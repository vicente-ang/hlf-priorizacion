"""Prioridad propuesta para interconsultas que nadie priorizó (entrevista 6).

Hay especialidades que no priorizan: la interconsulta llega y espera sin alta/media/baja. El hospital pidió
que, si pasan unas tres semanas sin prioridad, el sistema le dé una "según criterio clínico, no al diagnóstico,
sino a lo que te escribieron en la interconsulta".

Diseño (igual que las indicaciones de control):
  1. Reglas: se buscan en el texto los criterios de la guía (motor/config/guias.yaml), con negaciones
     ("sin fiebre", "niega ideación suicida" no cuentan).
  2. Bedrock, solo si las reglas no encontraron nada: se le pide que diga QUÉ CRITERIOS DE LA GUÍA aparecen.
     La prioridad la decide la tabla, no la IA. El texto va sin RUT, teléfonos ni correos.
  3. Si nadie está seguro -> "revisar": sigue con la prioridad provisoria y queda en la cola del especialista.
La propuesta siempre queda marcada "confirmar": la valida el especialista o el jefe de especialidad.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from pathlib import Path

import yaml

from .privacidad import anonimizar_texto

GUIA_DEFECTO = Path(__file__).resolve().parent / "config" / "guias.yaml"
NEGACIONES = ("sin ", "niega ", "no ", "descarta ", "descartado ", "ausencia de ", "no presenta ", "no refiere ")
_cache: dict = {}


def cargar_guia(ruta: str | Path | None = None) -> dict:
    ruta = str(ruta or GUIA_DEFECTO)
    if ruta not in _cache:
        with open(ruta, encoding="utf-8") as f:
            _cache[ruta] = yaml.safe_load(f)
    return _cache[ruta]


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c)))


def _criterios(guia: dict, especialidad: str) -> dict[str, list[str]]:
    esp = (guia.get("especialidades") or {}).get(especialidad, {})
    return {nivel: [_norm(x) for x in (esp.get(nivel) or []) + (guia["general"].get(nivel) or [])]
            for nivel in ("alta", "baja")}


def _aparece(texto: str, criterio: str) -> bool:
    """El criterio aparece y no está negado en las 4 palabras anteriores."""
    for m in re.finditer(re.escape(criterio), texto):
        antes = re.split(r"[.;:,]", texto[max(0, m.start() - 40):m.start()])[-1]   # solo la misma frase
        ventana = " " + " ".join(antes.split()[-4:]) + " "
        if not any(" " + n in ventana for n in NEGACIONES):
            return True
    return False


def proponer_reglas(texto: str, especialidad: str, guia: dict | None = None) -> dict:
    guia = guia or cargar_guia()
    t = _norm(texto)
    if not t.strip():
        return {"prioridad": None, "criterios": [], "estado": "revisar", "fuente": "reglas",
                "motivo": "la interconsulta no trae texto"}
    crit = _criterios(guia, especialidad)
    for nivel in ("alta", "baja"):
        hallados = [c for c in crit[nivel] if _aparece(t, c)]
        if hallados:
            return {"prioridad": nivel, "criterios": hallados, "estado": "ok", "fuente": "reglas", "motivo": None}
    return {"prioridad": None, "criterios": [], "estado": "revisar", "fuente": "reglas",
            "motivo": "no aparece ningún criterio de la guía"}


def proponer_bedrock(texto: str, especialidad: str, guia: dict | None = None, model_id: str | None = None,
                     region: str | None = None) -> dict | None:
    """Bedrock solo dice qué criterios de la guía aparecen. None si no está configurado o falla."""
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        return None
    guia = guia or cargar_guia()
    crit = _criterios(guia, especialidad)
    prompt = ("Lee esta interconsulta de un hospital público chileno. Responde SOLO un JSON "
              '{"alta": [...], "baja": [...]} con los criterios de las listas que el texto AFIRMA (no los negados ni '
              "los dudosos). Copia los criterios tal cual. Si ninguno aparece, listas vacías. No inventes.\n"
              f"Criterios de alta: {crit['alta']}\nCriterios de baja: {crit['baja']}\n\n"
              f"Interconsulta ({especialidad}): {anonimizar_texto(texto)}")
    try:
        import boto3
        cliente = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))
        resp = cliente.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                                inferenceConfig={"maxTokens": 200, "temperature": 0})
        crudo = resp["output"]["message"]["content"][0]["text"]
        datos = json.loads(crudo[crudo.find("{"):crudo.rfind("}") + 1])
    except Exception:
        return None
    # solo cuentan criterios que existen en la guía (la IA no puede agregar criterios nuevos)
    alta = [c for c in datos.get("alta") or [] if _norm(c) in crit["alta"]]
    baja = [c for c in datos.get("baja") or [] if _norm(c) in crit["baja"]]
    if alta:
        return {"prioridad": "alta", "criterios": alta, "estado": "ok", "fuente": "bedrock", "motivo": None}
    if baja:
        return {"prioridad": "baja", "criterios": baja, "estado": "ok", "fuente": "bedrock", "motivo": None}
    return {"prioridad": None, "criterios": [], "estado": "revisar", "fuente": "bedrock",
            "motivo": "ni las reglas ni la IA encontraron criterios de la guía"}


def proponer(texto: str, especialidad: str, usar_bedrock: bool | None = None, guia: dict | None = None) -> dict:
    r = proponer_reglas(texto, especialidad, guia)
    if r["estado"] == "ok" or usar_bedrock is False or not str(texto or "").strip():
        return r
    ia = proponer_bedrock(texto, especialidad, guia)
    return ia or r


def proponer_todas(datos, usar_bedrock: bool | None = False) -> int:
    """Propone prioridad a todas las interconsultas sin priorizar (al cargar los datos). Por defecto solo con
    reglas, para que cargar sea rápido y sin costo; la interfaz puede releer una con Bedrock."""
    n = 0
    for p in datos.pacientes.values():
        if getattr(p, "sin_priorizar", False) and p.propuesta is None:
            p.propuesta = proponer(p.texto_interconsulta, p.especialidad, usar_bedrock=usar_bedrock)
            n += 1
    return n


def texto_propuesta(prop: dict | None) -> str:
    if not prop:
        return ""
    if prop["estado"] != "ok":
        return f"Por revisar: {prop['motivo']}."
    fuente = "reglas" if prop["fuente"] == "reglas" else "IA generativa (Bedrock), con los criterios de la guía"
    return f"Propuesta: {prop['prioridad']} por «{', '.join(prop['criterios'])}» (leído con {fuente}). Confirmar."
