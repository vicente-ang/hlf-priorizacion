"""Agente regulador: mira los errores del agente clínico en TRAIN y propone reglas generales para la rúbrica.

No está en producción: solo trabaja en el ciclo de mejora (ia/ciclo.py). Ve la verdad del conjunto de
entrenamiento; NUNCA la de dev ni la de test. Sus propuestas pasan por `filtro_fuga` antes de tocar la rúbrica:
  - nada de identificadores de pacientes, fechas, ni nombres internos del generador (trayectoria, gravedad latente);
  - nada de frases copiadas de las notas de entrenamiento (6 palabras seguidas o más);
  - como máximo `MAX_CAMBIOS` reglas por iteración, cada una corta.
Así la rúbrica aprende criterios clínicos generales y no las respuestas de los casos.

Modos: "bedrock" (un modelo grande vía Converse) o "simulado" (elige de un catálogo de reglas según el tipo de
error más frecuente; solo para probar el circuito sin red).
"""
from __future__ import annotations

import json
import re
import unicodedata

import pandas as pd

MAX_CAMBIOS = 3
MAX_LARGO = 400            # caracteres por regla; al modelo se le pide 300 para dejar margen
PROHIBIDO = re.compile(r"(SIN-|PAC-|\b\d{4}-\d{2}-\d{2}\b|trayectoria|latente|riesgo_90d|categoria_ideal|semilla|"
                       r"generador|sintétic)", re.IGNORECASE)
ESQUEMA = {"type": "object", "properties": {
    "diagnostico_errores": {"type": "string"},
    "cambios": {"type": "array", "items": {"type": "object", "properties": {
        "regla": {"type": "string", "description": "Regla clínica general, una o dos frases, máximo 300 caracteres, "
                                                   "sin casos ni fechas"},
        "justificacion": {"type": "string"}}, "required": ["regla", "justificacion"], "additionalProperties": False}}},
    "required": ["diagnostico_errores", "cambios"], "additionalProperties": False}
SISTEMA = """Eres un médico revisor que audita a un agente que prioriza listas de espera. Recibes casos de
ENTRENAMIENTO donde el agente se equivocó, con la categoría correcta. Tu tarea: identificar PATRONES de error y
proponer como máximo 3 reglas CLÍNICAS GENERALES para agregar a su rúbrica. Prohibido: mencionar pacientes,
fechas, valores puntuales de un caso o copiar frases de las notas. Cada regla debe servir para pacientes que no
están aquí. Si el agente subestima, di qué señal no está viendo; si sobrestima, qué está sobrevalorando.
FORMATO DE CADA REGLA: una o dos frases, MÁXIMO 300 caracteres (las más largas se descartan sin probarlas). Deja
la explicación para el campo justificacion, no para la regla."""
CATALOGO_SIMULADO = {  # tipo de error -> regla general (el agente simulado reconoce estas frases)
    "notas": "Regla: dos o más notas seguidas que describen empeoramiento equivalen a deterioro claro, aunque no haya eventos.",
    "medicion": "Regla: una medición fuera de rango y en alza en las últimas tres tomas indica descompensación (al menos media).",
    "epicrisis": "Regla: una epicrisis con signos de alarma pesa aunque tenga más de un mes si no hay mejoría documentada después.",
}


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def ngramas(textos, n: int = 6) -> set:
    out = set()
    for t in textos:
        w = re.findall(r"\w+", _norm(t))
        out.update(" ".join(w[i:i + n]) for i in range(len(w) - n + 1))
    return out


def filtro_fuga(cambios: list[dict], ngramas_train: set, n: int = 6) -> tuple[list[dict], list[str]]:
    """Deja pasar solo reglas generales. Devuelve (aceptadas, motivos de rechazo)."""
    ok, rechazos = [], []
    for c in cambios[:MAX_CAMBIOS + 2]:
        regla = str(c.get("regla", "")).strip()
        w = re.findall(r"\w+", _norm(regla))
        copia = any(" ".join(w[i:i + n]) in ngramas_train for i in range(len(w) - n + 1))
        if not regla:
            continue
        if PROHIBIDO.search(regla):
            rechazos.append(f"menciona un caso, una fecha o el generador: «{regla[:80]}»")
        elif copia:
            rechazos.append(f"copia frases de las notas de entrenamiento: «{regla[:80]}»")
        elif len(regla) > MAX_LARGO:
            rechazos.append(f"regla demasiado larga ({len(regla)} caracteres, máximo {MAX_LARGO}): «{regla[:80]}…»")
        else:
            ok.append(c)
    return ok[:MAX_CAMBIOS], rechazos


