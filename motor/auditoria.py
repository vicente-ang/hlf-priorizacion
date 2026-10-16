"""Auditoría de equidad de la lista priorizada.

Pregunta: ¿algún grupo queda sub-representado en los primeros puestos respecto de su peso en la lista?
Para cada grupo (comuna rural/urbana, nivel socioeconómico, previsión, sexo, edad) compara:
  - su proporción en la lista completa,
  - su proporción en el primer cuarto de cada especialidad (los que se citan pronto).
Índice de representación = proporción en el primer cuarto / proporción en la lista.
Se marca alerta si el índice queda bajo 0,8 (regla de los cuatro quintos, usada para detectar
impacto adverso) y el grupo tiene al menos 10 pacientes (con menos, es ruido).

Riesgo que vigila: medir necesidad por uso de servicios desfavorece a quien accede menos
(Obermeyer et al., Science 2019). También reporta qué grupos tienen más pacientes "sin señales
recientes", que la herramienta manda a verificar.
"""
from __future__ import annotations

import pandas as pd

from .puntaje import Datos

RURALES = {"Pirque", "San José de Maipo"}
UMBRAL_INDICE = 0.8
MINIMO_GRUPO = 10


def _atributos(datos: Datos, ids) -> pd.DataFrame:
    filas = []
    for i in ids:
        p = datos.pacientes[i]
        filas.append({"id_paciente": i,
                      "Comuna": "Rural (Pirque, San José de Maipo)" if p.comuna in RURALES else "Urbana",
                      "Nivel socioeconómico": p.nivel_socioeconomico,
                      "Previsión": p.prevision,
                      "Sexo": "Mujer" if p.sexo == "F" else "Hombre",
                      "Edad": "65 años o más" if p.edad >= 65 else "Menor de 65"})
    return pd.DataFrame(filas)


def auditar(lista: pd.DataFrame, datos: Datos, fraccion_top: float = 0.25) -> pd.DataFrame:
    """Tabla por dimensión y grupo. `lista` es la salida de motor.priorizar (con puesto y en_especialidad)."""
    if lista.empty:
        return pd.DataFrame()
    df = lista[["id_paciente", "puesto", "en_especialidad"]].merge(_atributos(datos, lista["id_paciente"]), on="id_paciente")
    df["primer_cuarto"] = df["puesto"] <= (df["en_especialidad"] * fraccion_top).clip(lower=1)
    if "verificar_estado" in lista:
        df = df.merge(lista[["id_paciente", "verificar_estado"]], on="id_paciente")
        df["sin_senales"] = df["verificar_estado"].notna()
    else:
        df["sin_senales"] = False
    n_total, n_top = len(df), int(df["primer_cuarto"].sum())
    filas = []
    for dim in ("Comuna", "Nivel socioeconómico", "Previsión", "Sexo", "Edad"):
        for grupo, g in df.groupby(dim):
            en_lista = len(g) / n_total
            en_top = g["primer_cuarto"].sum() / n_top if n_top else 0
            indice = en_top / en_lista if en_lista else None
            filas.append({"Dimensión": dim, "Grupo": grupo, "Pacientes": len(g),
                          "% de la lista": round(100 * en_lista, 1),
                          "% del primer cuarto": round(100 * en_top, 1),
                          "Índice de representación": round(indice, 2) if indice is not None else None,
                          "% sin señales recientes": round(100 * g["sin_senales"].mean(), 1),
                          "Alerta": bool(indice is not None and indice < UMBRAL_INDICE and len(g) >= MINIMO_GRUPO)})
    return pd.DataFrame(filas)
