"""Agente clínico: lee la ficha de cada paciente y propone categoría, puntaje y evidencia.

Diseño (por qué así y no "que el LLM ordene la lista"):
  - PUNTUAL: evalúa a cada paciente por separado con una rúbrica con anclas. El orden sale de ordenar los puntajes.
    Escala a 26.000 pacientes (en paralelo o por lotes), solo se re-evalúa a quien tuvo datos nuevos, no depende
    del orden anterior (no se "ancla") y cada puesto queda auditable con su evidencia.
  - CIEGO al orden previo y a la verdad: la ficha trae solo lo observable hasta la fecha de corte.
  - HÍBRIDO con la regla: la regla pone un piso de seguridad (evento grave relacionado en 30 días => al menos
    alta). La IA puede proponer SUBIR; BAJAR queda como propuesta que confirma una persona.

Modos:
  bedrock   Amazon Bedrock (Converse + JSON validado). Requiere BEDROCK_MODEL_ID y AWS_REGION.
  simulado  sin red: reglas + palabras clave. Sirve para probar el circuito y como línea base; NO es la IA.

Uso:
  python -m ia.agente --datos data/mundo/dev --rubrica ia/rubrica/v0.md --modo bedrock --salida ia/resultados/dev_v0.csv
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor import Datos, cargar_regla, evaluar_paciente  # noqa: E402
from motor.pertinencia import es_pertinente  # noqa: E402
from motor.puntaje import ETIQUETAS_SUBTIPO  # noqa: E402
from motor.privacidad import anonimizar_texto  # noqa: E402

ORDEN = {"alta": 0, "media": 1, "baja": 2}
ESQUEMA = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string", "enum": ["alta", "media", "baja"]},
        "puntaje": {"type": "integer", "description": "0 a 100 según las anclas de la rúbrica"},
        "direccion": {"type": "string", "enum": ["sube", "igual", "baja"]},
        "criterios": {"type": "object", "properties": {
            "evento_agudo": {"type": "integer", "description": "0 a 3"},
            "tendencia": {"type": "integer", "description": "-2 (mejora) a 3 (empeora)"},
            "alarma_especifica": {"type": "integer", "description": "0 a 3"},
            "comorbilidad": {"type": "integer", "description": "0 a 2"},
            "recurrencia": {"type": "integer", "description": "0 a 2"}},
            "required": ["evento_agudo", "tendencia", "alarma_especifica", "comorbilidad", "recurrencia"],
            "additionalProperties": False},
        "evidencia": {"type": "array", "items": {"type": "object", "properties": {
            "fecha": {"type": "string"}, "fuente": {"type": "string"}, "cita": {"type": "string"}},
            "required": ["fecha", "fuente", "cita"], "additionalProperties": False}},
        "ignorado": {"type": "array", "items": {"type": "string"}},
        "confianza": {"type": "string", "enum": ["alta", "media", "baja"]},
        "resumen": {"type": "string"},
    },
    "required": ["categoria", "puntaje", "direccion", "criterios", "evidencia", "ignorado", "confianza", "resumen"],
    "additionalProperties": False,
}


# ------------------------------------------------------------------------------------------------ ficha
def cargar_notas(carpeta: Path) -> dict[str, list]:
    f = Path(carpeta) / "notas_clinicas.csv"
    if not f.exists():
        return {}
    df = pd.read_csv(f)
    df["fecha"] = pd.to_datetime(df.fecha).dt.date
    return {pid: g.sort_values("fecha").to_dict("records") for pid, g in df.groupby("id_paciente")}


def ficha(p, notas: list, corte: date, n_eventos: int = 15, n_notas: int = 8) -> str:
    """Lo que ve el agente: solo lo observable hasta `corte`. Sin puesto, sin orden previo, sin verdad."""
    dias = (corte - p.fecha_ingreso).days
    lin = [f"Paciente {p.id_paciente} · {p.edad} años · {p.sexo} · {p.especialidad} ({p.sub_especialidad})",
           f"Derivado por: {p.diagnostico} · desde {p.origen}",
           f"Prioridad del especialista al ingresar (T1): {p.prioridad_inicial if not p.sin_priorizar else 'sin priorizar'}"
           f" · en lista desde {p.fecha_ingreso} ({dias} días)",
           f"Fecha de hoy (corte): {corte}"]
    if p.texto_interconsulta:
        lin.append(f"Texto de la interconsulta: {anonimizar_texto(p.texto_interconsulta)}")
    rutina = ("control", "control crónico", "control de rutina")       # los controles se ven en las notas
    evs = [e for e in p.eventos if e["fecha"] <= corte and e["subtipo"] not in rutina][-n_eventos:]
    lin.append("Eventos mientras espera (del más reciente al más antiguo):" if evs else "Eventos: ninguno registrado.")
    for e in reversed(evs):
        dx = e.get("diagnostico_cie10")
        dx = f" · dx {dx}" + (f" {e.get('diagnostico_texto')}" if e.get("diagnostico_texto") == e.get("diagnostico_texto")
                               and e.get("diagnostico_texto") else "") if isinstance(dx, str) and dx else ""
        lin.append(f"- {e['fecha']} (hace {(corte - e['fecha']).days} d): {ETIQUETAS_SUBTIPO.get(e['subtipo'], e['subtipo'])}"
                   f" [{e['severidad']}]{dx}")
    med = [m for m in p.mediciones if m["fecha"] <= corte][-8:]
    if med:
        lin.append("Mediciones (de la más antigua a la más reciente):")
        lin += [f"- {m['fecha']}: {m['tipo_medicion']} = {m['valor']:g} {m['unidad']}"
                f"{' (fuera de rango)' if m['fuera_de_rango'] else ''}" for m in med]
    ns = [n for n in notas if n["fecha"] <= corte][-n_notas:]
    if ns:
        lin.append("Notas clínicas (de la más antigua a la más reciente):")
        lin += [f"- {n['fecha']} [{n['fuente']}]: {anonimizar_texto(str(n['texto']))}" for n in ns]
    return "\n".join(lin)


# ------------------------------------------------------------------------------------------------ modo simulado
def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


ALARMA = ["reposo", "ortopnea", "sincope", "saturacion 8", "hipoglicemias severas", "pie diabetico", "melena",
          "ictericia", "ascitis", "a repeticion", "focalidad", "ideacion suicida", "psicotic", "imposibilidad de marcha",
          "perdida de fuerza", "exacerbacion", "cf iii", "no cicatriza"]
EMPEORA = ["progresion", "peor que", "empeor"]
MEJORA = ["mejoria", "buena respuesta", "asintomatic", "sin cambios", "estable", "controlad"]
EXPLICITO = ["adelantar", "priorizar"]
DIRECTIVAS = {  # reglas que el regulador simulado puede agregar; el agente simulado las reconoce por su texto
    "notas_consecutivas": "dos o más notas seguidas que describen empeoramiento",
    "medicion_en_alza": "medición fuera de rango y en alza en las últimas tres tomas",
    "epicrisis_alarma": "una epicrisis con signos de alarma pesa aunque tenga más de un mes",
}


def evaluar_simulado(p, notas: list, corte: date, cfg: dict, rubrica: str) -> dict:
    activas = {k for k, frase in DIRECTIVAS.items() if frase in rubrica}
    pts, evid, ignor = 10, [], []
    ev = [e for e in p.eventos if e["fecha"] <= corte]
    graves = [e for e in ev if e["severidad"] == "grave"]
    for e in ev:
        if not es_pertinente(p, e, cfg) and e["severidad"] != "leve":
            ignor.append(f"{e['fecha']} {e.get('diagnostico_texto') or e.get('diagnostico_cie10')}")
    graves_rel = [e for e in graves if es_pertinente(p, e, cfg)]
    recientes = [e for e in graves_rel if (corte - e["fecha"]).days <= 30]
    if recientes:
        pts = max(pts, 92 if any(e["subtipo"] == "ingreso UCI" for e in recientes) else 85)
        evid.append({"fecha": str(recientes[-1]["fecha"]), "fuente": "evento", "cita": recientes[-1]["subtipo"]})
    elif [e for e in graves_rel if (corte - e["fecha"]).days <= 90]:
        pts = max(pts, 62)
    rec = len({e["fecha"] for e in graves_rel if (corte - e["fecha"]).days <= 365})
    pts += 6 * min(rec, 3)
    ns = [n for n in notas if n["fecha"] <= corte and n["fuente"] in ("CESFAM", "epicrisis")]
    ultimas = ns[-2:]
    for n in ultimas:
        t = _norm(n["texto"])
        if any(k in t for k in EXPLICITO):
            pts = max(pts, 78)
            evid.append({"fecha": str(n["fecha"]), "fuente": n["fuente"], "cita": n["texto"][:120]})
        if any(k in t for k in ALARMA):
            pts = max(pts, 70)
            evid.append({"fecha": str(n["fecha"]), "fuente": n["fuente"], "cita": n["texto"][:120]})
        if any(k in t for k in EMPEORA):
            pts += 8
        if any(k in t for k in MEJORA) and not any(k in t for k in ALARMA):
            pts -= 6
    if "notas_consecutivas" in activas and len(ultimas) == 2 and all(any(k in _norm(n["texto"]) for k in EMPEORA)
                                                                     for n in ultimas):
        pts = max(pts, 72)
    if "epicrisis_alarma" in activas:
        for n in ns[-4:]:
            if n["fuente"] == "epicrisis" and any(k in _norm(n["texto"]) for k in ALARMA):
                pts = max(pts, 74)
    med = [m for m in p.mediciones if m["fecha"] <= corte]
    if med and med[-1]["fuera_de_rango"]:
        pts += 6
    if "medicion_en_alza" in activas and len(med) >= 3 and all(m["fuera_de_rango"] for m in med[-3:]):
        pts = max(pts, 60)
    from motor.clusters import charlson
    ch, _ = charlson([p.diagnostico.split(" ")[0]] + [c["cie10"] for c in (p.comorbilidades or [])])
    pts += 3 * min(ch, 3)
    pts = int(max(0, min(100, pts)))
    cat = "alta" if pts >= 70 else "media" if pts >= 40 else "baja"
    d = ORDEN[cat] - ORDEN[p.prioridad_inicial]
    return {"categoria": cat, "puntaje": pts, "direccion": "sube" if d < 0 else "baja" if d > 0 else "igual",
            "criterios": {"evento_agudo": 3 if recientes else 0, "tendencia": 0, "alarma_especifica": 0,
                          "comorbilidad": min(ch, 2), "recurrencia": min(rec, 2)},
            "evidencia": evid[:4], "ignorado": ignor[:4], "confianza": "media",
            "resumen": "Modo simulado (reglas y palabras clave), sin Bedrock."}


# ------------------------------------------------------------------------------------------------ evaluación
def _evaluar_uno(p, notas, corte, cfg, rubrica, modo, model_id):
    if modo == "bedrock":
        from .bedrock import llamar_json
        salida, meta = llamar_json(rubrica, ficha(p, notas, corte), ESQUEMA, nombre="evaluacion_paciente",
                                   model_id=model_id)
    else:
        salida, meta = evaluar_simulado(p, notas, corte, cfg, rubrica), {"modo": "simulado"}
    salida["puntaje"] = int(max(0, min(100, int(salida.get("puntaje", 0)))))
    return salida, meta


def evaluar(carpeta: str | Path, rubrica: str, modo: str = "simulado", corte: date | None = None,
            model_id: str | None = None, concurrencia: int | None = None, ids: list | None = None) -> pd.DataFrame:
    """Evalúa a todos los pacientes en lista de `carpeta` y devuelve una fila por paciente con la propuesta de la
    IA, la de la regla y la final (híbrida)."""
    datos, cfg = Datos.cargar(carpeta), cargar_regla()
    corte = corte or datos.fecha_referencia()
    notas = cargar_notas(Path(carpeta))
    pacs = [p for p in datos.pacientes.values() if (ids is None or p.id_paciente in ids)]
    reglas = {p.id_paciente: evaluar_paciente(p, corte, cfg) for p in pacs}
    pacs = [p for p in pacs if reglas[p.id_paciente]["en_lista"]]
    conc = concurrencia or int(os.environ.get("BEDROCK_CONCURRENCIA", "6"))

    def tarea(p):
        try:
            s, meta = _evaluar_uno(p, notas.get(p.id_paciente, []), corte, cfg, rubrica, modo, model_id)
            return p, s, meta, None
        except Exception as e:  # el paciente queda con la regla y marcado para revisar
            return p, None, {}, str(e)

    if modo == "bedrock" and conc > 1:
        with ThreadPoolExecutor(max_workers=conc) as ex:
            resultados = list(ex.map(tarea, pacs))
    else:
        resultados = [tarea(p) for p in pacs]
    filas = []
    for p, s, meta, err in resultados:
        r = reglas[p.id_paciente]
        piso = "alta" if r["carril_rapido"] else None
        if s is None:
            cat_ia, pts, dirc, evid, conf, res, ign = None, None, None, [], None, f"error: {err}", []
        else:
            cat_ia, pts, dirc, evid, conf, res = (s["categoria"], s["puntaje"], s["direccion"], s["evidencia"],
                                                  s["confianza"], s["resumen"])
            ign = s.get("ignorado") or []
        # Híbrido: nunca bajo T1 sin una persona; la IA puede subir; la regla pone el piso (evento grave => alta)
        candidatas = [p.prioridad_inicial] + ([cat_ia] if cat_ia else []) + ([piso] if piso else [])
        cat_final = min(candidatas, key=lambda c: ORDEN[c])
        filas.append({"id_paciente": p.id_paciente, "especialidad": p.especialidad, "fecha_ingreso": p.fecha_ingreso,
                      "prioridad_inicial": p.prioridad_inicial, "categoria_regla": r["prioridad_dinamica"],
                      "carril_rapido": r["carril_rapido"],
                      "categoria_ia": cat_ia, "puntaje_ia": pts, "direccion_ia": dirc,
                      # sube/baja se calculan con las categorías (el campo "direccion" del modelo es su lectura
                      # de la tendencia y no siempre coincide con el cambio de grupo)
                      "propone_subir": bool(cat_ia) and ORDEN[cat_ia] < ORDEN[p.prioridad_inicial],
                      "propone_bajar": bool(cat_ia) and ORDEN[cat_ia] > ORDEN[p.prioridad_inicial],
                      "categoria_final": cat_final, "confianza": conf,
                      "evidencia": json.dumps(evid, ensure_ascii=False), "resumen": res,
                      "ignorado": json.dumps(ign, ensure_ascii=False),
                      "modo": meta.get("modo"), "modelo": meta.get("modelo") or ("simulado" if modo == "simulado" else None),
                      "tokens_entrada": meta.get("tokens_entrada"),
                      "tokens_salida": meta.get("tokens_salida"), "error": err})
    df = pd.DataFrame(filas)
    v = re.search(r"version:\s*(\S+)", rubrica)
    df["version_rubrica"] = v.group(1) if v else "sin versión"
    df["corte"] = corte
    return ordenar(df)


def ordenar(df: pd.DataFrame) -> pd.DataFrame:
    """Puesto IA (solo puntaje) y puesto final (categoría híbrida, luego puntaje, luego antigüedad) por especialidad."""
    if df.empty:
        return df
    df = df.copy()
    df["_c"] = df.categoria_final.map(ORDEN)
    df["_p"] = -df.puntaje_ia.fillna(-1)
    df = df.sort_values(["especialidad", "_c", "_p", "fecha_ingreso"])
    df["puesto_final"] = df.groupby("especialidad").cumcount() + 1
    df = df.sort_values(["especialidad", "_p", "fecha_ingreso"])
    df["puesto_ia"] = df.groupby("especialidad").cumcount() + 1
    return df.drop(columns=["_c", "_p"]).sort_values(["especialidad", "puesto_final"]).reset_index(drop=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default=str(RAIZ / "data" / "dataset_hlf_ambulatorio"))
    ap.add_argument("--rubrica", default=str(RAIZ / "ia" / "rubrica" / "v0.md"))
    ap.add_argument("--modo", choices=["bedrock", "simulado"], default="bedrock" if os.environ.get("BEDROCK_MODEL_ID") else "simulado")
    ap.add_argument("--corte")
    ap.add_argument("--salida")
    ap.add_argument("--muestra", type=int, help="evaluar solo N pacientes (para probar costos)")
    a = ap.parse_args()
    rubrica = Path(a.rubrica).read_text(encoding="utf-8")
    ids = None
    if a.muestra:
        le = pd.read_csv(Path(a.datos) / "lista_espera.csv")
        ids = list(le.sample(min(a.muestra, len(le)), random_state=1).id_paciente)
    df = evaluar(a.datos, rubrica, a.modo, date.fromisoformat(a.corte) if a.corte else None, ids=ids)
    salida = Path(a.salida or RAIZ / "ia" / "resultados" / f"propuestas_{Path(a.datos).name}_{a.modo}.csv")
    salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida, index=False)
    print(f"{len(df)} pacientes evaluados ({a.modo}). Proponen subir de grupo: {df.propone_subir.sum()}, "
          f"proponen bajar: {df.propone_bajar.sum()}, errores: {df.error.notna().sum()}. -> {salida}")


if __name__ == "__main__":
    main()
