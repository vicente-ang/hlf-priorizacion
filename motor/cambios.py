"""Qué cambió en la lista entre dos fechas: la revisión de cada mañana del equipo de gestión.

El hospital trabaja con reportes diarios (carpeta Polo). Cada día llegan atenciones, urgencias,
hospitalizaciones e indicaciones nuevas; esta función compara la lista de antes con la de ahora y dice
a quién mirar primero:

  - Entró al carril rápido      evento grave reciente: revisar hoy
  - Salió de la lista           falleció, fue atendido o el médico indicó alta
  - Subió / Bajó                movimiento de al menos `umbral` puestos en su especialidad
  - Nueva señal de deterioro    evento o medición nueva, aunque no lo haya movido mucho
  - Sin datos recientes         pasó a no tener datos en 180 días: llamar
  - Entró a la lista            interconsulta nueva
  - Salió del carril rápido     informativo: ya pasaron 30 días del evento

`datos_antes` y `datos_despues` pueden ser el mismo objeto (todo está fechado: la lista de antes usa solo
datos hasta `desde`) o dos cargas distintas (antes y después de incorporar un reporte).
"""
from __future__ import annotations

import pandas as pd

from .explicar import redactar_con_bedrock
from .priorizacion import evaluar_paciente, priorizar
from .puntaje import ETIQUETAS_MEDICION, ETIQUETAS_SUBTIPO, Datos, _a_fecha

ORDEN_TIPOS = ["Entró al carril rápido", "Salió de la lista", "Subió", "Nueva señal de deterioro",
               "Sin datos recientes", "Entró a la lista", "Bajó", "Salió del carril rápido"]
MOTIVO_SALIDA = {"fallecido": "falleció", "atendido": "fue atendido", "alta_indicada": "alta indicada por el médico",
                 "agendado": "tiene hora agendada"}


def _llegado(p, desde, hasta) -> list[str]:
    """Lo que llegó del paciente entre las dos fechas (eventos no rutinarios y mediciones)."""
    out = []
    for e in p.eventos:
        if desde < e["fecha"] <= hasta and e["subtipo"] not in ("control", "control crónico", "control de rutina"):
            out.append(f"{ETIQUETAS_SUBTIPO.get(e['subtipo'], e['subtipo'])} ({e['fecha'].strftime('%d-%m')})")
    for m in p.mediciones:
        if desde < m["fecha"] <= hasta:
            alerta = " fuera de rango" if m["fuera_de_rango"] else ""
            out.append(f"{ETIQUETAS_MEDICION.get(m['tipo_medicion'], m['tipo_medicion'])} {m['valor']:g}{alerta} "
                       f"({m['fecha'].strftime('%d-%m')})")
    return out


def _senales_nuevas(p, desde, hasta, cfg) -> list[str]:
    """Señales de deterioro que LLEGARON en el período: eventos moderados o graves (no de mejora) y
    mediciones que PASARON a fuera de rango (si ya estaban fuera de rango, no es novedad)."""
    mejora = set(cfg["senales"]["subtipos_mejora"])
    from .pertinencia import es_pertinente
    out = [f"{ETIQUETAS_SUBTIPO.get(e['subtipo'], e['subtipo'])} ({e['fecha'].strftime('%d-%m')})"
           for e in p.eventos if desde < e["fecha"] <= hasta and e["severidad"] in ("moderada", "grave")
           and e["subtipo"] not in mejora and es_pertinente(p, e, cfg)]
    previa: dict[str, bool] = {}
    for m in p.mediciones:                       # ordenadas por fecha
        if m["fecha"] > hasta:
            break
        if desde < m["fecha"] and m["fuera_de_rango"] and not previa.get(m["tipo_medicion"], False):
            out.append(f"{ETIQUETAS_MEDICION.get(m['tipo_medicion'], m['tipo_medicion'])} pasó a fuera de rango "
                       f"({m['valor']:g}, {m['fecha'].strftime('%d-%m')})")
        previa[m["tipo_medicion"]] = m["fuera_de_rango"]
    return out


