"""Tablas para descargar y trabajar fuera de la herramienta (Excel, impresión, sistema de agenda).

CSV con punto y coma, coma decimal y BOM UTF-8: así Excel en español (Chile) lo abre bien con doble clic.
"""
from __future__ import annotations

import pandas as pd


def a_csv(df: pd.DataFrame) -> bytes:
    return df.to_csv(sep=";", decimal=",", index=False).encode("utf-8-sig")


def _fecha(x) -> str:
    return "" if x is None or (not isinstance(x, str) and pd.isna(x)) else pd.Timestamp(x).strftime("%d-%m-%Y")


def _txt(x) -> str:
    return "" if x is None or (not isinstance(x, (list, str)) and pd.isna(x)) else str(x)


def _avisos(r: dict) -> str:
    a = []
    if pd.notna(r.get("verificar_estado")):
        a.append(f"sin datos clínicos hace {int(r['dias_sin_datos'])} días" if pd.notna(r.get("dias_sin_datos"))
                 else "sin datos clínicos recientes")
    if pd.notna(r.get("alerta_contacto")):
        a.append(str(r["alerta_contacto"]))
    if r.get("indicacion_revisar"):
        a.append("revisar la indicación de control")
    return "; ".join(a)


def lista_para_exportar(lista: pd.DataFrame) -> pd.DataFrame:
    """Lista priorizada con el porqué de cada puesto, en columnas legibles."""
    filas = []
    for r in lista.sort_values(["especialidad", "puesto"]).to_dict("records"):
        filas.append({
            "Especialidad": r["especialidad"], "Puesto": r["puesto"], "Paciente": r["id_paciente"],
            "Prioridad médica": r["prioridad_inicial"],
            "Origen de la prioridad": _txt(r.get("prioridad_origen")),
            "Prioridad actual": _txt(r.get("prioridad_dinamica")),
            "Por qué cambió la prioridad": _txt(r.get("motivo_prioridad")),
            "Fecha de ingreso": _fecha(r["fecha_ingreso"]),
            "Días en lista": r["dias_espera"], "Por qué está aquí": str(r["motivo_puesto"]).capitalize(),
            "Índice LACE": "" if pd.isna(r.get("lace")) or r.get("lace") is None else int(r["lace"]),
            "Carril rápido": "sí" if r.get("carril_rapido") else "no",
            "Motivo del carril": _txt(r.get("motivo_carril")),
            "Plazo vigente (días)": r.get("plazo_dias"), "Fecha objetivo": _fecha(r.get("fecha_objetivo")),
            "De dónde sale el plazo": _txt(r.get("motivo_plazo")),
            "Días de atraso": max(0, int(r["dias_atraso"])) if pd.notna(r.get("dias_atraso")) else "",
            "Señales de deterioro": "; ".join(r.get("senales_deterioro") or []),
            "Avisos": _avisos(r),
            "Puesto con la regla actual": r.get("puesto_regla_actual"),
            "Fecha de la lista": _fecha(r.get("corte")), "Versión de la regla": r.get("version_regla"),
        })
    return pd.DataFrame(filas)


def agenda_para_exportar(prop: dict) -> pd.DataFrame:
    """Citas propuestas por box y lista de reserva, en una sola tabla."""
    filas = []
    citas, reserva = prop.get("citas", pd.DataFrame()), prop.get("reserva", pd.DataFrame())
    if citas is not None and len(citas):
        for c in citas.sort_values(["especialidad", "id_box", "orden"]).itertuples():
            filas.append({"Especialidad": c.especialidad, "Box": c.id_box, "Orden": c.orden,
                          "Tipo": "Sobrecupo" if c.rol == "sobrecupo" else "Cupo", "Paciente": c.id_paciente,
                          "Puesto en lista": c.puesto_lista, "Prioridad médica": c.prioridad_inicial,
                          "Por qué está en la lista": str(c.motivo_puesto).capitalize(),
                          "Riesgo de no llegar (%)": round(100 * c.riesgo_no_llega),
                          "Antes de la cita": "; ".join(c.acciones)})
    if reserva is not None and len(reserva):
        for r in reserva.sort_values(["especialidad", "orden"]).itertuples():
            filas.append({"Especialidad": r.especialidad, "Box": "", "Orden": r.orden, "Tipo": "Reserva",
                          "Paciente": r.id_paciente, "Puesto en lista": r.puesto_lista,
                          "Prioridad médica": r.prioridad_inicial,
                          "Por qué está en la lista": str(r.motivo_puesto).capitalize(),
                          "Riesgo de no llegar (%)": "", "Antes de la cita": "llamar si alguien avisa que no viene"})
    return pd.DataFrame(filas)


def llamadas_para_exportar(llamadas: pd.DataFrame) -> pd.DataFrame:
    if llamadas is None or llamadas.empty:
        return pd.DataFrame(columns=["Orden de llamada", "Grupo", "Cuándo", "Especialidad", "Paciente",
                                     "Puesto en lista", "Box", "Orden en el box", "Qué conversar", "Resultado"])
    return pd.DataFrame({
        "Orden de llamada": llamadas.orden_llamada, "Grupo": llamadas.grupo, "Cuándo": llamadas.cuando,
        "Especialidad": llamadas.especialidad, "Paciente": llamadas.id_paciente,
        "Puesto en lista": llamadas.puesto_lista, "Box": llamadas.id_box.fillna(""),
        "Orden en el box": llamadas.orden_cita.astype("string").fillna(""),
        "Qué conversar": llamadas.motivos.str[0].str.upper() + llamadas.motivos.str[1:],
        "Resultado": "",      # para anotar a mano: confirmó / no contesta / no necesita la hora / otro
    })
