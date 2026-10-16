"""Lo que la persona hace con las propuestas del agente IA: aceptar, rechazar, dar prioridad absoluta o revertir.

Funciones puras (sin Streamlit) para que la pestaña "Agente IA" y los tests usen la misma lógica:

  aplicar(prop, decisiones, absolutos)  -> propuestas con la categoría y el puesto que resultan de las decisiones
  revisar_pertinencia(prop, datos, cfg) -> pacientes cuya evidencia cita un evento que la regla marca como
                                           no relacionado y que la IA no declaró como descartado (revisar)
  descartados(prop, datos, cfg)         -> cuántos eventos no relacionados (según la regla) declaró la IA como
                                           descartados en `ignorado`

Reglas (las mismas que la pestaña explica):
  - sin decisión: categoría híbrida (la IA puede subir; nunca baja sola de T1; evento grave relacionado => alta);
  - aceptada: la categoría de la IA, también si baja (lo confirmó una persona), pero nunca bajo el piso de la regla;
  - rechazada: se ignora a la IA (queda T1 con el piso de la regla);
  - prioridad absoluta: primero de su especialidad, en el orden en que se pidió, con motivo;
  - revertir: se borra la decisión y el paciente vuelve a la propuesta original (queda registrado).
"""
from __future__ import annotations

import json

import pandas as pd

ORDEN = {"alta": 0, "media": 1, "baja": 2}
ETIQUETA = {"ia_aceptada": "aceptada", "ia_rechazada": "rechazada", "prioridad_absoluta": "prioridad absoluta"}


def _mas_alta(*cats) -> str:
    return min((c for c in cats if isinstance(c, str) and c in ORDEN), key=ORDEN.get)


def categoria_tras_decision(fila, decision: str | None) -> str:
    piso = "alta" if bool(fila.get("carril_rapido")) else None
    t1 = fila.get("prioridad_inicial")
    if decision == "ia_aceptada" and isinstance(fila.get("categoria_ia"), str):
        return _mas_alta(fila["categoria_ia"], piso)
    if decision == "ia_rechazada":
        return _mas_alta(t1, piso)
    return fila.get("categoria_final") or _mas_alta(t1, piso)


def aplicar(prop: pd.DataFrame, decisiones: dict[str, dict] | None = None,
            absolutos: list[str] | None = None) -> pd.DataFrame:
    """`decisiones`: id_paciente -> {"decision": "ia_aceptada" | "ia_rechazada", ...}.
    `absolutos`: ids con prioridad absoluta, en el orden en que se pidió.
    Devuelve una copia con `categoria_vista`, `estado` y `puesto_vista` (por especialidad)."""
    decisiones = decisiones or {}
    absolutos = [a for a in (absolutos or []) if a in set(prop.id_paciente)]
    if prop.empty:
        return prop.assign(categoria_vista=[], estado=[], puesto_vista=[])
    df = prop.copy()
    df["categoria_vista"] = [categoria_tras_decision(f, decisiones.get(f["id_paciente"], {}).get("decision"))
                             for f in df.to_dict("records")]
    df["estado"] = [("prioridad absoluta" if pid in absolutos else
                     ETIQUETA.get(decisiones.get(pid, {}).get("decision"), "pendiente")) for pid in df.id_paciente]
    rango_abs = {pid: i for i, pid in enumerate(absolutos)}
    df["_a"] = df.id_paciente.map(rango_abs).fillna(len(absolutos)).astype(int)
    df["_c"] = df.categoria_vista.map(ORDEN)
    df["_p"] = -df.puntaje_ia.fillna(-1)
    df = df.sort_values(["especialidad", "_a", "_c", "_p", "fecha_ingreso"])
    df["puesto_vista"] = df.groupby("especialidad").cumcount() + 1
    return df.drop(columns=["_a", "_c", "_p"]).reset_index(drop=True)


def revisar_pertinencia(prop: pd.DataFrame, datos, cfg: dict) -> dict[str, list[str]]:
    """Coherencia entre la IA y la regla: si la evidencia que cita la IA incluye un evento que la regla considera
    no relacionado con el motivo de derivación (p. ej. un cólico renal en un paciente de traumatología) y la IA NO
    lo declaró en `ignorado`, se marca para revisión. No cambia la propuesta; solo avisa.
    Devuelve id_paciente -> descripciones de esos eventos."""
    from motor.pertinencia import es_pertinente
    rutina = ("control", "control crónico", "control de rutina")
    out: dict[str, list[str]] = {}
    for f in prop.itertuples():
        p = datos.pacientes.get(f.id_paciente)
        if p is None or not isinstance(f.evidencia, str) or not f.evidencia:
            continue
        try:
            texto = " ".join(f"{e.get('fecha', '')} {e.get('cita', '')}" for e in json.loads(f.evidencia))
        except (ValueError, AttributeError):
            texto = f.evidencia
        ign = getattr(f, "ignorado", "")
        try:
            ign = " ".join(json.loads(ign)) if isinstance(ign, str) and ign else ""
        except ValueError:
            pass
        citados = []
        for e in p.eventos:
            if e["subtipo"] in rutina or es_pertinente(p, e, cfg):
                continue
            dx = e.get("diagnostico_cie10")
            def esta(t):
                return (isinstance(dx, str) and bool(dx) and dx in t) or str(e["fecha"]) in t
            if esta(texto) and not esta(ign):
                nombre = e.get("diagnostico_texto") if isinstance(e.get("diagnostico_texto"), str) else ""
                citados.append(f"{e['fecha']} {e['subtipo']} {dx or ''} {nombre}".strip())
        if citados:
            out[f.id_paciente] = citados
    return out


def descartados(prop: pd.DataFrame, datos, cfg: dict) -> dict:
    """Concordancia en pertinencia: de los eventos que la regla considera no relacionados, cuántos menciona la IA
    en `ignorado` (por fecha o código CIE-10)."""
    from motor.pertinencia import es_pertinente
    rutina = ("control", "control crónico", "control de rutina")
    total = vistos = 0
    for f in prop.itertuples():
        p = datos.pacientes.get(f.id_paciente)
        if p is None:
            continue
        try:
            ign = " ".join(json.loads(f.ignorado)) if isinstance(getattr(f, "ignorado", None), str) else ""
        except ValueError:
            ign = ""
        corte = f.corte if not isinstance(f.corte, str) else pd.Timestamp(f.corte).date()
        for e in p.eventos:
            if e["fecha"] > corte or e["subtipo"] in rutina or es_pertinente(p, e, cfg):
                continue
            total += 1
            dx = e.get("diagnostico_cie10")
            vistos += int((isinstance(dx, str) and bool(dx) and dx in ign) or str(e["fecha"]) in ign)
    return {"no_relacionados": total, "descartados_por_ia": vistos}
