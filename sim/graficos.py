"""Gráficos para el pitch (PNG, listos para pegar en las diapositivas).

Uso:  python sim/graficos.py      (requiere haber corrido sim/simulador.py y sim/robustez.py)
Escribe salidas/graficos/: impacto.png, robustez.png, equidad.png, agenda.png, cadencia.png

Color: acento verde petróleo para el MVP y gris de contexto para la regla actual (codificación de
realce, no categórica). Validado con el validador de paletas: diferencia perceptual 22 con visión
normal y 17,6 en daltonismo protan. El gris no llega a 3:1 de contraste, por eso cada barra lleva
su valor escrito.
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
sys.path.insert(0, str(RAIZ))
from motor import Datos, auditar, cargar_regla, priorizar  # noqa: E402

ACENTO, CONTEXTO, ALERTA = "#0B8A73", "#A9B6BC", "#9A6212"
TINTA, TINTA_2, GRILLA = "#1E2A32", "#5B6B76", "#E3E8EB"
SALIDA = RAIZ / "salidas" / "graficos"
RES = RAIZ / "sim" / "resultados"

plt.rcParams.update({"font.size": 13, "axes.edgecolor": GRILLA, "axes.labelcolor": TINTA_2, "xtick.color": TINTA_2,
                     "ytick.color": TINTA, "axes.titlecolor": TINTA, "figure.facecolor": "white",
                     "axes.facecolor": "white", "savefig.facecolor": "white"})


def _coma(x, dec=0):
    return f"{x:.{dec}f}".replace(".", ",")


def _ejes(ax):
    for lado in ("top", "right", "left"):
        ax.spines[lado].set_visible(False)
    ax.spines["bottom"].set_color(GRILLA)
    ax.grid(axis="x", color=GRILLA, linewidth=1)
    ax.set_axisbelow(True)
    ax.tick_params(axis="y", length=0)


def impacto(capacidad="25%"):
    m = pd.read_csv(RES / "metricas.csv")
    g = m[m.capacidad == capacidad].set_index("politica")
    paneles = [("pct_atendidos_<=30d_tras_evento", "Atendidos ≤ 30 días\ntras un evento grave", "%", "más es mejor"),
               ("mediana_dias_evento_a_atencion", "Días entre el evento grave\ny la atención (mediana)", " días", "menos es mejor"),
               ("eventos_graves_en_espera", "Eventos graves ocurridos\nestando en lista", "", "menos es mejor")]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.6))
    for ax, (col, titulo, unidad, sentido) in zip(axes, paneles):
        vals = [g.loc["actual", col], g.loc["carril_plazo", col]]
        y = [1, 0]
        ax.barh(y, vals, height=0.42, color=[CONTEXTO, ACENTO])
        tope = max(vals) * 1.32
        for yi, v in zip(y, vals):
            ax.text(v + tope * 0.02, yi, f"{_coma(v, 1 if v % 1 else 0)}{unidad}", va="center", color=TINTA,
                    fontsize=15, fontweight="bold")
        ax.set_yticks(y, ["Regla actual", "MVP"], fontsize=13)
        ax.set_xlim(0, tope)
        ax.set_xticks([])
        _ejes(ax)
        ax.grid(False)
        ax.set_title(titulo, loc="left", fontsize=14, fontweight="bold", pad=10)
        ax.text(0, -0.62, sentido, color=TINTA_2, fontsize=11, transform=ax.get_yaxis_transform())
    fig.suptitle("Con el MVP, quien empeora mientras espera se atiende en días, no en meses",
                 x=0.01, ha="left", fontsize=17, fontweight="bold", color=TINTA, y=1.07)
    periodo = m["periodo"].iloc[0] if "periodo" in m else ""
    cohorte = int(g.loc["actual", "cohorte_evento_grave"])
    fig.text(0.01, 0.975, f"Simulación del {periodo} con capacidad para atender al {capacidad} de la lista. "
             f"{cohorte} pacientes con un evento grave. Datos sintéticos del desafío.", color=TINTA_2, fontsize=11.5)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(SALIDA / "impacto.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def robustez():
    r = pd.read_csv(RES / "robustez.csv")
    col = "pct_atendidos_<=30d_tras_evento"
    fig, ax = plt.subplots(figsize=(12, 3.6))
    rng = np.random.default_rng(1)
    for yi, (modo, color, nombre) in enumerate([("carril_plazo", ACENTO, "MVP"), ("actual", CONTEXTO, "Regla actual")]):
        v = r[r.modo == modo][col].astype(float).values
        ax.scatter(v, yi + rng.uniform(-0.12, 0.12, len(v)), s=70, color=color, edgecolors="white", linewidths=2, zorder=3)
        med = np.median(v)
        ax.text(med, yi + 0.33, f"mediana {_coma(med, 0)}%", ha="center", color=TINTA, fontsize=12, fontweight="bold")
    ax.set_yticks([0, 1], ["MVP", "Regla actual"])
    ax.set_xlim(-3, 100)
    ax.set_ylim(-0.5, 1.6)
    ax.set_xlabel("% atendidos ≤ 30 días tras un evento grave (cada punto es una submuestra)")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: f"{x:.0f}%"))
    _ejes(ax)
    ax.set_title("En 30 submuestras distintas de pacientes, el MVP gana en todas", loc="left", fontsize=16,
                 fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(SALIDA / "robustez.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def equidad(corte=None):
    from motor.cortes import corte_vigente
    datos, cfg = Datos.cargar(), cargar_regla()
    corte = corte or corte_vigente(datos.fecha_referencia(), cfg)      # la lista vigente: la del último corte
    a = auditar(priorizar(datos, corte, cfg), datos)
    a = a[a.Pacientes >= 10].copy()
    a["etiqueta"] = a.Dimensión + ": " + a.Grupo.str.replace(" (Pirque, San José de Maipo)", "", regex=False)
    a = a.iloc[::-1]
    fig, ax = plt.subplots(figsize=(12, 6.5))
    colores = [ALERTA if v < 0.85 else ACENTO for v in a["Índice de representación"]]
    y = np.arange(len(a))
    ax.barh(y, a["Índice de representación"], height=0.55, color=colores)
    for yi, v in zip(y, a["Índice de representación"]):
        ax.text(v + 0.015, yi, _coma(v, 2) + ("  cerca del umbral" if v < 0.85 else ""), va="center", color=TINTA,
                fontsize=11)
    ax.axvline(1.0, color=TINTA_2, linewidth=1)
    ax.axvline(0.8, color=ALERTA, linewidth=1)
    ax.text(1.0, len(a) - 0.2, " paridad", color=TINTA_2, fontsize=11)
    ax.text(0.8, len(a) - 0.2, " alerta (0,8)", color=ALERTA, fontsize=11)
    ax.set_yticks(y, a.etiqueta, fontsize=11)
    ax.set_xlim(0, 1.55)
    ax.set_xlabel("Índice de representación en el primer cuarto de cada especialidad (1 = igual que en la lista)")
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda x, _: _coma(x, 1)))
    _ejes(ax)
    bajo = a[a["Índice de representación"] < 0.8]
    if len(bajo):
        titulo = (f"Auditoría de equidad del corte del {corte.strftime('%d-%m-%Y')}: "
                  + ", ".join(f"{g.lower()} en {_coma(v, 2)}" for g, v in zip(bajo.Grupo, bajo["Índice de representación"]))
                  + ", bajo el umbral de 0,8: la herramienta avisa para revisar")
    else:
        titulo = f"Auditoría de equidad del corte del {corte.strftime('%d-%m-%Y')}: ningún grupo bajo 0,8"
    ax.set_title(titulo, loc="left", fontsize=14, fontweight="bold", pad=12)
    fig.tight_layout()
    fig.savefig(SALIDA / "equidad.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def agenda():
    """Uso del box: atenciones por 100 cupos y jornadas que se alargan, por política."""
    a = pd.read_csv(RES / "agenda.csv").set_index("politica")
    nombres = {"A": "Actual", "C": "Llamar antes\n+ lista de reserva", "E": "Reserva + sobrecupo\ndonde cabe",
               "D": "Reserva + sobrecupo\nfijo de 2"}
    orden = ["A", "C", "E", "D"]
    colores = [CONTEXTO, ACENTO, ACENTO, ALERTA]
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.6))
    for ax, (col, titulo, unidad) in zip(axes, [
            ("atendidos_por_100_cupos", "Atenciones por cada 100 cupos", ""),
            ("pct_bloques_sobretiempo_30", "Jornadas que se pasan más de 30 minutos", "%")]):
        vals = [a.loc[k, col] for k in orden]
        y = np.arange(len(orden))[::-1]
        ax.barh(y, vals, height=0.5, color=colores)
        tope = max(vals) * 1.25
        for yi, v in zip(y, vals):
            ax.text(v + tope * 0.015, yi, f"{_coma(v, 1)}{unidad}", va="center", color=TINTA, fontsize=13,
                    fontweight="bold")
        ax.set_yticks(y, [nombres[k] for k in orden], fontsize=12)
        ax.set_xlim(0, tope)
        ax.set_xticks([])
        _ejes(ax)
        ax.grid(False)
        ax.set_title(titulo, loc="left", fontsize=14, fontweight="bold", pad=10)
    extra_c, extra_e = int(a.loc["C", "atendidos_extra_6_meses"]), int(a.loc["E", "atendidos_extra_6_meses"])
    miles = lambda n: f"{n:,}".replace(",", ".")  # noqa: E731
    fig.suptitle(f"Sin agregar boxes: entre {miles(extra_c)} y {miles(extra_e)} atenciones más en 6 meses, "
                 "con un aumento moderado del sobretiempo", x=0.01, ha="left", fontsize=16, fontweight="bold",
                 color=TINTA, y=1.07)
    bloques = f"{int(a['bloques'].iloc[0]):,}".replace(",", ".") if "bloques" in a else ""
    fig.text(0.01, 0.975, f"Simulación de los {bloques} bloques de box del {a['periodo'].iloc[0] if 'periodo' in a else ''}. "
             "El sobrecupo fijo atiende más, "
             "pero más de la mitad de las jornadas se alarga. Datos sintéticos; supuestos en sim/agenda_sim.py.",
             color=TINTA_2, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(SALIDA / "agenda.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


def cadencia():
    """Corte semanal vs recálculo diario (entrevista 6): estabilidad de la lista y reacción ante eventos graves."""
    c = pd.read_csv(RES / "cadencia.csv").set_index("cadencia")
    fig, axes = plt.subplots(1, 2, figsize=(14, 4.2))
    paneles = [
        ("pct_dias_orden_cambia_top20", "Días hábiles en que cambia el orden\nde los 20 primeros", "%",
         [("diaria", "Recalcular cada día", CONTEXTO), ("semanal_alertas", "Corte semanal + alertas", ACENTO)]),
        ("mediana_dias_evento_a_atencion", "Días entre un evento grave\ny la atención (mediana)", " días",
         [("actual", "Regla actual", CONTEXTO), ("diaria", "MVP, cada día", CONTEXTO),
          ("semanal_alertas", "MVP, corte semanal + alertas", ACENTO)])]
    for ax, (col, titulo, unidad, filas) in zip(axes, paneles):
        vals = [float(c.loc[k, col]) for k, _, _ in filas]
        y = np.arange(len(filas))[::-1]
        ax.barh(y, vals, height=0.5, color=[col_ for _, _, col_ in filas])
        tope = max(vals) * 1.3
        for yi, v in zip(y, vals):
            ax.text(v + tope * 0.015, yi, f"{_coma(v, 1 if v % 1 else 0)}{unidad}", va="center", color=TINTA,
                    fontsize=14, fontweight="bold")
        ax.set_yticks(y, [n for _, n, _ in filas], fontsize=12)
        ax.set_xlim(0, tope)
        ax.set_xticks([])
        _ejes(ax)
        ax.grid(False)
        ax.set_title(titulo, loc="left", fontsize=14, fontweight="bold", pad=10)
    fig.suptitle("Repriorizar los lunes: la lista que se agenda queda quieta la semana y la reacción casi no cambia",
                 x=0.01, ha="left", fontsize=16, fontweight="bold", color=TINTA, y=1.07)
    fig.text(0.01, 0.975, "Misma regla MVP. Los eventos graves que llegan entre cortes se avisan al día siguiente y el "
             "equipo los adelanta con un motivo. Datos sintéticos; detalle en sim/resultados/cadencia.md.",
             color=TINTA_2, fontsize=11)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.savefig(SALIDA / "cadencia.png", dpi=200, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    SALIDA.mkdir(parents=True, exist_ok=True)
    if (RES / "cadencia.csv").exists():
        cadencia()
    impacto()
    robustez()
    equidad()
    if (RES / "agenda.csv").exists():
        agenda()
    print(f"Gráficos en {SALIDA}: impacto.png, robustez.png, equidad.png, agenda.png, cadencia.png")
