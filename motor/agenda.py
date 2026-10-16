"""Uso del recurso box: propuesta de agenda para un día.

Toma la lista priorizada (motor.priorizar) y la agenda de boxes de ese día y propone, para cada box:
  - quiénes ocupan los cupos (en orden de la lista),
  - sobrecupos SOLO si caben: se agrega uno mientras la probabilidad de pasarse más de 30 minutos del
    bloque siga bajo 10%, simulando con las duraciones reales de atención de la especialidad,
  - a quién llamar 48 h antes para confirmar (riesgo alto de no llegar o inasistencias previas),
  - qué exámenes confirmar antes de la cita (si la indicación de control los pide),
y para cada especialidad una lista de reserva para llenar los cupos que se liberan por cancelaciones.

Nada de esto cambia el orden clínico de la lista: el riesgo de inasistencia decide acciones de agenda
(llamar, sobrecupo), nunca quién se atiende primero.

Parámetros de cada especialidad (calibrados con los datos, sin insumo clínico):
  - p_asiste: uso histórico de cupos de la especialidad (agenda_box.csv: cupos_usados / capacidad).
  - el resto se reparte entre "no llega sin avisar" y "avisa (cancela o reprograma)" en la proporción
    observada en citaciones.csv.
  - riesgo de no llegar de cada paciente: su propia historia de citas, acercada a la tasa de la
    especialidad cuando tiene pocas citas: (inasistencias + m * tasa) / (citas + m), con m = 4.
  - duraciones de atención: minutos_atencion_real de las citas a las que asistieron.
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .priorizacion import priorizar
from .puntaje import Datos, Paciente, _a_fecha

N_SIM = 2000


def _ca(cfg: dict) -> dict:
    a = cfg.get("agenda", {})
    return {"duracion": a.get("duracion_bloque_min", 300),
            "m": a.get("inasistencia", {}).get("fuerza_prior", 4),
            "umbral_llamada": a.get("inasistencia", {}).get("umbral_llamada", 0.30),
            "sobrecupo": a.get("sobrecupo", {"activo": True, "max_por_box": 2, "minutos_tolerancia": 30,
                                             "prob_max_pasarse": 0.10}),
            "reserva_extra": a.get("reserva_extra", 1)}


def parametros_box(datos: Datos, corte, cfg: dict) -> dict:
    """Tasas y duraciones por especialidad, con datos hasta `corte`."""
    corte = _a_fecha(corte)
    ag = datos.agenda.copy()
    ag["f"] = pd.to_datetime(ag["fecha"]).dt.date
    ag = ag[ag.f <= corte]
    citas = [c for p in datos.pacientes.values() for c in p.citas if c["fecha"] <= corte]
    ns = sum(c["estado_cita"] == "no_asistio" for c in citas)
    av = sum(c["estado_cita"] in ("cancelo", "reprogramo") for c in citas)
    parte_ns = ns / (ns + av) if ns + av else 0.5
    tiempos_global = np.array([c["minutos_atencion_real"] for c in citas if c["estado_cita"] == "asistio"
                               and pd.notna(c.get("minutos_atencion_real"))], dtype=float)
    uso_global = ag.cupos_usados.sum() / ag.capacidad_cupos.sum() if len(ag) else 0.75
    out = {}
    for esp in sorted({p.especialidad for p in datos.pacientes.values()} | set(ag.especialidad)):
        g = ag[ag.especialidad == esp]
        uso = g.cupos_usados.sum() / g.capacidad_cupos.sum() if g.capacidad_cupos.sum() else uso_global
        t = np.array([c["minutos_atencion_real"] for c in citas if c["estado_cita"] == "asistio"
                      and c.get("especialidad") == esp and pd.notna(c.get("minutos_atencion_real"))], dtype=float)
        out[esp] = {"p_asiste": float(uso), "p_no_llega": float((1 - uso) * parte_ns),
                    "p_avisa": float((1 - uso) * (1 - parte_ns)),
                    "tiempos": t if len(t) >= 8 else tiempos_global,
                    "minutos_media": float((t if len(t) >= 8 else tiempos_global).mean())}
    return out


def riesgo_no_llega(p: Paciente, corte, tasa: float, m: float) -> tuple[float, int, int]:
    """Riesgo de no llegar sin avisar: historia del paciente acercada a la tasa de su especialidad."""
    corte = _a_fecha(corte)
    previas = [c for c in p.citas if c["fecha"] < corte and c["estado_cita"] in ("asistio", "no_asistio")]
    k = sum(c["estado_cita"] == "no_asistio" for c in previas)
    return (k + m * tasa) / (len(previas) + m), k, len(previas)


def simular_bloque(p_asiste, tiempos, duracion: int, tolerancia: int, n_sim: int = N_SIM, semilla: int = 0) -> dict:
    """Asistentes, sobretiempo y minutos ociosos esperados de un bloque, por simulación."""
    p = np.asarray(p_asiste, dtype=float)
    if len(p) == 0:
        return {"asistentes": 0.0, "sobretiempo": 0.0, "p_pasarse": 0.0, "ociosos": float(duracion)}
    rng = np.random.default_rng(semilla)
    asiste = rng.random((n_sim, len(p))) < p
    total = (asiste * rng.choice(tiempos, size=(n_sim, len(p)))).sum(axis=1)
    sobre = np.maximum(0.0, total - duracion)
    return {"asistentes": float(asiste.sum(axis=1).mean()), "sobretiempo": float(sobre.mean()),
            "p_pasarse": float((sobre > tolerancia).mean()), "ociosos": float(np.maximum(0.0, duracion - total).mean())}


def citas_que_caben(pe: dict, ca: dict, maximo: int, semilla: int = 0) -> int:
    """Cuántas citas de pacientes típicos de la especialidad caben en el bloque sin que la probabilidad de
    pasarse más de la tolerancia supere el límite. Si es menor que la capacidad, el bloque está sobreagendado
    para las duraciones reales de atención."""
    sc = ca["sobrecupo"]
    caben = 0
    for n in range(1, maximo + 1):
        est = simular_bloque([pe["p_asiste"]] * n, pe["tiempos"], ca["duracion"], sc["minutos_tolerancia"],
                             semilla=semilla)
        if est["p_pasarse"] > sc["prob_max_pasarse"]:
            break
        caben = n
    return caben


def _acciones(r: dict, p: Paciente, riesgo: float, umbral: float) -> list[str]:
    acc = []
    if r.get("carril_rapido"):
        acc.append(f"Carril rápido: {r['motivo_carril']}")
    if riesgo >= umbral or pd.notna(r.get("alerta_contacto")):
        acc.append("Llamar 48 h antes para confirmar")
    if pd.notna(r.get("verificar_estado")):
        acc.append("Sin datos recientes: preguntar cómo está al llamar")
    ind = p.indicacion or {}
    if ind.get("continua_control") and ind.get("requiere_examen"):
        ex = ", ".join(ind.get("examenes") or []) or "exámenes indicados"
        acc.append(f"Confirmar que tenga resultado de {ex}")
    return acc


def proponer_agenda(datos: Datos, fecha, cfg: dict, especialidad: str | None = None,
                    lista: pd.DataFrame | None = None, semilla: int = 0) -> dict:
    """Propuesta de agenda para `fecha`. Devuelve {'citas', 'boxes', 'reserva', 'resumen'} (DataFrames y dict)."""
    fecha = _a_fecha(fecha)
    ca = _ca(cfg)
    sc = ca["sobrecupo"]
    ag = datos.agenda.copy()
    ag = ag[pd.to_datetime(ag["fecha"]).dt.date == fecha]
    if especialidad:
        ag = ag[ag.especialidad == especialidad]
    vacio = {"citas": pd.DataFrame(), "boxes": pd.DataFrame(), "reserva": pd.DataFrame(),
             "resumen": {"bloques": 0, "cupos": 0, "citados": 0, "sobrecupos": 0}}
    if ag.empty:
        return vacio
    params = parametros_box(datos, fecha, cfg)
    if lista is None:
        lista = priorizar(datos, fecha, cfg, especialidad=especialidad)
    citas, boxes, reserva = [], [], []
    for esp, bloques in ag.groupby("especialidad"):
        pe = params[esp]
        cola = lista[lista.especialidad == esp].sort_values("puesto").to_dict("records") if len(lista) else []
        i, p_avisa_total = 0, 0.0

        def _fila(r, rol, id_box, orden):
            p = datos.pacientes[r["id_paciente"]]
            riesgo, k, n = riesgo_no_llega(p, fecha, pe["p_no_llega"], ca["m"])
            p_asiste = max(0.05, 1 - riesgo - pe["p_avisa"])
            return {"especialidad": esp, "id_box": id_box, "rol": rol, "orden": orden,
                    "id_paciente": r["id_paciente"], "puesto_lista": r["puesto"], "motivo_puesto": r["motivo_puesto"],
                    "prioridad_inicial": r["prioridad_inicial"], "dias_espera": r["dias_espera"],
                    "riesgo_no_llega": round(riesgo, 2), "inasistencias_previas": k, "citas_previas": n,
                    "p_asiste": p_asiste,
                    "acciones": _acciones(r, p, riesgo, ca["umbral_llamada"])}

        for b in bloques.sort_values("id_box").itertuples():
            cap = int(b.capacidad_cupos)
            filas = []
            while len(filas) < cap and i < len(cola):
                filas.append(_fila(cola[i], "cupo", b.id_box, len(filas) + 1))
                i += 1
            sobre = 0
            if sc.get("activo") and len(filas) == cap:
                while sobre < sc["max_por_box"] and i < len(cola):
                    cand = _fila(cola[i], "sobrecupo", b.id_box, len(filas) + 1)
                    est = simular_bloque([f["p_asiste"] for f in filas] + [cand["p_asiste"]], pe["tiempos"],
                                         ca["duracion"], sc["minutos_tolerancia"], semilla=semilla)
                    if est["p_pasarse"] > sc["prob_max_pasarse"]:
                        break
                    filas.append(cand)
                    sobre += 1
                    i += 1
            est = simular_bloque([f["p_asiste"] for f in filas], pe["tiempos"], ca["duracion"],
                                 sc["minutos_tolerancia"], semilla=semilla)
            base = simular_bloque([f["p_asiste"] for f in filas[:cap]], pe["tiempos"], ca["duracion"],
                                  sc["minutos_tolerancia"], semilla=semilla)
            caben = citas_que_caben(pe, ca, cap + sc["max_por_box"], semilla)
            p_avisa_total += pe["p_avisa"] * len(filas)
            citas += filas
            boxes.append({"especialidad": esp, "id_box": b.id_box, "capacidad": cap, "citados": len(filas),
                          "sobrecupos": sobre, "cupos_sin_paciente": max(0, cap - len(filas)),
                          "asistentes_esperados": round(est["asistentes"], 1),
                          "asistentes_sin_sobrecupo": round(base["asistentes"], 1),
                          "sobretiempo_esperado_min": round(est["sobretiempo"]),
                          "prob_pasarse_tolerancia": round(est["p_pasarse"], 2),
                          "minutos_ociosos_esperados": round(est["ociosos"]),
                          "citas_que_caben": caben,
                          "minutos_por_cupo": round(ca["duracion"] / cap),
                          "minutos_atencion_media": round(pe["minutos_media"])})
        n_reserva = math.ceil(p_avisa_total) + ca["reserva_extra"]
        for r in cola[i:]:
            if len([x for x in reserva if x["especialidad"] == esp]) >= n_reserva:
                break
            if pd.notna(r.get("alerta_contacto")):      # la reserva se llama el mismo día: que sea contactable
                continue
            reserva.append({"especialidad": esp, "orden": len([x for x in reserva if x["especialidad"] == esp]) + 1,
                            "id_paciente": r["id_paciente"], "puesto_lista": r["puesto"],
                            "prioridad_inicial": r["prioridad_inicial"], "motivo_puesto": r["motivo_puesto"]})
    citas_df, boxes_df = pd.DataFrame(citas), pd.DataFrame(boxes)
    resumen = {"bloques": len(boxes_df), "cupos": int(boxes_df.capacidad.sum()), "citados": len(citas_df),
               "sobrecupos": int(boxes_df.sobrecupos.sum()), "cupos_sin_paciente": int(boxes_df.cupos_sin_paciente.sum()),
               "asistentes_esperados": round(float(boxes_df.asistentes_esperados.sum()), 1),
               "asistentes_sin_sobrecupo": round(float(boxes_df.asistentes_sin_sobrecupo.sum()), 1),
               "llamar": int(citas_df.acciones.map(lambda a: any(x.startswith("Llamar") for x in a)).sum()) if len(citas_df) else 0,
               "reserva": len(reserva),
               "bloques_sobreagendados": int((boxes_df.capacidad > boxes_df.citas_que_caben).sum())}
    return {"citas": citas_df, "boxes": boxes_df, "reserva": pd.DataFrame(reserva), "resumen": resumen}


def _dias_sin_datos(r) -> str | None:
    """Texto para la llamada si la persona está marcada 'sin datos recientes' (r: fila de la lista o {})."""
    if r is None or len(r) == 0 or pd.isna(r.get("verificar_estado")):
        return None
    d = r.get("dias_sin_datos")
    cuanto = f"hace {int(d)} días" if pd.notna(d) else "recientes"
    return f"sin datos clínicos {cuanto}: preguntar cómo está y si aún necesita la hora"


def llamadas_del_dia(prop: dict, lista: pd.DataFrame) -> pd.DataFrame:
    """Una fila por persona a llamar para la agenda propuesta, en el orden en que conviene llamar.

    1. Citados: confirmar asistencia (riesgo alto o inasistencias previas), preguntar cómo está si no hay datos
       recientes y recordar exámenes pendientes.
    2. Próximos en la lista sin datos recientes: los que entrarían en la siguiente agenda (tantos puestos como
       citas del día). Llamarlos antes evita que un cupo se pierda en alguien que ya no necesita la hora.
    3. Reserva: llamar solo si se libera un cupo, en orden.
    """
    cols = ["orden_llamada", "grupo", "cuando", "especialidad", "id_paciente", "puesto_lista", "id_box", "orden_cita",
            "motivos"]
    citas, reserva = prop.get("citas", pd.DataFrame()), prop.get("reserva", pd.DataFrame())
    if citas is None or citas.empty:
        return pd.DataFrame(columns=cols)
    por_id = lista.set_index("id_paciente") if len(lista) else pd.DataFrame()
    fila_lista = (lambda pid: por_id.loc[pid] if pid in por_id.index else {})
    filas = []
    for c in citas.sort_values(["especialidad", "id_box", "orden"]).itertuples():
        motivos = []
        if any(a.startswith("Llamar") for a in c.acciones):
            if c.inasistencias_previas:
                motivos.append("confirmar que viene: no llegó a su cita anterior" if c.citas_previas == 1 else
                               f"confirmar que viene: no llegó a {c.inasistencias_previas} de sus "
                               f"{c.citas_previas} citas anteriores")
            else:
                motivos.append(f"confirmar que viene: riesgo de no llegar {c.riesgo_no_llega:.0%}")
        sin_datos = _dias_sin_datos(fila_lista(c.id_paciente))
        if sin_datos:
            motivos.append(sin_datos)
        motivos += [a[0].lower() + a[1:] for a in c.acciones if a.startswith("Confirmar que tenga")]
        if motivos:
            filas.append({"grupo": "1 · Citado", "cuando": "48 h antes de la cita", "especialidad": c.especialidad,
                          "id_paciente": c.id_paciente, "puesto_lista": c.puesto_lista, "id_box": c.id_box,
                          "orden_cita": c.orden, "motivos": "; ".join(motivos)})
    en_reserva = set(reserva.id_paciente) if len(reserva) else set()
    for esp, cs in citas.groupby("especialidad"):
        ultimo, n = int(cs.puesto_lista.max()), len(cs)
        prox = lista[(lista.especialidad == esp) & (lista.puesto > ultimo) & (lista.puesto <= ultimo + n)
                     & lista.verificar_estado.notna() & ~lista.id_paciente.isin(en_reserva)]
        for r in prox.sort_values("puesto").to_dict("records"):
            filas.append({"grupo": "2 · Próximo en la lista", "cuando": "esta semana", "especialidad": esp,
                          "id_paciente": r["id_paciente"], "puesto_lista": r["puesto"], "id_box": None,
                          "orden_cita": None, "motivos": _dias_sin_datos(r)})
    if len(reserva):
        for r in reserva.sort_values(["especialidad", "orden"]).itertuples():
            motivos = [f"reserva n.º {r.orden}: ofrecer la hora solo si alguien avisa que no viene"]
            sin_datos = _dias_sin_datos(fila_lista(r.id_paciente))
            if sin_datos:
                motivos.append(sin_datos)
            filas.append({"grupo": "3 · Reserva", "cuando": "si se libera un cupo", "especialidad": r.especialidad,
                          "id_paciente": r.id_paciente, "puesto_lista": r.puesto_lista, "id_box": None,
                          "orden_cita": None, "motivos": "; ".join(motivos)})
    df = pd.DataFrame(filas, columns=cols[1:])
    df.insert(0, "orden_llamada", range(1, len(df) + 1))
    df["orden_cita"] = df["orden_cita"].astype("Int64")
    return df
