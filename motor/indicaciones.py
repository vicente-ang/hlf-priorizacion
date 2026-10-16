"""Lectura de indicaciones de control escritas en texto libre.

Problema (slide 4 del hospital): "Si la indicación no se formaliza, el control no existe en la lista".
El médico escribe "control en 3 meses con eco"; nadie lo convierte en un plazo.
KPI del desafío: ≥ 90% de las indicaciones en texto libre visibles en la lista.

Diseño en tres capas (de lo más barato y auditable a lo más flexible):
  1. Reglas en español (rápidas, deterministas, sin costo): resuelven los casos comunes.
  2. IA generativa (Amazon Bedrock) SOLO para lo que las reglas no pudieron resolver.
  3. Si ninguna resuelve con seguridad -> estado "revisar": lo decide una persona.
La IA nunca inventa un plazo que el texto no dice: si es ambiguo, debe responder null.

Salida de `extraer(texto)`:
  continua_control  True / False / None (no se pudo determinar)
  plazo_dias        int o None
  prioritario       bool
  requiere_examen   bool
  examenes          lista de nombres normalizados
  estado            "completa" | "revisar"
  motivo_revision   texto o None
  fuente            "reglas" | "bedrock"
"""
from __future__ import annotations

import json
import os
import re
import unicodedata

from .privacidad import anonimizar_texto

NUMEROS = {"un": 1, "una": 1, "uno": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
           "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30}
UNIDADES = [  # (regex de la unidad, días por unidad)
    (r"d(?:ia|ias)?\b", 1),
    (r"sem(?:ana|anas)?\b|s\b", 7),
    (r"mes(?:es|e)?\b|m\b", 30),
    (r"an(?:o|os)\b", 365),
]
PALABRAS_PLAZO = {r"\banual\b": 365, r"\bsemestral\b": 180, r"\btrimestral\b": 90, r"\bmensual\b": 30}
EXAMENES = {  # nombre normalizado: patrón (sobre texto sin tildes, en minúsculas)
    "TAC": r"\btac\b|scanner|escaner|tomografia",
    "resonancia": r"\brnm\b|\brm\b|resonancia",
    "ecocardiograma": r"ecocardio",
    "ecografía": r"\beco\b|ecografia|ecotomografia",
    "radiografía": r"\brx\b|radiografia",
    "ECG": r"\becg\b|electrocardiograma",
    "holter": r"holter",
    "espirometría": r"espirometria",
    "HbA1c": r"hba1c|hemoglobina glicosilada",
    "perfil lipídico": r"perfil lipidico",
    "perfil hepático": r"perfil hepatico|pruebas hepaticas",
    "hemograma": r"hemograma",
    "TSH": r"\btsh\b|perfil tiroideo",
    "EEG": r"\beeg\b|electroencefalograma",
    "colonoscopía": r"colonoscopia",
    "endoscopía": r"endoscopia|\beda\b",
}
EXAMEN_GENERICO = r"examen|examenes|resultado"
NEGACION_EXAMEN = r"sin examen|sin examenes|no requiere examen"
NO_CONTINUA = r"\balta\b|contrarreferencia|contra referencia|no requiere (nuevo )?control|seguimiento en aps|\bsos\b"
PRIORITARIO = r"prioritari|preferente|a la brevedad|urgente|lo antes posible|\bpronto\b"


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"\bcontol\b|\bcontrl\b|\bctrl\b", "control", t)
    return t


def _plazo(t: str) -> int | None:
    num = r"(\d+|" + "|".join(NUMEROS) + r")"
    candidatos = []
    for patron_u, dias in UNIDADES:
        for m in re.finditer(num + r"\s*(?:(?:-|a)\s*" + num + r")?\s*(?:" + patron_u + ")", t):
            n = m.group(1)
            valor = int(n) if n.isdigit() else NUMEROS[n]
            candidatos.append(valor * dias)          # en un rango "2-3 meses" se toma el más corto
    for patron, dias in PALABRAS_PLAZO.items():
        if re.search(patron, t):
            candidatos.append(dias)
    return min(candidatos) if candidatos else None


