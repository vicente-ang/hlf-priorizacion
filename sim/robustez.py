"""¿Las cifras del MVP son robustas o dependen de unos pocos pacientes?

Repite la simulación (capacidad 25%) en 30 submuestras aleatorias del 80% de los pacientes y
compara la regla actual con el MVP en cada una. Si el MVP gana en casi todas, la ventaja no es
un accidente de la muestra. Con 500 pacientes sintéticos esto no reemplaza datos reales, pero
responde la pregunta típica del jurado: "¿y si cambia la muestra?".

Uso:  python sim/robustez.py [--n 30] [--fraccion 0.8]   -> sim/resultados/robustez.md
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor.priorizacion import cargar_regla  # noqa: E402
from motor.puntaje import Datos, _a_fecha  # noqa: E402
from sim.simulador import capacidad_escalada, metricas, periodo, simular  # noqa: E402

METRICAS = [  # (columna, nombre, mayor_es_mejor)
    ("pct_atendidos_<=30d_tras_evento", "% atendidos ≤30 d tras evento grave", True),
    ("mediana_dias_evento_a_atencion", "Mediana días evento → atención", False),
    ("eventos_graves_en_espera", "Eventos graves en lista", False),
    ("siguen_esperando_>365d", "Siguen esperando > 365 d", False),
    ("pct_atendido_nse_bajo", "% atendido NSE bajo", True),
    ("pct_atendido_rural", "% atendido rural", True),
]


def correr(n=30, fraccion=0.8, capacidad=0.25, semilla=2026):
    base, cfg = Datos.cargar(), cargar_regla()
    ini, fin = periodo(base)
    rng = random.Random(semilla)
    ids = sorted(base.pacientes)
    filas = []
    for i in range(n):
        sub = rng.sample(ids, int(len(ids) * fraccion))
        datos = Datos({k: base.pacientes[k] for k in sub}, base.agenda)
        cap = capacidad_escalada(datos, capacidad, ini, fin)
        for modo in ("actual", "carril_plazo"):
            m = metricas(datos, simular(datos, cfg, modo, cap)[0], ini, fin)
            filas.append({"muestra": i, "modo": modo, **{c: m[c] for c, _, _ in METRICAS}})
    df = pd.DataFrame(filas)

    md = [f"# Robustez: {n} submuestras del {int(fraccion * 100)}% de los pacientes (capacidad {int(capacidad * 100)}%)\n",
          "Mediana y rango del 5% al 95% entre submuestras. Última columna: en cuántas submuestras el MVP "
          "queda mejor (o igual) que la regla actual.\n",
          "| Métrica | Regla actual | MVP | MVP mejor o igual |", "|---|---|---|---|"]
    for col, nombre, mayor in METRICAS:
        a = df[df.modo == "actual"].set_index("muestra")[col].astype(float)
        b = df[df.modo == "carril_plazo"].set_index("muestra")[col].astype(float)
        mejor = int(((b >= a) if mayor else (b <= a)).sum())

        def r(s):
            return f"{np.median(s):.1f} ({np.percentile(s, 5):.1f}–{np.percentile(s, 95):.1f})".replace(".", ",")
        md.append(f"| {nombre} | {r(a)} | {r(b)} | {mejor} de {n} |")
    salida = RAIZ / "sim" / "resultados"
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "robustez.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    df.to_csv(salida / "robustez.csv", index=False)
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--fraccion", type=float, default=0.8)
    a = ap.parse_args()
    correr(a.n, a.fraccion)
    print((RAIZ / "sim" / "resultados" / "robustez.md").read_text(encoding="utf-8"))
