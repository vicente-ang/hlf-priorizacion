r"""Explicaciones redactadas por Bedrock (Claude Haiku 4.5) para los primeros de cada especialidad.

La regla calcula el orden y los HECHOS de cada puesto (motor.explicar). Aquí Bedrock solo los REDACTA en lenguaje
claro, para los `n` primeros de la lista vigente de cada especialidad (los que la gestora mira primero). El resto
del front usa la explicación de la plantilla (determinista), que también es el respaldo si no hay red.

Caché en disco (misma idea que ia/bedrock): por (modelo, hechos) no se paga dos veces y la corrida es reproducible.
Carpeta: ia/cache (o HLF_IA_CACHE).

Uso:
  . .\entorno.ps1
  python -m ia.explicaciones                 # top 10 por especialidad -> ia/resultados/explicaciones_hlf.csv
  python -m ia.explicaciones --top 5 --datos data/dataset_hlf_ambulatorio
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor import Datos, cargar_regla, priorizar  # noqa: E402
from motor.explicar import construir_prompt, explicacion_plantilla, hechos as hechos_regla  # noqa: E402

CACHE = Path(os.environ.get("HLF_IA_CACHE", RAIZ / "ia" / "cache"))
SALIDA = RAIZ / "ia" / "resultados" / "explicaciones_hlf.csv"


def _clave(model_id: str, prompt: str) -> str:
    return "exp_" + hashlib.sha256(f"{model_id}\x1f{prompt}".encode()).hexdigest()[:30]


def _redactar_cacheado(r: dict, model_id: str | None, region: str | None) -> tuple[str, str]:
    """(texto, fuente). Usa la caché; si no hay modelo o falla, cae a la plantilla determinista."""
    respaldo = explicacion_plantilla(r)
    if not model_id:
        return respaldo, "plantilla"
    prompt = construir_prompt(r)
    archivo = CACHE / f"{_clave(model_id, prompt)}.json"
    if archivo.exists():
        d = json.loads(archivo.read_text(encoding="utf-8"))
        return d["texto"], "bedrock-cache"
    try:
        import boto3
        cli = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))
        resp = cli.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                            inferenceConfig={"maxTokens": 300, "temperature": 0})
        texto = resp["output"]["message"]["content"][0]["text"].strip()
        uso = resp.get("usage", {})
        CACHE.mkdir(parents=True, exist_ok=True)
        archivo.write_text(json.dumps({"texto": texto, "tokens_entrada": uso.get("inputTokens"),
                                       "tokens_salida": uso.get("outputTokens")}, ensure_ascii=False), encoding="utf-8")
        return texto, "bedrock"
    except Exception:
        return respaldo, "plantilla"


def generar(carpeta: str | Path | None = None, top: int = 10, hoy: str | date | None = None,
            model_id: str | None = None, region: str | None = None, salida: str | Path | None = None) -> pd.DataFrame:
    """Redacta la explicación de los `top` primeros de la lista vigente de cada especialidad."""
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    datos, cfg = Datos.cargar(carpeta), cargar_regla()
    hoy = date.fromisoformat(str(hoy)) if hoy else datos.fecha_referencia()
    lista = priorizar(datos, hoy, cfg, modo="carril_plazo")
    filas = []
    for esp, g in lista.groupby("especialidad"):
        for r in g.sort_values("puesto").head(top).to_dict("records"):
            texto, fuente = _redactar_cacheado(r, model_id, region)
            filas.append({"id_paciente": r["id_paciente"], "especialidad": esp, "puesto": int(r["puesto"]),
                          "prioridad": r["prioridad_dinamica"], "explicacion_bedrock": texto, "fuente": fuente,
                          "hechos": json.dumps(hechos_regla(r), ensure_ascii=False)})
    df = pd.DataFrame(filas)
    destino = Path(salida) if salida else SALIDA
    destino.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(destino, index=False)
    return df


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--hoy")
    ap.add_argument("--salida")
    a = ap.parse_args()
    df = generar(a.datos, a.top, a.hoy, salida=a.salida)
    fuentes = df.fuente.value_counts().to_dict()
    print(f"{len(df)} explicaciones ({df.especialidad.nunique()} especialidades, top {a.top}). "
          f"Fuentes: {fuentes}. -> {a.salida or SALIDA}")


if __name__ == "__main__":
    main()
