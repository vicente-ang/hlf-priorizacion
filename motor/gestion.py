"""Vista de gestión de la lista: percentiles de espera y grupos para estrategias focalizadas (reunión 7).

Cómo trabaja hoy la gestión del hospital: descarga la lista, mira los percentiles más extremos (el P90, personas
que esperan más de ~200 días) y busca si están agrupados por un diagnóstico: "sabemos que es hipoacusia en
otorrino, entonces hacemos una estrategia focalizada: una licitación o un día completo de atenciones". Hoy eso es
manual. Este módulo lo deja hecho sobre la lista vigente:

  percentiles(lista)           por especialidad: personas, mediana (P50) y P90 de días de espera, cuántos superan
                               el P90 y cuántos están en carril rápido o con prioridad alta hoy.
  grupo_extremo(lista, esp)    quienes superan el umbral (P90 de la especialidad o un número de días), agrupados
                               por diagnóstico, con su perfil de riesgo (prioridad de hoy, señales, sin datos).
  sugerencias(...)             frases para el gestor: qué diagnóstico concentra el grupo extremo y si conviene una
                               estrategia focalizada.
"""
from __future__ import annotations

import pandas as pd

CONCENTRACION = 0.30   # un diagnóstico que reúne al menos el 30% del grupo extremo...
SOBRERREPRESENTACION = 1.2   # ...y pesa en él al menos 1,2 veces lo que pesa en toda la lista se sugiere como foco


def percentiles(lista: pd.DataFrame) -> pd.DataFrame:
    if lista is None or lista.empty:
        return pd.DataFrame()
    filas = []
    for esp, g in lista.groupby("especialidad"):
        p50, p90 = g.dias_espera.quantile(0.5), g.dias_espera.quantile(0.9)
        filas.append({"Especialidad": esp, "Personas": len(g), "Mediana de espera (días)": int(round(p50)),
                      "P90 de espera (días)": int(round(p90)), "Sobre el P90": int((g.dias_espera > p90).sum()),
                      "Más de 365 días": int((g.dias_espera > 365).sum()),
                      "Prioridad alta hoy": int((g.prioridad_dinamica == "alta").sum()),
                      "Carril rápido": int(g.carril_rapido.sum())})
    return pd.DataFrame(filas).sort_values("P90 de espera (días)", ascending=False).reset_index(drop=True)


def grupo_extremo(lista: pd.DataFrame, especialidad: str, umbral_dias: int | None = None,
                  diagnosticos: dict | None = None) -> tuple[pd.DataFrame, int]:
    """Quienes esperan más que el umbral (por defecto el P90 de la especialidad), agrupados por diagnóstico.
    `diagnosticos` = {id_paciente: "CIE-10 texto"}. Devuelve (tabla, umbral usado)."""
    g = lista[lista.especialidad == especialidad]
    if g.empty:
        return pd.DataFrame(), 0
    umbral = int(umbral_dias if umbral_dias is not None else round(g.dias_espera.quantile(0.9)))
    ext = g[g.dias_espera > umbral].copy()
    if ext.empty:
        return pd.DataFrame(), umbral
    ext["diagnostico"] = ext.id_paciente.map(diagnosticos or {}).fillna("sin diagnóstico")
    en_lista = g.id_paciente.map(diagnosticos or {}).fillna("sin diagnóstico").value_counts(normalize=True)
    filas = []
    for dx, d in ext.groupby("diagnostico"):
        filas.append({"Diagnóstico": dx, "Personas": len(d), "% del grupo": round(100 * len(d) / len(ext)),
                      "% en toda la lista": round(100 * en_lista.get(dx, 0)),
                      "Mediana de espera (días)": int(d.dias_espera.median()),
                      "Prioridad alta hoy": int((d.prioridad_dinamica == "alta").sum()),
                      "Con señales de deterioro": int(d.senales_deterioro.map(len).gt(0).sum()),
                      "Sin datos recientes": int(d.verificar_estado.notna().sum())})
    tabla = pd.DataFrame(filas).sort_values(["Personas", "Mediana de espera (días)"], ascending=False)
    return tabla.reset_index(drop=True), umbral


def sugerencias(tabla: pd.DataFrame, especialidad: str, umbral: int) -> list[str]:
    if tabla is None or tabla.empty:
        return [f"En {especialidad} nadie espera más de {umbral} días."]
    total = int(tabla.Personas.sum())
    out = [f"En {especialidad}, {total} personas esperan más de {umbral} días."]
    foco = tabla[(tabla["% del grupo"] >= 100 * CONCENTRACION)
                 & (tabla["% del grupo"] >= SOBRERREPRESENTACION * tabla["% en toda la lista"])]
    for r in foco.itertuples(index=False):
        out.append(f"{r[0]} reúne {r[1]} de ellas ({r[2]}%, frente al {r[3]}% de toda la lista), con una mediana de "
                   f"{r[4]} días: candidato a una estrategia focalizada (operativo, día de atención o compra de "
                   "prestaciones para ese diagnóstico).")
    alta = int(tabla["Prioridad alta hoy"].sum())
    if alta:
        out.append(f"{alta} {'tiene' if alta == 1 else 'tienen'} prioridad alta hoy: revisar que no estén esperando "
                   "por falta de cupo.")
    sin = int(tabla["Sin datos recientes"].sum())
    if sin:
        out.append(f"{sin} {'no tiene' if sin == 1 else 'no tienen'} datos en 180 días: llamar antes de programar "
                   "(pueden ya no necesitar la hora).")
    if foco.empty:
        out.append("Ningún diagnóstico está sobrerrepresentado en el grupo: se parece al resto de la lista, así que "
                   "conviene más oferta general o más cupo por antigüedad que una estrategia por diagnóstico.")
    return out