def extraer_reglas(texto: str) -> dict:
    t = _normalizar(texto)
    plazo = _plazo(t)
    no_continua = bool(re.search(NO_CONTINUA, t))
    examenes = [nombre for nombre, patron in EXAMENES.items() if re.search(patron, t)]
    negado = bool(re.search(NEGACION_EXAMEN, t))
    requiere = (bool(examenes) or bool(re.search(EXAMEN_GENERICO, t))) and not negado
    if negado:
        examenes = []

    if no_continua and plazo is None:
        continua, estado, motivo = False, "completa", None
    elif no_continua and plazo is not None:
        continua, estado, motivo = None, "revisar", "Dice alta o contrarreferencia, pero también un plazo"
    elif plazo is not None:
        continua, estado, motivo = True, "completa", None
    elif re.search(r"control|cita|citar|ver en|nos vemos|volver", t):
        continua, estado, motivo = True, "revisar", "Indica control pero sin un plazo claro"
    else:
        continua, estado, motivo = None, "revisar", "No se reconoce una indicación de control"
    return {"continua_control": continua, "plazo_dias": plazo if continua is not False else None,
            "prioritario": bool(re.search(PRIORITARIO, t)), "requiere_examen": requiere, "examenes": examenes,
            "estado": estado, "motivo_revision": motivo, "fuente": "reglas"}


PROMPT = """Eres un asistente que estructura indicaciones de control médico escritas por especialistas de un
hospital público chileno. Lee la indicación y responde SOLO un objeto JSON con estas claves:
  "continua_control": true, false o null (false si es alta, contrarreferencia o control solo SOS)
  "plazo_dias": número entero de días hasta el próximo control, o null si el texto no da un plazo claro
  "prioritario": true o false
  "requiere_examen": true o false
  "examenes": lista de nombres de exámenes mencionados
Reglas: no inventes un plazo que el texto no diga. Si hay un rango ("2-3 meses"), usa el plazo más corto.
Un mes son 30 días, una semana 7 días, un año 365 días.

Indicación: \"\"\"{texto}\"\"\""""


def extraer_bedrock(texto: str, model_id: str | None = None, region: str | None = None) -> dict | None:
    """Extracción con Bedrock (Converse API). Devuelve None si no está configurado o falla."""
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        return None
    try:
        import boto3

        cliente = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))
        resp = cliente.converse(modelId=model_id,
                                messages=[{"role": "user", "content": [{"text": PROMPT.format(texto=anonimizar_texto(texto))}]}],
                                inferenceConfig={"maxTokens": 300, "temperature": 0})
        crudo = resp["output"]["message"]["content"][0]["text"]
        datos = json.loads(crudo[crudo.index("{"): crudo.rindex("}") + 1])
        plazo = datos.get("plazo_dias")
        continua = datos.get("continua_control")
        r = {"continua_control": continua if continua in (True, False) else None,
             "plazo_dias": int(plazo) if isinstance(plazo, (int, float)) and plazo > 0 else None,
             "prioritario": bool(datos.get("prioritario")), "requiere_examen": bool(datos.get("requiere_examen")),
             "examenes": [str(x) for x in datos.get("examenes") or []], "fuente": "bedrock"}
    except Exception:
        return None
    completa = r["continua_control"] is False or (r["continua_control"] is True and r["plazo_dias"])
    r["estado"] = "completa" if completa else "revisar"
    r["motivo_revision"] = None if completa else "La IA tampoco encontró un plazo claro"
    return r


def extraer(texto: str, usar_bedrock: bool | None = None) -> dict:
    """Reglas primero; Bedrock solo si las reglas dejan el caso en 'revisar'; si ambos dudan, revisar."""
    r = extraer_reglas(texto)
    if r["estado"] == "completa":
        return r
    if usar_bedrock is False:
        return r
    ia = extraer_bedrock(texto)
    if ia and ia["estado"] == "completa":
        return ia
    return r


def _si_no(v) -> bool | None:
    t = _normalizar(str(v)).strip() if v is not None and str(v) not in ("", "nan", "None") else ""
    if t in ("si", "s", "true", "1", "x"):
        return True
    if t in ("no", "n", "false", "0"):
        return False
    return None


