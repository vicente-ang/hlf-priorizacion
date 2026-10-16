"""Simulación del uso de box: ¿qué política aprovecha mejor los cupos sin alargar las jornadas?

Repite cada bloque de la agenda (2.188 en el dataset del desafío) 300 veces con cinco políticas:
  A  Actual: se cita la capacidad del bloque.
  B  A + llamada 48 h antes a los citados con riesgo alto de no llegar (≥ 0,30).
  C  B + lista de reserva: cuando alguien avisa que no viene, se llama a la reserva.
  D  C + sobrecupo fijo de 2 por box (práctica habitual).
  E  C + sobrecupo con tope de sobretiempo (la regla de motor/agenda.py): solo donde cabe.

Calibración (con los datos del desafío):
  - Asistencia de cada especialidad = uso histórico de cupos de la agenda (74% en promedio), así la
    política A reproduce el uso real.
  - Lo que no se usa se reparte entre "no llega sin avisar" y "avisa" como en citaciones.csv (60 : 45).
  - Riesgo de cada paciente: del modelo de motor/agenda.py aplicado a la lista (historia + especialidad).
  - Duración de cada atención: muestreada de minutos_atencion_real de la especialidad.

Supuestos (decirlos si preguntan):
  - La llamada reduce a la mitad la inasistencia de los llamados: ensayo aleatorizado de Dunstan et al.
    (2023) en el Hospital Luis Calvo Mackenna, 21,0% → 10,7%.
  - La reserva logra llenar la mitad de los cupos que se liberan con aviso, y quien viene de la reserva
    asiste en el 90% de los casos. Son supuestos: medir en marcha blanca.
  - El sobretiempo se calcula con las duraciones de atención. En agenda_box.csv el sobretiempo registrado
    no se relaciona con los cupos usados (correlación 0,02), por eso no se usa para calibrar.

Uso:  python sim/agenda_sim.py      -> sim/resultados/agenda.md y agenda.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor.agenda import _ca, citas_que_caben, parametros_box, riesgo_no_llega  # noqa: E402
from motor.priorizacion import cargar_regla  # noqa: E402
from motor.puntaje import Datos  # noqa: E402

FIN = None   # fecha de referencia de los datos (se fija al correr)
EFECTO_LLAMADA = 10.7 / 21.0          # Dunstan et al. 2023
P_LLENAR_RESERVA = 0.5
P_ASISTE_RESERVA = 0.9
REPETICIONES = 300
POLITICAS = {
    "A": "Actual: citar la capacidad",
    "B": "+ llamada a riesgo alto",
    "C": "+ llamada + lista de reserva",
    "D": "+ llamada + reserva + sobrecupo fijo (+2)",
    "E": "+ llamada + reserva + sobrecupo con tope de sobretiempo",
}


def _riesgos_por_especialidad(datos, params, ca):
    """Riesgos de no llegar de los pacientes de cada especialidad, reescalados a la tasa calibrada."""
    out = {}
    for esp, pe in params.items():
        r = np.array([riesgo_no_llega(p, FIN, pe["p_no_llega"], ca["m"])[0]
                      for p in datos.pacientes.values() if p.especialidad == esp])
        if len(r) == 0:
            r = np.array([pe["p_no_llega"]])
        out[esp] = r * (pe["p_no_llega"] / r.mean())
    return out


def _bloque(rng, cap, extra, pe, riesgos, ca, llamada, reserva):
    n = cap + extra
    ns = rng.choice(riesgos, size=(REPETICIONES, n))
    if llamada:
        ns = np.where(ns >= ca["umbral_llamada"], ns * EFECTO_LLAMADA, ns)
    pav = pe["p_avisa"]
    pa = np.clip(1 - ns - pav, 0.0, 1.0)
    u = rng.random((REPETICIONES, n))
    asiste = u < pa
    avisa = (u >= pa) & (u < pa + pav)
    tiempos = rng.choice(pe["tiempos"], size=(REPETICIONES, n))
    total = (asiste * tiempos).sum(axis=1)
    vistos = asiste.sum(axis=1).astype(float)
    if reserva:
        relleno = (avisa & (rng.random((REPETICIONES, n)) < P_LLENAR_RESERVA * P_ASISTE_RESERVA))
        total = total + (relleno * rng.choice(pe["tiempos"], size=(REPETICIONES, n))).sum(axis=1)
        vistos = vistos + relleno.sum(axis=1)
    sobre = np.maximum(0.0, total - ca["duracion"])
    ocio = np.maximum(0.0, ca["duracion"] - total)
    return vistos, sobre, ocio


def correr(semilla=2026):
    global FIN
    datos, cfg = Datos.cargar(), cargar_regla()
    if datos.agenda is None or not len(datos.agenda):
        sys.exit("La simulación de box necesita agenda_box.csv en la carpeta de datos.")
    FIN = datos.fecha_referencia().isoformat()
    ca = _ca(cfg)
    params = parametros_box(datos, FIN, cfg)
    riesgos = _riesgos_por_especialidad(datos, params, ca)
    ag = datos.agenda
    rng = np.random.default_rng(semilla)
    caben = {(esp, cap): citas_que_caben(params[esp], ca, cap + ca["sobrecupo"]["max_por_box"])
             for esp, cap in ag[["especialidad", "capacidad_cupos"]].drop_duplicates().itertuples(index=False)}

    acum = {k: {"vistos": 0.0, "cupos": 0, "sobre": [], "ocio": [], "sobrecupos": 0} for k in POLITICAS}
    for b in ag.itertuples():
        pe, cap = params[b.especialidad], int(b.capacidad_cupos)
        extra_e = max(0, min(ca["sobrecupo"]["max_por_box"], caben[(b.especialidad, cap)] - cap))
        for k, (extra, llamada, reserva) in {"A": (0, False, False), "B": (0, True, False), "C": (0, True, True),
                                            "D": (2, True, True), "E": (extra_e, True, True)}.items():
            v, s, o = _bloque(rng, cap, extra, pe, riesgos[b.especialidad], ca, llamada, reserva)
            a = acum[k]
            a["vistos"] += v.mean()
            a["cupos"] += cap
            a["sobre"].append(s)
            a["ocio"].append(o)
            a["sobrecupos"] += extra

    filas = []
    for k, a in acum.items():
        sobre, ocio = np.concatenate(a["sobre"]), np.concatenate(a["ocio"])
        filas.append({"politica": k, "nombre": POLITICAS[k],
                      "atendidos_por_100_cupos": round(100 * a["vistos"] / a["cupos"], 1),
                      "sobretiempo_medio_min": round(float(sobre.mean()), 1),
                      "pct_bloques_sobretiempo_30": round(100 * float((sobre > 30).mean()), 1),
                      "minutos_ociosos_medio": round(float(ocio.mean()), 1),
                      "sobrecupos_por_100_cupos": round(100 * a["sobrecupos"] / a["cupos"], 1)})
    df = pd.DataFrame(filas)
    base = df.set_index("politica").loc["A", "atendidos_por_100_cupos"]
    df["atendidos_extra_6_meses"] = ((df.atendidos_por_100_cupos - base) / 100 * int(ag.capacidad_cupos.sum())).round()
    f_ini, f_fin = pd.to_datetime(ag.fecha).min(), pd.to_datetime(ag.fecha).max()
    df["bloques"] = len(ag)
    df["periodo"] = f"{f_ini.strftime('%d-%m-%Y')} al {f_fin.strftime('%d-%m-%Y')}"

    salida = RAIZ / "sim" / "resultados"
    salida.mkdir(parents=True, exist_ok=True)
    df.to_csv(salida / "agenda.csv", index=False)
    n_cupos = int(ag.capacidad_cupos.sum())
    md = ["# Uso del box: simulación de políticas de agenda\n",
          f"{len(ag):,} bloques del {df.periodo.iloc[0]} ({n_cupos:,} cupos), 300 repeticiones cada uno. "
          "Datos sintéticos; supuestos en sim/agenda_sim.py.\n".replace(",", "."),
          "| Política | Atendidos por 100 cupos | Atendidos extra en 6 meses | Sobretiempo medio por bloque | "
          "Bloques con > 30 min de sobretiempo | Minutos ociosos por bloque |",
          "|---|---|---|---|---|---|"]
    def num(x, dec=1):
        return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")

    for r in df.itertuples():
        extra = int(r.atendidos_extra_6_meses)
        md.append(f"| {r.politica}) {r.nombre} | {num(r.atendidos_por_100_cupos)} | "
                  f"{'+' if extra > 0 else ''}{num(extra, 0)} | {num(r.sobretiempo_medio_min)} min | "
                  f"{num(r.pct_bloques_sobretiempo_30)}% | {num(r.minutos_ociosos_medio, 0)} min |")
    sobre = {(esp, cap): c for (esp, cap), c in caben.items() if c < cap}
    md += ["", "Bloques sobreagendados para las duraciones reales de atención (caben menos citas que cupos):", ""]
    for (esp, cap), c in sorted(sobre.items()):
        md.append(f"- {esp}, bloques de {cap} cupos: caben {c} citas sin pasarse más de 30 min "
                  f"(atención media {params[esp]['minutos_media']:.0f} min, cupos de {ca['duracion'] / cap:.0f} min)")
    (salida / "agenda.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return df


if __name__ == "__main__":
    correr()
    print((RAIZ / "sim" / "resultados" / "agenda.md").read_text(encoding="utf-8"))
