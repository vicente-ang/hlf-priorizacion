"""Simulación contrafactual: ¿qué habría pasado en el período de la agenda (abril–octubre 2026 en el dataset
del desafío) si los cupos
se hubieran asignado con cada regla de priorización?

Usa EXACTAMENTE el mismo código de ordenamiento que la lista, la demo y la Lambda
(motor.priorizacion.evaluar_paciente + clave_orden).

Cómo funciona
-------------
1. Capacidad: se usan los días de agenda de cada especialidad (agenda_box.csv), pero los
   cupos se ESCALAN a la muestra. Los boxes reales atienden a toda la población (~21.900
   cupos en 6 meses) y el dataset trae solo 500 pacientes: sin escalar no habría escasez
   y todas las reglas darían lo mismo. Por defecto, cada especialidad puede atender en el
   período al 25% de sus pacientes; se prueba también 15% y 40%.
2. Cada día con agenda, cada regla elige a quién citar entre quienes están esperando ese
   día, usando SOLO información con fecha <= ese día.
3. Se comparan: rapidez para atender a quien tuvo un evento grave, eventos graves ocurridos
   estando en lista, esperas extremas y equidad.

Reglas comparadas
-----------------
- actual        : alta -> media -> baja, el más antiguo primero (regla del hospital)
- carril        : regla actual + carril rápido (evento grave en los últimos 30 días)
- carril_plazo  : MVP por defecto: carril rápido + resto por razón de atraso de su plazo,
                  con 1 de cada 10 cupos para el que más espera (agenda.cupo_antiguedad)
- puntaje       : puntaje v1 con pesos a mano (modo opcional, requiere calibración)

Supuestos (decirlos en el pitch)
--------------------------------
- Los eventos clínicos son los registrados: se asume que atender antes NO los habría evitado.
  Es conservador: en la realidad, atender a tiempo previene parte de ellos.
- Todos los citados asisten (la inasistencia se trabaja aparte con la alerta de contacto).
- En la comparación principal TODAS las reglas excluyen a los fallecidos. Aparte se mide
  cuántos cupos perdería la regla actual si no detecta defunciones (como encontró el BID).
- El % atendido a ≤30 días tras un evento grave es en parte la definición del carril rápido:
  mide el cumplimiento del KPI de reacción, no un beneficio clínico demostrado.

Uso:  python sim/simulador.py            (escribe sim/resultados/)
"""
from __future__ import annotations

import argparse
import copy
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import median

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor.priorizacion import cargar_regla, clave_orden, es_turno_antiguedad, evaluar_paciente  # noqa: E402
from motor.puntaje import Datos, _a_fecha  # noqa: E402

INICIO, FIN = None, None          # por defecto: desde el primer bloque de agenda hasta la fecha más reciente


def periodo(datos: Datos, inicio=None, fin=None):
    """Período a simular: el de la agenda de boxes, hasta la fecha de referencia de los datos."""
    if datos.agenda is None or not len(datos.agenda):
        sys.exit("La simulación necesita agenda_box.csv (bloques de box con su capacidad) en la carpeta de datos.")
    ini = _a_fecha(inicio) if inicio else _a_fecha(datos.agenda["fecha"].min())
    fn = _a_fecha(fin) if fin else datos.fecha_referencia()
    return ini, fn
POLITICAS = ["actual", "carril", "carril_plazo", "puntaje"]
NOMBRES = {
    "actual": "Regla actual",
    "carril": "Actual + carril rápido",
    "carril_plazo": "MVP: carril rápido + plazo dinámico + 10% por antigüedad",
    "puntaje": "Puntaje v1 (pesos a mano)",
}
RURALES = {"Pirque", "San José de Maipo"}