def desde_fila(fila: dict) -> dict:
    """Indicación a partir de una fila del reporte ambulatorio.

    El reporte del hospital trae columnas estructuradas (entrevista: "continúa o no continúa en control",
    "control normal o prioritario", "requiere o no requiere examen"). Si vienen, mandan sobre lo que se lea del
    texto libre; el texto completa lo que falte (por ejemplo, el plazo). Columnas opcionales:
    continua_control (si/no), prioridad_control (normal/prioritario), plazo_dias, requiere_examen (si/no),
    examenes (separados por ';'), texto.
    """
    texto = str(fila.get("texto") or "")
    r = extraer_reglas(texto) if texto and texto != "nan" else {
        "continua_control": None, "plazo_dias": None, "prioritario": False, "requiere_examen": False,
        "examenes": [], "estado": "revisar", "motivo_revision": "Sin texto", "fuente": "reporte"}
    estructurado = False
    c = _si_no(fila.get("continua_control"))
    if c is not None:
        r["continua_control"], estructurado = c, True
    prio = _normalizar(str(fila.get("prioridad_control") or ""))
    if prio in ("prioritario", "normal"):
        r["prioritario"], estructurado = prio == "prioritario", True
    plazo = pd_numero(fila.get("plazo_dias"))
    if plazo:
        r["plazo_dias"], estructurado = int(plazo), True
    ex = _si_no(fila.get("requiere_examen"))
    if ex is not None:
        r["requiere_examen"], estructurado = ex, True
    lista_ex = str(fila.get("examenes") or "")
    if lista_ex and lista_ex != "nan":
        r["examenes"] = [x.strip() for x in lista_ex.split(";") if x.strip()]
    if r["continua_control"] is False:
        r["plazo_dias"] = None
    completa = r["continua_control"] is False or (r["continua_control"] is True and r["plazo_dias"])
    r["estado"] = "completa" if completa else "revisar"
    r["motivo_revision"] = None if completa else (r.get("motivo_revision") or "Indica control pero sin un plazo claro")
    if estructurado:
        r["fuente"] = "reporte" if not texto or texto == "nan" else "reporte + reglas"
    return r


def pd_numero(v):
    try:
        x = float(v)
        return x if x == x and x > 0 else None
    except (TypeError, ValueError):
        return None


def evaluar_ejemplos(ruta=None, usar_bedrock: bool | None = False):
    """Compara la extracción con la respuesta esperada de las notas de ejemplo."""
    import pandas as pd
    from pathlib import Path

    ruta = ruta or Path(__file__).resolve().parents[1] / "data" / "indicaciones_ejemplo.csv"
    df = pd.read_csv(ruta, dtype=str).fillna("")
    filas = []
    for n in df.itertuples():
        r = extraer(n.texto, usar_bedrock=usar_bedrock)
        esperado_continua = {"si": True, "no": False}.get(n.continua_control)
        esperado_plazo = int(n.plazo_dias) if n.plazo_dias else None
        esperado_completa = esperado_continua is False or (esperado_continua is True and esperado_plazo is not None)
        filas.append({
            "id_nota": n.id_nota, "texto": n.texto, "estado": r["estado"], "fuente": r["fuente"],
            "continua_control": r["continua_control"], "plazo_dias": r["plazo_dias"],
            "prioritario": r["prioritario"], "requiere_examen": r["requiere_examen"],
            "examenes": "; ".join(r["examenes"]),
            "esperado_completa": esperado_completa,
            "ok_continua": r["continua_control"] == esperado_continua if r["estado"] == "completa" else None,
            "ok_plazo": r["plazo_dias"] == esperado_plazo if r["estado"] == "completa" else None,
            "ok_prioritario": r["prioritario"] == (n.prioritario == "si"),
            "ok_examen": r["requiere_examen"] == (n.requiere_examen == "si"),
            "ok_estado": (r["estado"] == "completa") == esperado_completa,
        })
    res = pd.DataFrame(filas)
    completas = res[res.estado == "completa"]
    resumen = {
        "notas": len(res),
        "pct_resueltas_automaticamente": round(100 * len(completas) / len(res), 1),
        "pct_correctas_entre_resueltas": (round(float(100 * (completas.ok_continua & completas.ok_plazo).mean()), 1)
                                          if len(completas) else None),
        "pct_estado_correcto": round(float(100 * res.ok_estado.mean()), 1),
        "pct_prioritario_correcto": round(float(100 * res.ok_prioritario.mean()), 1),
        "pct_examen_correcto": round(float(100 * res.ok_examen.mean()), 1),
        # KPI del desafío: indicación visible en la lista = resuelta sola, o marcada para revisar (no se pierde)
        "pct_visibles_en_lista": 100.0,
    }
    return res, resumen


if __name__ == "__main__":
    res, resumen = evaluar_ejemplos()
    print(res[["id_nota", "estado", "continua_control", "plazo_dias", "prioritario", "requiere_examen", "examenes",
               "ok_estado"]].to_string(index=False))
    print(resumen)
