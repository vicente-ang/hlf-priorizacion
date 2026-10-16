"""Cliente mínimo de Amazon Bedrock (Converse API) con salida JSON validada por esquema.

- Salida estructurada: `outputConfig.textFormat` con un JSON Schema (Bedrock la valida desde feb. 2026). Si la
  versión de boto3 o el modelo no la soporta, cae a "tool use" con `strict` y, al final, a pedir JSON en el texto.
- Caché en disco por (modelo, versión de la rúbrica, entrada): no se paga dos veces lo mismo y la corrida es
  reproducible. Carpeta: ia/cache (o HLF_IA_CACHE).
- Reintentos con espera ante limitación de tasa.
Variables: BEDROCK_MODEL_ID (id del modelo o inference profile), AWS_REGION. Sin ellas, `disponible()` es False.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

CACHE = Path(os.environ.get("HLF_IA_CACHE", Path(__file__).resolve().parent / "cache"))


def disponible(model_id: str | None = None) -> bool:
    return bool(model_id or os.environ.get("BEDROCK_MODEL_ID"))


def _clave(*partes) -> str:
    return hashlib.sha256("\x1f".join(str(p) for p in partes).encode()).hexdigest()[:32]


def _cliente(region: str | None):
    import boto3
    from botocore.config import Config
    return boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"),
                        config=Config(retries={"max_attempts": 6, "mode": "adaptive"}, read_timeout=120))


def _extraer_json(texto: str) -> dict:
    return json.loads(texto[texto.find("{"):texto.rfind("}") + 1])


def llamar_json(sistema: str, usuario: str, esquema: dict, nombre: str = "salida", model_id: str | None = None,
                region: str | None = None, max_tokens: int = 1200, temperatura: float = 0.0,
                usar_cache: bool = True) -> tuple[dict, dict]:
    """Devuelve (json, meta). meta trae tokens, modo usado y si vino de la caché."""
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        raise RuntimeError("Falta BEDROCK_MODEL_ID")
    clave = _clave(model_id, sistema, usuario, json.dumps(esquema, sort_keys=True), temperatura)
    archivo = CACHE / f"{clave}.json"
    if usar_cache and archivo.exists():
        d = json.loads(archivo.read_text(encoding="utf-8"))
        return d["salida"], {**d["meta"], "cache": True}
    cliente = _cliente(region)
    base = {"modelId": model_id, "system": [{"text": sistema}],
            "messages": [{"role": "user", "content": [{"text": usuario}]}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": temperatura}}
    intentos = [
        ("json_schema", {**base, "outputConfig": {"textFormat": {"type": "json_schema", "structure": {"jsonSchema": {
            "schema": json.dumps(esquema), "name": nombre, "description": "Respuesta estructurada"}}}}}),
        ("tool_strict", {**base, "toolConfig": {"tools": [{"toolSpec": {"name": nombre, "description": "Entrega la respuesta",
                                                                         "strict": True, "inputSchema": {"json": esquema}}}],
                                                "toolChoice": {"tool": {"name": nombre}}}}),
        ("texto", {**base, "messages": [{"role": "user", "content": [{"text": usuario + "\n\nResponde SOLO con un JSON que "
                                                                       "cumpla este esquema:\n" + json.dumps(esquema)}]}]}),
    ]
    ultimo_error = None
    for modo, pedido in intentos:
        for espera in (0, 2, 5, 10):
            if espera:
                time.sleep(espera)
            try:
                resp = cliente.converse(**pedido)
            except Exception as e:  # validación local de boto3, modelo sin soporte, limitación de tasa...
                ultimo_error = e
                nombre_err = type(e).__name__
                if "Throttling" in str(e) or "TooManyRequests" in str(e) or nombre_err == "ThrottlingException":
                    continue
                break   # probar el siguiente modo
            contenido = resp["output"]["message"]["content"]
            try:
                if modo == "tool_strict":
                    salida = next(c["toolUse"]["input"] for c in contenido if "toolUse" in c)
                else:
                    salida = _extraer_json("".join(c.get("text", "") for c in contenido))
            except Exception as e:
                ultimo_error = e
                break
            meta = {"modo": modo, "modelo": model_id, "tokens_entrada": resp.get("usage", {}).get("inputTokens"),
                    "tokens_salida": resp.get("usage", {}).get("outputTokens"), "cache": False}
            if usar_cache:
                CACHE.mkdir(parents=True, exist_ok=True)
                archivo.write_text(json.dumps({"salida": salida, "meta": meta}, ensure_ascii=False), encoding="utf-8")
            return salida, meta
    raise RuntimeError(f"Bedrock no respondió en ningún modo: {ultimo_error}")