def cambios(datos_antes: Datos, datos_despues: Datos | None, desde, hasta, cfg: dict, modo: str | None = None,
            especialidad: str | None = None, umbral: int = 5) -> tuple[pd.DataFrame, dict]:
    desde, hasta = _a_fecha(desde), _a_fecha(hasta)
    datos_despues = datos_despues or datos_antes
    a = priorizar(datos_antes, desde, cfg, modo=modo, especialidad=especialidad)
    b = priorizar(datos_despues, hasta, cfg, modo=modo, especialidad=especialidad)
    a = a.set_index("id_paciente") if len(a) else pd.DataFrame()
    b = b.set_index("id_paciente") if len(b) else pd.DataFrame()
    filas = []

    def fila(pid, tipo, detalle, ra=None, rb=None):
        p = datos_despues.pacientes.get(pid) or datos_antes.pacientes[pid]
        filas.append({"tipo": tipo, "especialidad": p.especialidad, "id_paciente": pid,
                      "prioridad_inicial": p.prioridad_inicial,
                      "puesto_antes": int(ra["puesto"]) if ra is not None else None,
                      "puesto_ahora": int(rb["puesto"]) if rb is not None else None,
                      "en_especialidad": int(rb["en_especialidad"]) if rb is not None else None,
                      "detalle": detalle, "llego": "; ".join(_llegado(p, desde, hasta))})

    for pid in a.index.difference(b.index):
        r = evaluar_paciente(datos_despues.pacientes[pid], hasta, cfg) if pid in datos_despues.pacientes else None
        motivo = MOTIVO_SALIDA.get(r["motivo_fuera"], r["motivo_fuera"]) if r else "ya no está en los datos"
        fila(pid, "Salió de la lista", motivo, ra=a.loc[pid])
    for pid in b.index.difference(a.index):
        fila(pid, "Entró a la lista", f"Prioridad médica {b.loc[pid, 'prioridad_inicial']}", rb=b.loc[pid])
    for pid in a.index.intersection(b.index):
        ra, rb = a.loc[pid], b.loc[pid]
        nuevas = _senales_nuevas(datos_despues.pacientes[pid], desde, hasta, cfg)
        if rb["carril_rapido"] and not ra["carril_rapido"]:
            fila(pid, "Entró al carril rápido", rb["motivo_carril"], ra, rb)
            continue
        if ra["carril_rapido"] and not rb["carril_rapido"]:
            fila(pid, "Salió del carril rápido", "Pasaron 30 días desde el evento grave", ra, rb)
            continue
        delta = int(ra["puesto"]) - int(rb["puesto"])
        if delta >= umbral:
            fila(pid, "Subió", (f"Nuevo: {'; '.join(nuevas)}. " if nuevas else "Otros salieron de la lista o bajaron. ")
                 + f"Plazo vigente: {rb['motivo_plazo']}", ra, rb)
        elif nuevas:
            fila(pid, "Nueva señal de deterioro", "; ".join(nuevas), ra, rb)
        elif pd.notna(rb.get("verificar_estado")) and pd.isna(ra.get("verificar_estado")):
            fila(pid, "Sin datos recientes", f"{rb['dias_sin_datos']} días sin eventos ni mediciones", ra, rb)
        elif delta <= -umbral:
            fila(pid, "Bajó", "Otros pacientes pasaron adelante", ra, rb)

    df = pd.DataFrame(filas)
    if len(df):
        df["_o"] = df.tipo.map({t: i for i, t in enumerate(ORDEN_TIPOS)})
        df = df.sort_values(["_o", "especialidad", "puesto_ahora"], na_position="last").drop(columns="_o")
        df = df.reset_index(drop=True)
    resumen = {"desde": desde, "hasta": hasta, "en_lista_antes": len(a), "en_lista_ahora": len(b),
               **{t: int((df.tipo == t).sum()) if len(df) else 0 for t in ORDEN_TIPOS}}
    return df, resumen


