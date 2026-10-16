"""Gráfico de la medición en TEST del agente, para el pitch: salidas/graficos/ia_test.png.

Lee ia/resultados/test_conteos_bedrock.csv (los mismos 118 pacientes de prueba para todos los métodos) y dibuja,
por método, cuántos deterioros detectó (de 23), cuántos "alta" dejó en baja (de 29) y las falsas alarmas (de 95).
Mismo estilo que sim/graficos.py (acento verde para la IA, gris de contexto; cada barra con su valor).

Uso:  python -m ia.grafico_test
"""
from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RAIZ = Path(__file__).resolve().parents[1]
ACENTO, CONTEXTO, ALERTA = "#0B8A73", "#A9B6BC", "#9A6212"
TINTA, TINTA_2, GRILLA = "#1E2A32", "#5B6B76", "#E3E8EB"
CSV = RAIZ / "ia" / "resultados" / "test_conteos_bedrock.csv"
SALIDA = RAIZ / "salidas" / "graficos" / "ia_test.png"
ETIQUETA = {"fifo": "Regla actual (FIFO)", "regla": "Regla MVP", "palabras_clave": "Palabras clave (sin LLM)",
            "ia": "IA (Bedrock)", "hibrido": "IA + piso de la regla"}

plt.rcParams.update({"font.size": 12, "axes.edgecolor": GRILLA, "axes.labelcolor": TINTA_2, "xtick.color": TINTA_2,
                     "ytick.color": TINTA, "axes.titlecolor": TINTA, "figure.facecolor": "white",
                     "axes.facecolor": "white", "savefig.facecolor": "white"})


def generar(csv: str | Path | None = None, salida: str | Path | None = None) -> Path:
    df = pd.read_csv(csv or CSV).set_index("metodo")
    orden = [m for m in ("fifo", "regla", "palabras_clave", "ia", "hibrido") if m in df.index]
    df = df.loc[orden]
    emp = int(df["empeoraron"].iloc[0])        # 23
    alta = int(df["debian_ser_alta"].iloc[0])  # 29
    paneles = [
        ("detectados", emp, f"Deterioros detectados\n(de {emp} que empeoraron)", "más es mejor", False),
        ("quedaron_en_baja", alta, f"«Alta» que quedaron en baja\n(de {alta}; subtriaje)", "menos es mejor", True),
        ("falsas_alarmas", int(df["no_empeoraron"].iloc[0]), "Falsas alarmas\n(subió sin empeorar)", "menos es mejor", True),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.2))
    fig.suptitle("Medición en TEST: 118 pacientes que el agente nunca vio (otra redacción de notas)",
                 fontsize=14, fontweight="bold", color=TINTA, y=1.02)
    etiquetas = [ETIQUETA.get(m, m) for m in orden]
    for ax, (col, tope, titulo, nota, menos_mejor) in zip(axes, paneles):
        vals = df[col].to_numpy()
        # la IA en acento; el resto en gris; si "menos es mejor", el mejor (mínimo) también en acento
        colores = []
        mejor = vals.min() if menos_mejor else vals.max()
        for m, v in zip(orden, vals):
            colores.append(ACENTO if (m in ("ia", "hibrido") or v == mejor) else CONTEXTO)
        barras = ax.bar(etiquetas, vals, color=colores, width=0.68)
        for b, v in zip(barras, vals):
            ax.text(b.get_x() + b.get_width() / 2, v + tope * 0.02, str(int(v)), ha="center", va="bottom",
                    fontsize=12, color=TINTA, fontweight="bold")
        ax.set_ylim(0, tope * 1.15)
        ax.set_title(f"{titulo}\n({nota})", fontsize=11.5, pad=10)
        for lado in ("top", "right", "left"):
            ax.spines[lado].set_visible(False)
        ax.grid(axis="y", color=GRILLA, linewidth=1)
        ax.set_axisbelow(True)
        ax.tick_params(axis="y", length=0)
        ax.tick_params(axis="x", length=0)
        ax.set_xticks(range(len(etiquetas)))
        ax.set_xticklabels(etiquetas, rotation=28, ha="right", fontsize=10)
    fig.tight_layout()
    destino = Path(salida) if salida else SALIDA
    destino.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(destino, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return destino


def main():
    destino = generar()
    print(f"gráfico de TEST -> {destino}")


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    main()