# ----------------------------------------------------------------------------
def capacidad_escalada(datos: Datos, fraccion: float, inicio: date, fin: date) -> dict:
    """{fecha: {especialidad: cupos}} con los días de agenda reales y cupos escalados."""
    ag = datos.agenda.copy()
    ag["fecha"] = pd.to_datetime(ag["fecha"]).dt.date
    ag = ag[(ag["fecha"] >= inicio) & (ag["fecha"] <= fin)]
    cap: dict = defaultdict(dict)
    for esp, g in ag.groupby("especialidad"):
        n = sum(1 for p in datos.pacientes.values()
                if p.especialidad == esp and p.fecha_ingreso <= fin
                and not (p.fecha_defuncion and p.fecha_defuncion < inicio))
        total = round(fraccion * n)
        dia = g.groupby("fecha")["capacidad_cupos"].sum().sort_index()
        peso_total, acum, previo = dia.sum(), 0, 0
        for f, w in dia.items():
            acum += w
            asignado = int(total * acum // peso_total)
            if asignado - previo > 0:
                cap[f][esp] = asignado - previo
            previo = asignado
    return dict(cap)


def simular(datos: Datos, cfg: dict, modo: str, cap: dict, excluir_fallecidos: bool = True,
            cupo_antiguedad: float | None = None, cadencia: str = "diaria", ordenes: dict | None = None):
    """Asigna los cupos día a día con la regla `modo`. `cupo_antiguedad` reserva esa fracción
    de los cupos (repartida de forma pareja) para quien lleva más tiempo esperando. Por defecto
    usa el de regla.yaml en el modo MVP (como la lista) y 0 en los demás.

    `cadencia` (entrevista 6):
      diaria           la lista se recalcula cada día con todo lo que se sabe hasta ese día
      semanal          la lista se reprioriza el día de corte (lunes) y se usa igual toda la semana; quien
                       ingresa después del corte entra en el siguiente
      semanal_alertas  semanal, pero quien tuvo un evento grave después del corte aparece en el reporte del día
                       siguiente y el equipo lo adelanta (alerta + adelanto manual)
    `ordenes`, si se pasa un dict, guarda el orden de cada especialidad cada día (para medir estabilidad)."""
    from motor.cortes import corte_vigente
    if cupo_antiguedad is None:
        cupo_antiguedad = cfg.get("agenda", {}).get("cupo_antiguedad", 0.0) if modo == "carril_plazo" else 0.0
    por_esp = defaultdict(list)
    for p in datos.pacientes.values():
        por_esp[p.especialidad].append(p)
    atendido: dict[str, date] = {}
    cupos_a_fallecidos = 0
    usados = defaultdict(int)
    foto: dict = {}
    for d in sorted(cap):
        for esp, k in cap[d].items():
            cand = [p for p in por_esp[esp] if p.fecha_ingreso <= d and p.id_paciente not in atendido]
            if excluir_fallecidos:
                cand = [p for p in cand if not (p.fecha_defuncion and p.fecha_defuncion <= d)]
            if cadencia == "diaria":
                evals = {p.id_paciente: evaluar_paciente(p, d, cfg, modo) for p in cand}
                por_regla = sorted(cand, key=lambda p: clave_orden(evals[p.id_paciente], modo))
            else:
                c = corte_vigente(d, cfg)
                if (esp, c) not in foto:
                    en_c = [p for p in por_esp[esp] if p.fecha_ingreso <= c and p.id_paciente not in atendido
                            and not (p.fecha_defuncion and p.fecha_defuncion <= c)]
                    ev_c = {p.id_paciente: evaluar_paciente(p, c, cfg, modo) for p in en_c}
                    foto[(esp, c)] = sorted(en_c, key=lambda p: clave_orden(ev_c[p.id_paciente], modo))
                vivos = {p.id_paciente for p in cand}
                por_regla = [p for p in foto[(esp, c)] if p.id_paciente in vivos]
                if cadencia == "semanal_alertas":
                    ayer = date.fromordinal(d.toordinal() - 1)
                    alerta = [p for p in cand if any(e["severidad"] == "grave" and c < e["fecha"] <= ayer
                                                     and _pertinente(p, e) for e in p.eventos)]
                    if alerta:
                        ev_a = {p.id_paciente: evaluar_paciente(p, d, cfg, modo) for p in alerta}
                        alerta = sorted(alerta, key=lambda p: clave_orden(ev_a[p.id_paciente], modo))
                        ids_a = {p.id_paciente for p in alerta}
                        por_regla = alerta + [p for p in por_regla if p.id_paciente not in ids_a]
            if ordenes is not None:
                ordenes[(esp, d)] = [p.id_paciente for p in por_regla]
            por_antiguedad = sorted(cand, key=lambda p: p.fecha_ingreso)
            for _ in range(k):
                t = usados[esp]
                es_antiguedad = es_turno_antiguedad(t, cupo_antiguedad)
                fila = por_antiguedad if es_antiguedad else por_regla
                elegido = next((p for p in fila if p.id_paciente not in atendido), None)
                if elegido is None:
                    break
                usados[esp] += 1
                atendido[elegido.id_paciente] = d
                if elegido.fecha_defuncion and elegido.fecha_defuncion <= d:
                    cupos_a_fallecidos += 1
    return atendido, cupos_a_fallecidos


def dias_con_cambios(ordenes: dict, top: int = 20) -> float:
    """Estabilidad: % de días de agenda en que el orden de los `top` primeros cambia respecto del día de agenda
    anterior (alguien es pasado por otro que estaba detrás; no cuenta que salgan los ya atendidos)."""
    por_esp = defaultdict(list)
    for (esp, d), orden in ordenes.items():
        por_esp[esp].append((d, orden))
    con_cambio = total = 0
    for serie in por_esp.values():
        serie.sort()
        for (_, a), (_, b) in zip(serie, serie[1:]):
            pos_b = {pid: i for i, pid in enumerate(b)}
            comunes = [pid for pid in a[:top] if pid in pos_b]
            nuevos_arriba = [pid for pid in b[:top] if pid not in set(a)]
            inv = any(pos_b[comunes[i]] > pos_b[comunes[j]] for i in range(len(comunes))
                      for j in range(i + 1, len(comunes)))
            total += 1
            con_cambio += bool(inv or nuevos_arriba)
    return round(100 * con_cambio / total, 1) if total else 0.0


# ----------------------------------------------------------------------------
_CFG = None


def _pertinente(p, e):
    """Solo cuentan los eventos relacionados con la derivación (reunión 7), igual que en la regla."""
    global _CFG
    if _CFG is None:
        _CFG = cargar_regla()
    from motor.pertinencia import es_pertinente
    return es_pertinente(p, e, _CFG)


def _primer_grave(p, inicio, fin):
    for e in p.eventos:
        if (e["severidad"] == "grave" and inicio <= e["fecha"] <= fin and e["fecha"] >= p.fecha_ingreso
                and _pertinente(p, e)):
            return e["fecha"]
    return None


def metricas(datos: Datos, atendido: dict, inicio: date, fin: date) -> dict:
    pac = datos.pacientes.values()
    m: dict = {"atendidos": len(atendido)}
    for pr in ("alta", "media", "baja"):
        grupo = [p for p in pac if p.prioridad_inicial == pr and p.fecha_ingreso <= fin]
        at = [p for p in grupo if p.id_paciente in atendido]
        m[f"atendidos_{pr}"] = len(at)
        m[f"espera_mediana_al_atender_{pr}"] = (median((atendido[p.id_paciente] - p.fecha_ingreso).days for p in at)
                                               if at else None)

    # 1) Eventos graves ocurridos mientras el paciente seguía esperando
    n = 0
    for p in pac:
        t = atendido.get(p.id_paciente)
        for e in p.eventos:
            if (e["severidad"] == "grave" and inicio <= e["fecha"] <= fin and e["fecha"] >= p.fecha_ingreso
                    and (t is None or e["fecha"] < t) and _pertinente(p, e)):
                n += 1
    m["eventos_graves_en_espera"] = n

    # 2) Reacción ante el primer evento grave (cohorte fija, igual para todas las reglas)
    cohorte = [(p, _primer_grave(p, inicio, fin)) for p in pac]
    cohorte = [(p, e) for p, e in cohorte if e is not None]
    antes = d30 = d90 = 0
    esperas_tras_evento = []
    for p, e in cohorte:
        t = atendido.get(p.id_paciente)
        if t is not None and t < e:
            antes += 1
            continue
        fin_obs = p.fecha_defuncion if p.fecha_defuncion and p.fecha_defuncion < fin else fin
        dias = (t - e).days if t is not None else (fin_obs - e).days   # censurado si no fue atendido
        esperas_tras_evento.append(dias)
        if t is not None and dias <= 30:
            d30 += 1
        elif t is not None and dias <= 90:
            d90 += 1
    m["cohorte_evento_grave"] = len(cohorte)
    m["atendidos_antes_del_evento"] = antes
    m["atendidos_<=30d_tras_evento"] = d30
    m["atendidos_31-90d_tras_evento"] = d90
    m["sin_atencion_>90d_o_no_atendidos"] = len(cohorte) - antes - d30 - d90
    m["pct_atendidos_<=30d_tras_evento"] = round(100 * d30 / len(cohorte), 1) if cohorte else None
    m["mediana_dias_evento_a_atencion"] = median(esperas_tras_evento) if esperas_tras_evento else None

    # 3) Esperas extremas al final del período (pacientes vivos que siguen esperando)
    siguen = [p for p in pac if p.id_paciente not in atendido and p.fecha_ingreso <= fin
              and not (p.fecha_defuncion and p.fecha_defuncion <= fin)]
    for pr in ("alta", "media", "baja"):
        dias = [(fin - p.fecha_ingreso).days for p in siguen if p.prioridad_inicial == pr]
        m[f"espera_max_final_{pr}"] = max(dias) if dias else 0
    m["siguen_esperando"] = len(siguen)
    m["siguen_esperando_>365d"] = sum(1 for p in siguen if (fin - p.fecha_ingreso).days > 365)

    # 4) Equidad: % atendido por nivel socioeconómico y ruralidad
    for grupo, filtro in [("nse_bajo", lambda p: p.nivel_socioeconomico == "bajo"),
                          ("nse_medio", lambda p: p.nivel_socioeconomico == "medio"),
                          ("rural", lambda p: p.comuna in RURALES),
                          ("urbano", lambda p: p.comuna not in RURALES)]:
        g = [p for p in pac if filtro(p) and p.fecha_ingreso <= fin]
        m[f"pct_atendido_{grupo}"] = round(100 * sum(p.id_paciente in atendido for p in g) / len(g), 1) if g else None
    return m


# ----------------------------------------------------------------------------
FILAS_CLAVE = [
    ("pct_atendidos_<=30d_tras_evento", "% atendidos ≤30 días tras su primer evento grave"),
    ("mediana_dias_evento_a_atencion", "Mediana de días entre evento grave y atención"),
    ("eventos_graves_en_espera", "Eventos graves ocurridos estando en lista"),
    ("atendidos_baja", "Pacientes 'baja' atendidos"),
    ("siguen_esperando_>365d", "Pacientes que siguen esperando > 365 días"),
    ("pct_atendido_nse_bajo", "% atendido, NSE bajo"),
    ("pct_atendido_rural", "% atendido, comunas rurales"),
]


def _celda(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    return f"{v:g}" if isinstance(v, float) else str(v)


def correr(fracciones=(0.15, 0.25, 0.40), inicio=INICIO, fin=FIN, carpeta_salida=None):
    datos, cfg = Datos.cargar(), cargar_regla()
    ini, fn = periodo(datos, inicio, fin)
    salida = Path(carpeta_salida or RAIZ / "sim" / "resultados")
    salida.mkdir(parents=True, exist_ok=True)

    filas, perdidos = [], {}
    for fr in fracciones:
        cap = capacidad_escalada(datos, fr, ini, fn)
        for modo in POLITICAS:
            atendido, _ = simular(datos, cfg, modo, cap)
            filas.append({"capacidad": f"{int(fr * 100)}%", "politica": modo, **metricas(datos, atendido, ini, fn)})
            if fr == 0.25:
                pd.DataFrame([{"id_paciente": k, "fecha_atencion": v} for k, v in atendido.items()]) \
                    .to_csv(salida / f"atenciones_{modo}_25.csv", index=False)
        perdidos[f"{int(fr * 100)}%"] = simular(datos, cfg, "actual", cap, excluir_fallecidos=False)[1]
    df = pd.DataFrame(filas)
    df.attrs["periodo"] = f"{ini.strftime('%d-%m-%Y')} al {fn.strftime('%d-%m-%Y')}"
    df["periodo"] = df.attrs["periodo"]
    df.to_csv(salida / "metricas.csv", index=False)

    out = [f"# Resultados de la simulación ({df.attrs.get('periodo', '')})\n",
           "Datos sintéticos del desafío. Contrafactual simplificado: ver supuestos en sim/simulador.py.\n"]
    for capac, g in df.groupby("capacidad", sort=False):
        g = g.set_index("politica")
        out.append(f"\n## Capacidad: cada especialidad atiende al {capac} de sus pacientes en el período\n")
        out.append(f"Cohorte con evento grave durante la espera: {int(g['cohorte_evento_grave'].iloc[0])} pacientes.\n")
        out.append("| Métrica | " + " | ".join(NOMBRES[p] for p in POLITICAS) + " |")
        out.append("|---|" + "---|" * len(POLITICAS))
        for col, nombre in FILAS_CLAVE:
            out.append(f"| {nombre} | " + " | ".join(_celda(g.loc[p, col]) for p in POLITICAS) + " |")
        out.append(f"\nSi la regla actual no detecta defunciones, entregaría **{perdidos[capac]} cupos a pacientes fallecidos**.\n")
    (salida / "resumen.md").write_text("\n".join(out) + "\n", encoding="utf-8")
    return df


def sensibilidad(fraccion=0.25, inicio=INICIO, fin=FIN):
    """Robustez de los dos parámetros de política del MVP: ventana del carril y cupo por antigüedad."""
    datos, cfg0 = Datos.cargar(), cargar_regla()
    ini, fn = periodo(datos, inicio, fin)
    cap = capacidad_escalada(datos, fraccion, ini, fn)
    cols = [("pct_atendidos_<=30d_tras_evento", "% ≤30 d tras evento grave"),
            ("eventos_graves_en_espera", "Eventos graves en lista"),
            ("atendidos_baja", "'Baja' atendidos"),
            ("siguen_esperando_>365d", "Siguen > 365 d"),
            ("pct_atendido_rural", "% rural atendido")]
    md = [f"# Sensibilidad del MVP (capacidad {int(fraccion * 100)}%)\n"]

    def tabla(titulo, etiqueta, variantes):
        md.extend([f"\n## {titulo}\n", f"| {etiqueta} | " + " | ".join(n for _, n in cols) + " |",
                   "|---|" + "---|" * len(cols)])
        for nombre, cfg, cupo, modo in variantes:
            m = metricas(datos, simular(datos, cfg, modo, cap, cupo_antiguedad=cupo)[0], ini, fn)
            md.append(f"| {nombre} | " + " | ".join(_celda(m[c]) for c, _ in cols) + " |")

    variantes = [("regla actual", cfg0, 0.0, "actual")]
    for v in (14, 30, 60):
        c = copy.deepcopy(cfg0)
        c["carril_rapido"]["ventana_dias"] = v
        variantes.append((f"{v} días", c, 0.0, "carril_plazo"))
    tabla("Ventana del carril rápido (sin cupo por antigüedad, para aislar su efecto)", "Ventana", variantes)
    tabla("Cupo de agenda reservado por antigüedad (decisión de política del hospital)", "Cupo",
          [("regla actual", cfg0, 0.0, "actual")] +
          [(f"{int(v * 100)}%", cfg0, v, "carril_plazo") for v in (0.0, 0.1, 0.2, 0.3)])
    salida = RAIZ / "sim" / "resultados"
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "sensibilidad.md").write_text("\n".join(md) + "\n", encoding="utf-8")


def estabilidad(datos: Datos, cfg: dict, ini: date, fin: date, semanal: bool, top: int = 20) -> float:
    """% de días hábiles en que cambia el orden de los `top` primeros de una especialidad (lo que ve la gestora
    al abrir la lista), con recálculo diario o con corte semanal. Se mide sobre todos los días hábiles, no solo
    los días con agenda."""
    from motor.cortes import corte_vigente
    from motor.puntaje import estado_en_lista
    por_esp = defaultdict(list)
    for p in datos.pacientes.values():
        por_esp[p.especialidad].append(p)
    con_cambio = total = 0
    for esp, pacs in por_esp.items():
        previo, cache = None, {}
        d = ini
        while d <= fin:
            if d.weekday() < 5:
                f = corte_vigente(d, cfg) if semanal else d
                if f not in cache:
                    ev = [evaluar_paciente(p, f, cfg, "carril_plazo") for p in pacs if estado_en_lista(p, f)[0]]
                    cache = {f: [r["id_paciente"] for r in sorted(ev, key=lambda r: clave_orden(r, "carril_plazo"))]}
                orden = cache[f][:top]
                if previo is not None:
                    total += 1
                    pos = {pid: i for i, pid in enumerate(cache[f])}
                    comunes = [pid for pid in previo if pid in pos]
                    con_cambio += any(pos[a] > pos[b] for i, a in enumerate(comunes) for b in comunes[i + 1:]) or \
                        any(pid not in previo for pid in orden)
                previo = orden
            d = date.fromordinal(d.toordinal() + 1)
    return round(100 * con_cambio / total, 1) if total else 0.0


def cadencia(fraccion=0.25, inicio=INICIO, fin=FIN):
    """¿Repriorizar cada día o una vez por semana? (entrevista 6). Misma regla MVP, tres cadencias."""
    datos, cfg = Datos.cargar(), cargar_regla()
    ini, fn = periodo(datos, inicio, fin)
    cap = capacidad_escalada(datos, fraccion, ini, fn)
    variantes = [("diaria", "Recalcular cada día"), ("semanal", "Corte semanal (lunes), sin alertas"),
                 ("semanal_alertas", "Corte semanal + alertas diarias que se adelantan")]
    filas = []
    for cad, nombre in [("actual", "Regla actual (referencia)")] + variantes:
        ordenes: dict = {}
        if cad == "actual":
            at, _ = simular(datos, cfg, "actual", cap, ordenes=ordenes)
        else:
            at, _ = simular(datos, cfg, "carril_plazo", cap, cadencia=cad, ordenes=ordenes)
        m = metricas(datos, at, ini, fn)
        filas.append({"cadencia": cad, "nombre": nombre, **{c: m[c] for c, _ in FILAS_CLAVE[:3]},
                      "siguen_esperando_>365d": m["siguen_esperando_>365d"],
                      "pct_dias_orden_cambia_top20": (None if cad == "actual" else
                                                      estabilidad(datos, cfg, ini, fn, semanal=cad != "diaria"))})
    df = pd.DataFrame(filas)
    salida = RAIZ / "sim" / "resultados"
    df.to_csv(salida / "cadencia.csv", index=False)
    md = [f"# ¿Cada día o una vez por semana? (capacidad {int(fraccion * 100)}%, {ini.strftime('%d-%m-%Y')} al "
          f"{fn.strftime('%d-%m-%Y')})\n",
          "Misma regla MVP con tres cadencias. «Días en que el orden cambia»: % de días hábiles en que la gestora abre "
          "la lista y alguien de los 20 primeros fue pasado por otro, o entró alguien nuevo arriba. Con corte semanal "
          "solo puede cambiar los lunes; las alertas se adelantan a mano, con motivo.\n",
          "| Cadencia | % ≤30 d tras evento grave | Mediana días evento → atención | Eventos graves en lista | "
          "Siguen > 365 d | Días en que el orden cambia (top 20) |", "|---|---|---|---|---|---|"]
    for r in filas:
        est = "—" if r["pct_dias_orden_cambia_top20"] is None else f"{_celda(r['pct_dias_orden_cambia_top20'])}%"
        md.append(f"| {r['nombre']} | {_celda(r['pct_atendidos_<=30d_tras_evento'])} | "
                  f"{_celda(r['mediana_dias_evento_a_atencion'])} | {r['eventos_graves_en_espera']} | "
                  f"{r['siguen_esperando_>365d']} | {est} |")
    (salida / "cadencia.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return df


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fracciones", default="0.15,0.25,0.40")
    a = ap.parse_args()
    correr(tuple(float(x) for x in a.fracciones.split(",")))
    sensibilidad()
    cadencia()
    print((RAIZ / "sim" / "resultados" / "cadencia.md").read_text(encoding="utf-8"))
    print((RAIZ / "sim" / "resultados" / "resumen.md").read_text(encoding="utf-8"))
    print((RAIZ / "sim" / "resultados" / "sensibilidad.md").read_text(encoding="utf-8"))