def _n(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


SALIDA_TXT = {"falleció": ("falleció", "fallecieron"), "fue atendido": ("fue atendido", "fueron atendidos"),
              "alta indicada por el médico": ("recibió alta del médico", "recibieron alta del médico"),
              "tiene hora agendada": ("tiene hora agendada", "tienen hora agendada")}


def resumen_plantilla(df: pd.DataFrame, r: dict) -> str:
    periodo = f"Entre el {r['desde'].strftime('%d-%m-%Y')} y el {r['hasta'].strftime('%d-%m-%Y')}"
    relevantes = sum(r[t] for t in ORDEN_TIPOS if t not in ("Bajó", "Salió del carril rápido"))
    if df.empty or not relevantes:
        return f"{periodo} no hubo cambios relevantes en la lista ({r['en_lista_ahora']} personas en espera)."
    partes = [f"{periodo}:"]
    n = r["Entró al carril rápido"]
    if n:
        ids = ", ".join(df[df.tipo == "Entró al carril rápido"].id_paciente.head(5))
        partes.append(f"{_n(n, 'paciente entró', 'pacientes entraron')} al carril rápido por un evento grave ({ids}); "
                      "revisar hoy.")
    n = r["Salió de la lista"]
    if n:
        motivos = df[df.tipo == "Salió de la lista"].detalle.value_counts()
        detalle = ", ".join(f"{k} {SALIDA_TXT.get(m, (m, m))[0 if k == 1 else 1]}" for m, k in motivos.items())
        partes.append(f"{_n(n, 'persona salió', 'personas salieron')} de la lista: {detalle}.")
    if r["Subió"]:
        partes.append(f"{_n(r['Subió'], 'paciente subió', 'pacientes subieron')} 5 o más puestos.")
    if r["Nueva señal de deterioro"]:
        partes.append(f"{_n(r['Nueva señal de deterioro'], 'paciente tiene', 'pacientes tienen')} señales nuevas de "
                      "deterioro (evento moderado o medición que pasó a fuera de rango).")
    if r["Sin datos recientes"]:
        partes.append(f"{_n(r['Sin datos recientes'], 'paciente pasó', 'pacientes pasaron')} a no tener datos "
                      "recientes: conviene llamar.")
    if r["Entró a la lista"]:
        partes.append(f"{_n(r['Entró a la lista'], 'interconsulta nueva ingresó', 'interconsultas nuevas ingresaron')}.")
    partes.append(f"Hoy esperan {r['en_lista_ahora']} personas.")
    return " ".join(partes)


def resumen_para_equipo(df: pd.DataFrame, r: dict) -> tuple[str, str]:
    """Resumen del día redactado por Bedrock a partir de los hechos; plantilla si no hay Bedrock."""
    respaldo = resumen_plantilla(df, r)
    if df.empty:
        return respaldo, "plantilla"
    hechos = "\n".join(f"- {x.tipo}: {x.id_paciente} ({x.especialidad}, prioridad {x.prioridad_inicial})"
                       f"{'' if pd.isna(x.puesto_ahora) else f', puesto {int(x.puesto_ahora)}'}. {x.detalle}"
                       for x in df.head(25).itertuples())
    prompt = ("Eres un asistente del equipo de gestión de la demanda de un hospital público chileno. Con los hechos "
              "de abajo, escribe en español de Chile un resumen de la mañana de máximo 5 oraciones: primero a quién "
              "revisar hoy (carril rápido), luego quién salió de la lista y quién subió. Usa solo los hechos; no "
              "inventes diagnósticos ni recomendaciones clínicas. Cierra recordando que el equipo valida antes de citar.\n\n"
              f"Período: {r['desde']} a {r['hasta']}. Personas en espera hoy: {r['en_lista_ahora']}.\nHechos:\n{hechos}")
    return redactar_con_bedrock(prompt, respaldo)