def errores(propuestas: pd.DataFrame, verdad: pd.DataFrame, k: int = 12) -> pd.DataFrame:
    """Los errores más importantes primero: subtriaje de quien debía ser alta, luego deterioros no detectados,
    luego falsas alarmas."""
    o = {"alta": 0, "media": 1, "baja": 2}
    m = propuestas.merge(verdad, on=["id_paciente", "especialidad"], suffixes=("", "_v")).dropna(subset=["riesgo_90d"])
    m["error"] = m.categoria_ia.map(o) - m.categoria_ideal.map(o)        # >0: subestimó
    m["peso"] = m.error.clip(lower=0) * 3 + (m.error < 0) * 1 + m.riesgo_90d
    return m[m.error != 0].sort_values("peso", ascending=False).head(k)


def proponer(errs: pd.DataFrame, fichas: dict, rubrica: str, modo: str = "simulado", model_id: str | None = None,
             ya_probadas: list[str] | None = None, rechazadas: list[str] | None = None) -> dict:
    """`ya_probadas`: reglas que se probaron en DEV y no mejoraron. `rechazadas`: motivos del filtro en la
    iteración anterior (p. ej. largas), para que el regulador las corrija en vez de repetirlas."""
    ya_probadas = ya_probadas or []
    rechazadas = rechazadas or []
    if modo == "bedrock":
        from .bedrock import llamar_json
        casos = []
        for r in errs.itertuples():
            casos.append(f"### Caso\n{fichas.get(r.id_paciente, '')}\nEl agente dijo: {r.categoria_ia} (puntaje "
                         f"{r.puntaje_ia}). Correcto: {r.categoria_ideal}.")
        probadas = ("\n\nREGLAS YA PROBADAS QUE NO MEJORARON (no las repitas):\n- " + "\n- ".join(ya_probadas)
                    if ya_probadas else "")
        filtradas = ("\n\nTU PROPUESTA ANTERIOR NO PASÓ EL FILTRO (corrígela, no la repitas igual):\n- "
                     + "\n- ".join(rechazadas) if rechazadas else "")
        usuario = (f"RÚBRICA ACTUAL:\n{rubrica}{probadas}{filtradas}\n\nERRORES DE ENTRENAMIENTO ({len(casos)}):\n\n"
                   + "\n\n".join(casos)
                   + f"\n\nRecuerda: como máximo {MAX_CAMBIOS} reglas, cada una de 300 caracteres o menos.")
        salida, _ = llamar_json(SISTEMA, usuario, ESQUEMA, nombre="propuesta_regulador", model_id=model_id,
                                max_tokens=1500)
        return salida
    # simulado: el tipo de error más frecuente según lo que tenían los casos mal subestimados
    sub = errs[errs.error > 0]
    tipos = []
    for r in sub.itertuples():
        f = fichas.get(r.id_paciente, "")
        if "fuera de rango" in f:
            tipos.append("medicion")
        if "[epicrisis]" in f:
            tipos.append("epicrisis")
        tipos.append("notas")
    orden = pd.Series(tipos).value_counts().index.tolist() if tipos else []
    nuevas = [t for t in orden if CATALOGO_SIMULADO[t] not in rubrica and CATALOGO_SIMULADO[t] not in ya_probadas][:1]
    return {"diagnostico_errores": f"{len(sub)} subestimados entre los {len(errs)} errores revisados.",
            "cambios": [{"regla": CATALOGO_SIMULADO[t], "justificacion": "patrón más frecuente en los subestimados"}
                        for t in nuevas]}


def aplicar(rubrica: str, cambios: list[dict], version: str) -> str:
    if not cambios:
        return rubrica
    nuevo = re.sub(r"version: v\d+", f"version: {version}", rubrica, count=1)
    bloque = "\n".join(f"- {c['regla']}" for c in cambios)
    if "## Reglas aprendidas" not in nuevo:
        nuevo = nuevo.replace("## Qué entregar", "## Reglas aprendidas (ciclo regulador)\n\n## Qué entregar")
    return nuevo.replace("## Reglas aprendidas (ciclo regulador)\n", f"## Reglas aprendidas (ciclo regulador)\n{bloque}\n", 1)
