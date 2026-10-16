"""Métricas contra la verdad conocida del mundo sintético. Compara métodos con los mismos pacientes
(los que evaluó el agente).

Métodos:
  fifo        regla actual del hospital: categoría T1 y, dentro de ella, orden de llegada
  regla       regla MVP (carril rápido + plazo dinámico), sin cupo por antigüedad para medir solo el riesgo
  ia          agente clínico: su categoría y su puntaje
  hibrido     agente + piso de seguridad de la regla, sin bajar de T1 sin una persona (lo que usaría el hospital)

Métricas (todas por especialidad y luego promedio, o sobre todos los pacientes):
  kappa              κ de Cohen ponderado (lineal) entre la categoría propuesta y la ideal
  sens_deterioro     de los que EMPEORARON (categoría ideal > T1), % que el método subió de categoría
  falsas_alarmas     de los que NO empeoraron, % que el método subió
  subtriage_alta     de los que deberían ser alta, % que quedaron en baja
  ndcg10             calidad de los 10 primeros puestos (ganancia = riesgo real a 90 días)
  kendall            τ de Kendall entre el orden propuesto y el riesgo real
  recall_top10       de los 10% de mayor riesgo real, % que quedó en el 10% superior propuesto
  objetivo           promedio de sens_deterioro, ndcg10 y kappa (lo que el ciclo regulador intenta subir)
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor import Datos, cargar_regla, priorizar  # noqa: E402

ORDEN = {"alta": 0, "media": 1, "baja": 2}


def kappa_ponderado(a, b) -> float:
    from validar_concordancia import kappa_ponderado as k
    return k(list(a), list(b))


def _ndcg(ganancias_en_orden: list[float], ideales: list[float], k: int = 10) -> float:
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(ganancias_en_orden[:k]))
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(sorted(ideales, reverse=True)[:k]))
    return dcg / idcg if idcg else 0.0


def propuestas_base(carpeta: str | Path) -> dict[str, pd.DataFrame]:
    """FIFO y regla MVP sobre los mismos datos (columnas: id_paciente, especialidad, categoria, puesto)."""
    datos, cfg = Datos.cargar(carpeta), cargar_regla()
    corte = datos.fecha_referencia()
    sin_cupo = {**cfg, "agenda": {**cfg["agenda"], "cupo_antiguedad": 0}}
    actual = priorizar(datos, corte, sin_cupo, modo="actual")
    mvp = priorizar(datos, corte, sin_cupo, modo="carril_plazo")
    return {"fifo": actual.assign(categoria=actual.prioridad_inicial)[["id_paciente", "especialidad", "categoria", "puesto"]],
            "regla": mvp.assign(categoria=mvp.prioridad_dinamica)[["id_paciente", "especialidad", "categoria", "puesto"]]}


def desde_agente(df: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"ia": df.assign(categoria=df.categoria_ia, puesto=df.puesto_ia)[["id_paciente", "especialidad", "categoria", "puesto"]],
            "hibrido": df.assign(categoria=df.categoria_final, puesto=df.puesto_final)[["id_paciente", "especialidad", "categoria", "puesto"]]}


def metricas(prop: pd.DataFrame, verdad: pd.DataFrame) -> dict:
    m = prop.merge(verdad[["id_paciente", "riesgo_90d", "categoria_ideal", "prioridad_inicial", "empeoro"]],
                   on="id_paciente").dropna(subset=["riesgo_90d", "categoria"])
    if m.empty:
        return {}
    sube = m.categoria.map(ORDEN) < m.prioridad_inicial.map(ORDEN)
    emp = m.empeoro.astype(bool)
    nd, kt, rc = [], [], []
    for _, g in m.groupby("especialidad"):
        g = g.sort_values("puesto")
        nd.append(_ndcg(list(g.riesgo_90d), list(g.riesgo_90d)))
        if len(g) > 2:
            kt.append(pd.Series(-g.puesto.values).corr(pd.Series(g.riesgo_90d.values), method="kendall"))
        k = max(1, round(.1 * len(g)))
        top_real = set(g.nlargest(k, "riesgo_90d").id_paciente)
        rc.append(len(top_real & set(g.head(k).id_paciente)) / k)
    r = {"n": len(m), "kappa": kappa_ponderado(m.categoria, m.categoria_ideal),
         "sens_deterioro": float(sube[emp].mean()) if emp.any() else float("nan"),
         "falsas_alarmas": float(sube[~emp].mean()) if (~emp).any() else float("nan"),
         "subtriage_alta": float((m[m.categoria_ideal == "alta"].categoria == "baja").mean())
         if (m.categoria_ideal == "alta").any() else float("nan"),
         "ndcg10": sum(nd) / len(nd), "kendall": sum(kt) / len(kt) if kt else float("nan"),
         "recall_top10": sum(rc) / len(rc)}
    r["objetivo"] = (r["sens_deterioro"] + r["ndcg10"] + r["kappa"]) / 3
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in r.items()}


def comparar(carpeta: str | Path, agente_df: pd.DataFrame | None = None,
             otros: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Tabla de métricas por método. Si hay propuestas del agente, TODOS los métodos se miden sobre los mismos
    pacientes que evaluó el agente (con --muestra son menos que la lista: el NDCG y el τ de una lista de 118 no se
    comparan con los de una de 296). El orden de FIFO y de la regla se conserva dentro de ese subconjunto.
    `otros`: más corridas del agente para comparar (p. ej. {"palabras_clave": propuestas en modo simulado})."""
    carpeta = Path(carpeta)
    verdad = pd.read_csv(carpeta.parent / f"{carpeta.name}_verdad" / "verdad.csv")
    metodos = propuestas_base(carpeta)
    for nombre, df in (otros or {}).items():
        metodos[nombre] = desde_agente(df)["ia"]
    if agente_df is not None:
        metodos.update(desde_agente(agente_df))
        ids = set(agente_df.id_paciente)
        metodos = {k: v[v.id_paciente.isin(ids)] for k, v in metodos.items()}
    return pd.DataFrame([{"metodo": k, **metricas(v, verdad)} for k, v in metodos.items()])


