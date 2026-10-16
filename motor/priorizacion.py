"""Regla de priorización por defecto del MVP: CARRIL RÁPIDO + PLAZO DINÁMICO.

No usa pesos ni requiere calibración clínica (ver motor/config/regla.yaml).

1) Carril rápido: quien tuvo un evento grave (según el registro: ESI 2, hospitalización, UCI)
   en los últimos 30 días pasa adelante. Dentro del carril se respeta la regla actual.
2) Resto: se ordena por razón de atraso = (hoy - fecha objetivo) / plazo vigente.
   La fecha objetivo parte en ingreso + plazo según prioridad (30 / 90 / 180 días) y se
   adelanta con eventos o mediciones que empeoran.

Modos disponibles (mismo código para la lista, la demo, la Lambda y la simulación):
  carril_plazo  regla del MVP (por defecto)
  carril        regla actual del hospital + carril rápido
  actual        regla actual del hospital (alta -> media -> baja, más antiguo primero)
  puntaje       puntaje v1 con pesos a mano (motor/puntaje.py), opcional
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yaml

from .clusters import clusters
from .pertinencia import es_pertinente
from .puntaje import (ETIQUETAS_MEDICION, ETIQUETAS_SUBTIPO, ORDEN_PRIORIDAD, Datos, Paciente, _a_fecha,
                      _alerta_contacto, cargar_config as cargar_pesos_v1, estado_en_lista, puntuar_paciente)

REGLA_DEFECTO = Path(__file__).resolve().parent / "config" / "regla.yaml"
MODOS = ("carril_plazo", "carril", "actual", "puntaje")


def cargar_regla(ruta: str | Path | None = None, pesos_v1: str | Path | None = None) -> dict:
    """Configuración de la regla MVP. Incluye los pesos v1 en `pesos_v1` por si se usa ese modo."""
    with open(ruta or REGLA_DEFECTO, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["pesos_v1"] = cargar_pesos_v1(pesos_v1)
    return cfg


def _fmt(f: date | None) -> str:
    return f.strftime("%d-%m-%Y") if f else ""


def categoria_de_plazo(dias: int) -> str:
    """Plazo de hasta 30 días = alta, hasta 90 = media, más = baja (los cortes de los plazos base)."""
    return "alta" if dias <= 30 else "media" if dias <= 90 else "baja"


def prioridad_de_partida(p: Paciente, corte: date, cfg: dict) -> tuple[str, str, date | None]:
    """(prioridad, origen, fecha) con la que parte el paciente en la lista (T1).

    - "especialista": la asignó el especialista al leer la interconsulta (lo normal).
    - Si la interconsulta no fue priorizada (hay especialidades que no priorizan, entrevista 6):
        antes de `sin_priorizar.dias_para_proponer` días -> "provisoria" (plazo medio mientras el especialista la lee)
        después -> la que propone la guía por diagnóstico, "propuesta por guía (confirmar)", si la lectura fue
        segura; si quedó para revisar, sigue provisoria.
    """
    if not getattr(p, "sin_priorizar", False):
        return p.prioridad_inicial, "especialista", p.fecha_ingreso
    sp = cfg.get("sin_priorizar", {})
    provisoria = sp.get("prioridad_provisoria", "media")
    dias = (corte - p.fecha_ingreso).days
    prop = getattr(p, "propuesta", None) or {}
    if dias >= sp.get("dias_para_proponer", 21) and prop.get("estado") == "ok" and prop.get("prioridad"):
        return prop["prioridad"], "propuesta por guía, confirmar", p.fecha_ingreso + timedelta(
            days=sp.get("dias_para_proponer", 21))
    return provisoria, "provisoria: interconsulta sin priorizar", None


def _cuando(dias: int) -> str:
    return "hoy" if dias == 0 else "ayer" if dias == 1 else f"hace {dias} días"


def _mediciones_recientes(p: Paciente, corte: date, cfg: dict) -> dict[str, list]:
    por_tipo: dict[str, list] = {}
    for m in p.mediciones:
        if m["fecha"] > corte:
            break
        if (corte - m["fecha"]).days <= cfg["mediciones"]["ventana_dias"]:
            por_tipo.setdefault(m["tipo_medicion"], []).append(m)
    return por_tipo


def evaluar_paciente(p: Paciente, corte, cfg: dict, modo: str | None = None) -> dict:
    """Evalúa a un paciente usando SOLO información con fecha <= corte."""
    if isinstance(corte, str):
        corte = _a_fecha(corte)
    modo = modo or cfg.get("modo_por_defecto", "carril_plazo")
    en_lista, motivo_fuera = estado_en_lista(p, corte)
    dias_espera = (corte - p.fecha_ingreso).days if p.fecha_ingreso <= corte else 0
    cs, cp, cc = cfg["senales"], cfg["plazo"], cfg["carril_rapido"]
    rutina, mejora = set(cs["subtipos_rutina"]), set(cs["subtipos_mejora"])

    # --- Eventos: carril rápido, últimos eventos por gravedad y señales recientes
    carril, motivo_carril = False, None
    ultimo_grave = ultimo_moderado = None
    det, mej, no_rel = [], [], []
    for e in p.eventos:
        if e["fecha"] > corte:
            break
        if e["subtipo"] in rutina:
            continue
        dd = (corte - e["fecha"]).days
        etiqueta = ETIQUETAS_SUBTIPO.get(e["subtipo"], e["subtipo"])
        if e["subtipo"] in mejora:
            if dd <= cs["ventana_eventos_dias"]:
                mej.append(f"{etiqueta} ({_cuando(dd)})")
            continue
        if not es_pertinente(p, e, cfg):              # reunión 7: no relacionado con la derivación -> no mueve
            if dd <= cs["ventana_eventos_dias"]:
                motivo_e = e.get("diagnostico_texto") or e.get("diagnostico_cie10")
                no_rel.append(f"{etiqueta} por {motivo_e} ({_cuando(dd)})")
            continue
        if e["severidad"] == "grave":
            ultimo_grave = e
        elif e["severidad"] == "moderada":
            ultimo_moderado = e
        if e["severidad"] in cc["severidades"] and dd <= cc["ventana_dias"]:
            carril, motivo_carril = True, f"{etiqueta} {_cuando(dd)}"
        if dd <= cs["ventana_eventos_dias"]:
            det.append(f"{etiqueta} ({_cuando(dd)})")

    # --- Mediciones: fuera de rango y tendencia
    ultima_emp = None
    for tipo, serie in _mediciones_recientes(p, corte, cfg).items():
        ult, etiqueta = serie[-1], ETIQUETAS_MEDICION.get(tipo, tipo)
        if ult["fuera_de_rango"]:
            det.append(f"{etiqueta} fuera de rango ({ult['valor']:g} {ult['unidad']})")
        reglas = cfg["mediciones"]["tipos"].get(tipo)
        if reglas and len(serie) >= 2:
            u = serie[-3:]
            delta = u[-1]["valor"] - u[0]["valor"]
            if reglas["empeora_si"] == "baja":
                delta = -delta
            if delta >= reglas["umbral"]:
                det.append(f"{etiqueta} empeorando ({u[0]['valor']:g} → {u[-1]['valor']:g})")
                if ultima_emp is None or u[-1]["fecha"] > ultima_emp:
                    ultima_emp = u[-1]["fecha"]
            elif delta <= -reglas["umbral"]:
                mej.append(f"{etiqueta} mejorando ({u[0]['valor']:g} → {u[-1]['valor']:g})")

    # --- Prioridad de partida (T1): la del especialista o, si la interconsulta no fue priorizada,
    #     una provisoria y después la que propone la guía por diagnóstico (entrevista 6).
    prio, origen_prio, fecha_prio = prioridad_de_partida(p, corte, cfg)

    # --- Plazo dinámico: cada señal abre su propio plazo y manda el MÁS atrasado.
    #     (Así un evento nuevo nunca vuelve a un paciente menos urgente.)
    base = cp["base_dias"][prio]
    plazos = [(p.fecha_ingreso, base, f"{base} días desde el ingreso, por prioridad {prio}"
                                      + ("" if origen_prio == "especialista" else f" ({origen_prio})"))]
    ind = p.indicacion if p.indicacion and p.indicacion.get("fecha") and p.indicacion["fecha"] <= corte else None
    if ind and ind.get("continua_control") is True:
        # El plazo que indicó el médico reemplaza al plazo por prioridad (lista de controles)
        if ind.get("plazo_dias"):
            plazos = [(ind["fecha"], int(ind["plazo_dias"]),
                       f"{int(ind['plazo_dias'])} días indicados por el médico ({_fmt(ind['fecha'])})")]
        elif ind.get("prioritario"):
            plazos = [(ind["fecha"], cp["base_dias"]["alta"],
                       f"{cp['base_dias']['alta']} días: control prioritario sin plazo escrito ({_fmt(ind['fecha'])})")]
    if ultimo_grave:
        plazos.append((ultimo_grave["fecha"], cp["tras_evento_grave_dias"],
                       f"{cp['tras_evento_grave_dias']} días desde "
                       f"{ETIQUETAS_SUBTIPO.get(ultimo_grave['subtipo'], ultimo_grave['subtipo']).lower()} ({_fmt(ultimo_grave['fecha'])})"))
    if ultimo_moderado:
        plazos.append((ultimo_moderado["fecha"], cp["tras_evento_moderado_dias"],
                       f"{cp['tras_evento_moderado_dias']} días desde "
                       f"{ETIQUETAS_SUBTIPO.get(ultimo_moderado['subtipo'], ultimo_moderado['subtipo']).lower()} ({_fmt(ultimo_moderado['fecha'])})"))
    if ultima_emp:
        plazos.append((ultima_emp, cp["tras_medicion_empeorando_dias"],
                       f"{cp['tras_medicion_empeorando_dias']} días desde medición empeorando ({_fmt(ultima_emp)})"))
    inicio, plazo, motivo_plazo = max(plazos, key=lambda x: ((corte - x[0]).days - x[1]) / x[1])
    objetivo = inicio + timedelta(days=plazo)
    dias_atraso = (corte - objetivo).days
    razon = dias_atraso / plazo

    # --- Prioridad dinámica (T2): la categoría del plazo más exigente que tiene abierto el paciente.
    #     Un plazo de hasta 30 días es "alta", hasta 90 "media" y más largo "baja" (los mismos cortes de los
    #     plazos base). Así se puede decir "pasó de media a alta por la hospitalización del 02-10".
    prio_dyn, motivo_dyn = categoria_de_plazo(plazos[0][1]), None
    for ini_p, dias_p, mot_p in plazos[1:]:
        cat = categoria_de_plazo(dias_p)
        if ORDEN_PRIORIDAD[cat] < ORDEN_PRIORIDAD[prio_dyn]:
            # "14 días desde hospitalización (20-09-2026)" -> "hospitalización (20-09-2026), plazo de 14 días"
            senal = mot_p.split(" desde ", 1)
            prio_dyn, motivo_dyn = cat, (f"{senal[1]}, que pide atención en {dias_p} días" if len(senal) == 2
                                         else mot_p)
    if carril and prio_dyn != "alta":
        prio_dyn, motivo_dyn = "alta", f"carril rápido: {motivo_carril}"
    if motivo_dyn is None and prio_dyn != prio:      # la indicación del médico cambió el plazo de partida
        motivo_dyn = plazos[0][2]

    # Los clusters (y el índice LACE) solo hacen falta para ordenar dentro del carril; para el resto se calculan
    # al mostrar el detalle (motor.clusters.clusters), así la lista completa sigue siendo rápida.
    cl = clusters(p, corte, cfg) if carril else None

    # --- Sin señales recientes: no sabemos cómo está -> verificar (no cambia el orden)
    fechas = [x["fecha"] for x in p.eventos + p.mediciones if x["fecha"] <= corte]
    dias_sin_datos = (corte - max(fechas)).days if fechas else dias_espera
    verificar = None
    if (dias_sin_datos >= cs.get("dias_sin_senales", 180)
            and dias_espera >= cs.get("dias_espera_minimos_para_verificar", 90)):
        verificar = (f"Sin eventos ni mediciones hace {dias_sin_datos} días: verificar estado "
                     f"(llamada o cuestionario) antes de asumir que está estable")

    if ind and ind.get("continua_control") is False and en_lista:
        en_lista, motivo_fuera = False, "alta_indicada"

    r = {
        "id_paciente": p.id_paciente, "especialidad": p.especialidad, "prioridad_inicial": prio,
        "prioridad_origen": origen_prio, "fecha_prioridad": fecha_prio,
        "prioridad_dinamica": prio_dyn, "motivo_prioridad": motivo_dyn,
        "nivel_cuidado": cl["nivel_cuidado"] if cl else 3, "lace": ((cl or {}).get("lace") or {}).get("total"),
        "recurrencia": cl["recurrencia"] if cl else 0, "eventos_no_relacionados": no_rel,
        "clusters": cl,
        "fecha_ingreso": p.fecha_ingreso, "dias_espera": dias_espera, "en_lista": en_lista,
        "motivo_fuera": motivo_fuera, "modo": modo, "corte": corte, "version_regla": cfg.get("version"),
        "carril_rapido": carril, "motivo_carril": motivo_carril,
        "fecha_objetivo": objetivo, "plazo_dias": plazo, "motivo_plazo": motivo_plazo,
        "dias_atraso": dias_atraso, "razon_atraso": round(razon, 2),
        "senales_deterioro": det, "senales_mejora": mej,
        "alerta_contacto": _alerta_contacto(p, corte, cfg),
        "dias_sin_datos": dias_sin_datos, "verificar_estado": verificar,
        "indicacion_control": (ind or {}).get("texto"),
        "indicacion_revisar": (ind or {}).get("motivo_revision") if ind and ind.get("estado") == "revisar" else None,
        "orden_carril": tuple(cc.get("orden", ORDEN_CARRIL_DEFECTO)),
    }
    if modo == "puntaje":
        v1 = puntuar_paciente(p, corte, cfg["pesos_v1"])
        r.update({k: v1[k] for k in ("puntaje", "base", "espera", "eventos", "mediciones", "boleta",
                                     "top_razones", "bandera_revision", "motivo_bandera")})
    return r


ORDEN_CARRIL_DEFECTO = ("nivel_cuidado", "lace", "prioridad", "antiguedad")


def _clave_carril(r: dict, orden) -> tuple:
    """Orden DENTRO del carril rápido (entrevista 5: "no por orden de llegada"). Por defecto: nivel de cuidado
    más alto (UCI > sala > urgencia), luego episodios graves en 12 meses (reunión 7), luego índice LACE (más
    riesgo primero), luego prioridad y antigüedad."""
    partes = []
    for c in orden:
        if c == "nivel_cuidado":
            partes.append(r.get("nivel_cuidado", 3))
        elif c == "recurrencia":
            partes.append(-(r.get("recurrencia") or 0))
        elif c == "lace":
            partes.append(-(r.get("lace") or 0))
        elif c == "prioridad":
            partes.append(ORDEN_PRIORIDAD[r["prioridad_inicial"]])
        elif c == "antiguedad":
            partes.append(r["fecha_ingreso"].toordinal())
    return tuple(partes)


def clave_orden(r: dict, modo: str, orden_carril=None) -> tuple:
    """Clave para ordenar (menor = primero). La usan la lista, la demo y la simulación."""
    orden_carril = orden_carril or r.get("orden_carril") or ORDEN_CARRIL_DEFECTO
    actual = (ORDEN_PRIORIDAD[r["prioridad_inicial"]], r["fecha_ingreso"])
    if modo == "actual":
        return (0,) + actual
    if modo == "carril":
        return (0 if r["carril_rapido"] else 1,) + actual
    if modo == "carril_plazo":
        if r["carril_rapido"]:
            return (0,) + _clave_carril(r, orden_carril)
        return (1, -r["razon_atraso"], r["fecha_ingreso"].toordinal())
    if modo == "puntaje":
        return (-r["puntaje"], r["fecha_ingreso"])
    raise ValueError(f"modo desconocido: {modo}")


def ordenar(evaluaciones: list[dict], modo: str) -> list[dict]:
    return sorted(evaluaciones, key=lambda r: clave_orden(r, modo))


def es_turno_antiguedad(k: int, cupo: float) -> bool:
    """¿El puesto k (0, 1, 2, ...) le corresponde al cupo por antigüedad? Reparte `cupo` de forma pareja."""
    return cupo > 0 and int((k + 1) * cupo) > int(k * cupo)


def ordenar_con_cupo(evaluaciones: list[dict], modo: str, cupo: float) -> list[dict]:
    """Orden de UNA especialidad, intercalando el cupo por antigüedad (1 de cada 10 si cupo=0.1)."""
    por_regla = ordenar(evaluaciones, modo)
    if cupo <= 0:
        for r in por_regla:
            r["motivo_puesto"] = _motivo_puesto(r, modo)
        return por_regla
    por_antiguedad = sorted(evaluaciones, key=lambda r: r["fecha_ingreso"])
    filas = {"regla": por_regla, "antiguedad": por_antiguedad}
    punteros = {"regla": 0, "antiguedad": 0}      # cada fila avanza una sola vez: orden lineal, no cuadrático
    usados, salida = set(), []
    for k in range(len(evaluaciones)):
        clave = "antiguedad" if es_turno_antiguedad(k, cupo) else "regla"
        fila, i = filas[clave], punteros[clave]
        while fila[i]["id_paciente"] in usados:
            i += 1
        r = fila[i]
        punteros[clave] = i + 1
        usados.add(r["id_paciente"])
        r["motivo_puesto"] = "cupo por antigüedad" if clave == "antiguedad" else _motivo_puesto(r, modo)
        salida.append(r)
    return salida


def _motivo_puesto(r: dict, modo: str) -> str:
    if modo in ("carril", "carril_plazo") and r["carril_rapido"]:
        return "carril rápido"
    return {"carril_plazo": "atraso de su plazo", "carril": "regla actual", "actual": "regla actual",
            "puntaje": "puntaje v1"}[modo]


def priorizar(datos: Datos, corte, cfg: dict, modo: str | None = None, especialidad: str | None = None) -> pd.DataFrame:
    """Lista de trabajo a una fecha de corte, ordenada por especialidad (cada especialidad tiene su
    propia agenda). `puesto` es el orden de citación dentro de la especialidad."""
    modo = modo or cfg.get("modo_por_defecto", "carril_plazo")
    if isinstance(corte, str):
        corte = _a_fecha(corte)
    cupo = cfg.get("agenda", {}).get("cupo_antiguedad", 0.0) if modo == "carril_plazo" else 0.0
    evals = [evaluar_paciente(p, corte, cfg, modo) for p in datos.pacientes.values()
             if (not especialidad or p.especialidad == especialidad)]
    evals = [r for r in evals if r["en_lista"]]
    if not evals:
        return pd.DataFrame()
    por_esp: dict[str, list] = {}
    for r in evals:
        por_esp.setdefault(r["especialidad"], []).append(r)
    filas = []
    for esp in sorted(por_esp):
        actual = {r["id_paciente"]: i + 1 for i, r in enumerate(ordenar(por_esp[esp], "actual"))}
        for i, r in enumerate(ordenar_con_cupo(por_esp[esp], modo, cupo), start=1):
            filas.append({**r, "puesto": i, "en_especialidad": len(por_esp[esp]),
                          "puesto_regla_actual": actual[r["id_paciente"]]})
    df = pd.DataFrame(filas)
    df["cambio_puestos"] = df["puesto_regla_actual"] - df["puesto"]
    return df