def conteos(carpeta: str | Path, agente_df: pd.DataFrame, otros: dict[str, pd.DataFrame] | None = None) -> pd.DataFrame:
    """Lo mismo que `comparar` pero en números absolutos (para el pitch: «22 de 23», no solo «96 %»)."""
    carpeta = Path(carpeta)
    verdad = pd.read_csv(carpeta.parent / f"{carpeta.name}_verdad" / "verdad.csv")
    metodos = {**propuestas_base(carpeta), **{k: desde_agente(v)["ia"] for k, v in (otros or {}).items()},
               **desde_agente(agente_df)}
    ids = set(agente_df.id_paciente)
    filas = []
    for k, v in metodos.items():
        m = v[v.id_paciente.isin(ids)].merge(verdad[["id_paciente", "categoria_ideal", "prioridad_inicial", "empeoro"]],
                                             on="id_paciente").dropna(subset=["categoria"])
        sube = m.categoria.map(ORDEN) < m.prioridad_inicial.map(ORDEN)
        emp = m.empeoro.astype(bool)
        alta = m.categoria_ideal == "alta"
        filas.append({"metodo": k, "n": len(m), "empeoraron": int(emp.sum()), "detectados": int(sube[emp].sum()),
                      "no_empeoraron": int((~emp).sum()), "falsas_alarmas": int(sube[~emp].sum()),
                      "debian_ser_alta": int(alta.sum()), "quedaron_en_baja": int((m[alta].categoria == "baja").sum())})
    return pd.DataFrame(filas)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos", default=str(RAIZ / "data" / "mundo" / "dev"))
    ap.add_argument("--propuestas", help="CSV del agente (ia.agente) para incluir ia e híbrido")
    a = ap.parse_args()
    ag = pd.read_csv(a.propuestas) if a.propuestas else None
    print(comparar(a.datos, ag).to_string(index=False))
    if ag is not None:
        print("\nEn números absolutos (mismos pacientes):")
        print(conteos(a.datos, ag).to_string(index=False))
