"""Puntaje v1 (MODO OPCIONAL) — suma de puntos con pesos definidos a mano.

La regla por defecto del MVP es "carril rápido + plazo dinámico" (motor/priorizacion.py),
que no necesita pesos ni calibración clínica. Este módulo además define la carga de datos
(Datos) que usan ambos modos.

Idea central: el puntaje es una SUMA DE PUNTOS VISIBLES ("boleta"), calculada solo con
la información disponible a una fecha de corte. La misma función sirve para:
  - la lista de trabajo de hoy,
  - recalcular a un paciente cuando llega un evento nuevo,
  - reproducir el pasado en la simulación (sin mirar el futuro).

Puntaje = base por prioridad médica
        + tiempo de espera (acumulación por clase, con tope)
        + eventos clínicos (con decaimiento temporal)
        + mediciones (fuera de rango y tendencia)
Además: bandera de revisión clínica, exclusión de fallecidos/atendidos y alerta de
contacto por inasistencias (sin efecto en el puntaje).
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parents[1]
DATOS_DEFECTO = RAIZ / "data" / "dataset_hlf_ambulatorio"
CONFIG_DEFECTO = Path(__file__).resolve().parent / "config" / "pesos_puntaje_v1.yaml"

ORDEN_PRIORIDAD = {"alta": 0, "media": 1, "baja": 2}

ETIQUETAS_SUBTIPO = {
    "ingreso UCI": "Ingreso a UCI",
    "ingreso hospitalario": "Hospitalización",
    "triage ESI 2": "Urgencia (triage ESI 2)",
    "descompensación grave": "Urgencia por descompensación grave",
    "descompensación": "Urgencia por descompensación",
    "triage ESI 3": "Urgencia (triage ESI 3)",
    "consulta de urgencia": "Consulta de urgencia",
    "resultado alterado": "Examen alterado",
    "aumento dosis": "Aumento de dosis",
    "buena respuesta": "Buena respuesta a tratamiento",
    "estabilización": "Estabilización",
    "reducción dosis": "Reducción de dosis",
}

ETIQUETAS_MEDICION = {
    "presion_sistolica": "Presión sistólica",
    "presion_diastolica": "Presión diastólica",
    "HbA1c": "HbA1c",
    "glicemia": "Glicemia",
    "saturacion_o2": "Saturación O2",
    "peak_flow": "Peak flow",
    "escala_dolor_eva": "Dolor (EVA)",
    "PHQ9": "PHQ-9",
}


# ----------------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------------
def _mezclar(base: dict, extra: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _mezclar(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def cargar_config(ruta: str | Path | None = None) -> dict:
    with open(ruta or CONFIG_DEFECTO, encoding="utf-8") as f:
        return yaml.safe_load(f)


def config_para(cfg: dict, especialidad: str) -> dict:
    """Config general + ajustes de la especialidad (si existen)."""
    extra = (cfg.get("especialidades") or {}).get(especialidad)
    return _mezclar(cfg, extra) if extra else cfg


# ----------------------------------------------------------------------------
# Datos
# ----------------------------------------------------------------------------
def _texto(x) -> str:
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x)


def _a_fecha(x) -> date | None:
    if x is None or (isinstance(x, float) and pd.isna(x)) or x == "":
        return None
    return pd.Timestamp(x).date()


@dataclass
class Paciente:
    id_paciente: str
    especialidad: str
    sub_especialidad: str
    diagnostico: str
    prioridad_inicial: str
    fecha_ingreso: date
    estado: str
    origen: str
    edad: int
    sexo: str
    comuna: str
    prevision: str
    nivel_socioeconomico: str
    fecha_defuncion: date | None
    eventos: list = field(default_factory=list)      # dicts ordenados por fecha
    mediciones: list = field(default_factory=list)   # dicts ordenados por fecha
    citas: list = field(default_factory=list)        # dicts ordenados por fecha
    indicacion: dict | None = None                    # última indicación de control leída del texto libre
    # --- de otras fuentes (motor/fuentes.py); todo opcional
    sin_priorizar: bool = False                       # la interconsulta llegó sin prioridad del especialista
    propuesta: dict | None = None                     # prioridad propuesta por la guía (motor/guias.py)
    texto_interconsulta: str = ""                     # lo que escribió quien derivó
    acg: list = field(default_factory=list)           # estratificación de riesgo APS: [{"fecha", "estrato"}] (G0..G3)
    comorbilidades: list = field(default_factory=list)  # crónicos de APS (reporte de Rayen): [{"fecha", "cie10"}]


class Datos:
    """Todos los pacientes indexados por id, listos para puntuar rápido."""

    def __init__(self, pacientes: dict[str, Paciente], agenda: pd.DataFrame | None = None):
        self.pacientes = pacientes
        self.agenda = agenda
        self.fuentes: dict = {}          # resumen de las otras fuentes incorporadas (motor/fuentes.py)

    @classmethod
    def cargar(cls, carpeta: str | Path | None = None) -> "Datos":
        """Carga una carpeta de CSV. Sin carpeta usa la variable de entorno HLF_DATOS (o DATA_DIR en Lambda) y,
        si no hay, el dataset del desafío."""
        import os
        d = Path(carpeta or os.environ.get("HLF_DATOS") or os.environ.get("DATA_DIR") or DATOS_DEFECTO)
        pa = pd.read_csv(d / "pacientes.csv")
        le = pd.read_csv(d / "lista_espera.csv")
        ev = pd.read_csv(d / "eventos_clinicos.csv")
        me = pd.read_csv(d / "mediciones.csv")
        ci = pd.read_csv(d / "citaciones.csv")
        ag = pd.read_csv(d / "agenda_box.csv") if (d / "agenda_box.csv").exists() else None

        base = le.merge(pa, on="id_paciente", how="left")
        pacientes: dict[str, Paciente] = {}
        for r in base.itertuples(index=False):
            sin_prio = str(r.prioridad_inicial).strip().lower() not in ORDEN_PRIORIDAD
            pacientes[r.id_paciente] = Paciente(
                id_paciente=r.id_paciente,
                especialidad=r.especialidad,
                sub_especialidad=r.sub_especialidad,
                diagnostico=f"{r.diagnostico_cie10} {r.diagnostico_texto}",
                # sin prioridad del especialista: se guarda la provisoria; la regla decide con prioridad_de_partida
                prioridad_inicial="media" if sin_prio else str(r.prioridad_inicial).strip().lower(),
                sin_priorizar=sin_prio,
                texto_interconsulta=_texto(getattr(r, "texto_interconsulta", "")),
                fecha_ingreso=_a_fecha(r.fecha_ingreso_lista),
                estado=r.estado,
                origen=r.origen_derivacion,
                edad=int(r.edad),
                sexo=r.sexo,
                comuna=r.comuna,
                prevision=r.prevision,
                nivel_socioeconomico=r.nivel_socioeconomico,
                fecha_defuncion=_a_fecha(r.fecha_defuncion) if str(r.fallecido).lower() == "true" else None,
            )

        for r in ev.to_dict("records"):
            p = pacientes.get(r["id_paciente"])
            if p:
                r["fecha"] = _a_fecha(r["fecha_evento"])
                p.eventos.append(r)
        for r in me.to_dict("records"):
            p = pacientes.get(r["id_paciente"])
            if p:
                r["fecha"] = _a_fecha(r["fecha_medicion"])
                r["fuera_de_rango"] = str(r["fuera_de_rango"]).lower() == "true"
                p.mediciones.append(r)
        for r in ci.to_dict("records"):
            p = pacientes.get(r["id_paciente"])
            if p:
                r["fecha"] = _a_fecha(r["fecha_cita"])
                r["fecha_agendamiento"] = _a_fecha(r.get("fecha_agendamiento"))   # opcional: cuándo se agendó
                p.citas.append(r)
        for p in pacientes.values():
            p.eventos.sort(key=lambda x: x["fecha"])
            p.mediciones.sort(key=lambda x: x["fecha"])
            p.citas.sort(key=lambda x: x["fecha"])
        # Opcional: indicaciones de control en texto libre (id_paciente, fecha_indicacion, texto).
        # No viene en el dataset del desafío; si el hospital la entrega, se lee con reglas al cargar.
        if (d / "indicaciones.csv").exists():
            from .indicaciones import desde_fila
            for r in pd.read_csv(d / "indicaciones.csv").sort_values("fecha_indicacion").to_dict("records"):
                p = pacientes.get(r["id_paciente"])
                if p:
                    p.indicacion = {**desde_fila(r), "fecha": _a_fecha(r["fecha_indicacion"]),
                                    "texto": str(r.get("texto") or "")}
        datos = cls(pacientes, ag)
        # Otras fuentes (Tálamo hospitalización/urgencia, ACG, Rayen, interconsultas sin priorizar), si existen.
        # Carpeta: HLF_FUENTES, o `fuentes/` dentro de la carpeta de datos, o data/fuentes_sinteticas con el
        # dataset del desafío. HLF_FUENTES=no las apaga.
        from .fuentes import carpeta_fuentes, enriquecer
        cf = carpeta_fuentes(d)
        if cf is not None:
            enriquecer(datos, cf)
        from .guias import proponer_todas
        proponer_todas(datos)
        return datos

    def con_indicacion(self, id_paciente: str, indicacion: dict, fecha) -> "Datos":
        """Copia de los datos con una indicación de control leída (salida de motor.indicaciones.extraer)."""
        nuevo = copy.copy(self)
        nuevo.pacientes = dict(self.pacientes)
        p = copy.copy(self.pacientes[id_paciente])
        p.indicacion = {**indicacion, "fecha": _a_fecha(fecha)}
        nuevo.pacientes[id_paciente] = p
        return nuevo

    def fecha_referencia(self) -> date:
        """'Hoy' para los datos: la fecha más reciente con información (ingresos, eventos, mediciones, citas,
        agenda), sin pasar de hoy. Se puede fijar con la variable de entorno HLF_HOY (AAAA-MM-DD)."""
        import os
        if os.environ.get("HLF_HOY"):
            return _a_fecha(os.environ["HLF_HOY"])
        if getattr(self, "_fecha_ref", None):
            return self._fecha_ref
        fechas = [p.fecha_ingreso for p in self.pacientes.values()]
        for p in self.pacientes.values():
            fechas += [x["fecha"] for x in p.eventos + p.mediciones + p.citas]
        if self.agenda is not None and len(self.agenda):
            fechas.append(_a_fecha(self.agenda["fecha"].max()))
        self._fecha_ref = min(max(fechas), date.today())
        return self._fecha_ref

    def fecha_inicial(self) -> date:
        return min(p.fecha_ingreso for p in self.pacientes.values())

    def con_cita(self, id_paciente: str, fecha_cita, fecha_agendamiento=None) -> "Datos":
        """Copia de los datos con una hora agendada (el paciente sale del orden hasta su cita)."""
        nuevo = copy.copy(self)
        nuevo.pacientes = dict(self.pacientes)
        p = copy.copy(self.pacientes[id_paciente])
        c = {"id_paciente": id_paciente, "id_cita": "CT-NUEVA", "fecha_cita": str(fecha_cita),
             "fecha": _a_fecha(fecha_cita), "fecha_agendamiento": _a_fecha(fecha_agendamiento),
             "especialidad": p.especialidad, "estado_cita": "agendada", "minutos_atencion_real": None}
        p.citas = sorted(p.citas + [c], key=lambda x: x["fecha"])
        nuevo.pacientes[id_paciente] = p
        return nuevo

    def con_evento(self, id_paciente: str, evento: dict) -> "Datos":
        """Copia de los datos con un evento nuevo agregado (para la demo y el recálculo
        disparado por evento). `evento` necesita: fecha_evento, tipo_evento, subtipo,
        severidad; `detalle` y `dias_estadia` son opcionales."""
        nuevo = copy.copy(self)
        nuevo.pacientes = dict(self.pacientes)
        p = copy.copy(self.pacientes[id_paciente])
        e = dict(evento)
        e.setdefault("id_paciente", id_paciente)
        e.setdefault("id_evento", "EV-NUEVO")
        e.setdefault("detalle", f"{e['subtipo']} ({p.especialidad})")
        e["fecha"] = _a_fecha(e["fecha_evento"])
        p.eventos = sorted(p.eventos + [e], key=lambda x: x["fecha"])
        nuevo.pacientes[id_paciente] = p
        return nuevo


# ----------------------------------------------------------------------------
# Puntaje
# ----------------------------------------------------------------------------
def estado_en_lista(p: Paciente, corte: date) -> tuple[bool, str | None]:
    """¿Está el paciente esperando a la fecha de corte? Devuelve (en_lista, motivo_fuera)."""
    if p.fecha_ingreso > corte:
        return False, "aun_no_ingresa"
    if p.fecha_defuncion and p.fecha_defuncion <= corte:
        return False, "fallecido"
    if p.estado == "atendido":
        asistio = [c["fecha"] for c in p.citas if c["estado_cita"] == "asistio" and c["fecha"] <= corte]
        if asistio:
            return False, "atendido"
    # Reunión 7: quien ya tiene hora agendada sale del orden (sale formalmente de la lista cuando la cita se hace).
    # Si no asiste, la cita pasa a no_asistio y vuelve a la lista.
    for c in p.citas:
        if c["estado_cita"] == "agendada" and c["fecha"] >= corte and (
                c.get("fecha_agendamiento") is None or c["fecha_agendamiento"] <= corte):
            return False, "agendado"
    return True, None


def _componente_espera(p: Paciente, corte: date, cfg: dict) -> tuple[float, int]:
    dias = (corte - p.fecha_ingreso).days
    tasa = cfg["espera"]["puntos_por_semana"][p.prioridad_inicial]
    return min(cfg["espera"]["tope"], tasa * dias / 7.0), dias


def _componente_eventos(p: Paciente, corte: date, cfg: dict) -> tuple[float, list]:
    ce = cfg["eventos"]
    vida, vent = ce["vida_media_dias"], ce["ventana_max_dias"]
    items, total = [], 0.0
    for e in p.eventos:
        if e["fecha"] > corte:
            break
        dias = (corte - e["fecha"]).days
        if dias > vent:
            continue
        pts_base = float(ce["puntos_por_subtipo"].get(e["subtipo"], 0))
        estadia = e.get("dias_estadia")
        if estadia is not None and not (isinstance(estadia, float) and pd.isna(estadia)):
            pts_base += ce["puntos_por_dia_hospitalizado"] * min(float(estadia), ce["tope_dias_hospitalizado"])
        if pts_base == 0:
            continue
        pts = pts_base * 0.5 ** (dias / vida)
        total += pts
        detalle = ETIQUETAS_SUBTIPO.get(e["subtipo"], e["subtipo"])
        if estadia is not None and not (isinstance(estadia, float) and pd.isna(estadia)):
            detalle += f" ({int(estadia)} días)"
        items.append({"componente": "evento", "detalle": detalle, "fecha": e["fecha"],
                      "puntos": pts, "severidad": e["severidad"], "hace_dias": dias})
    total = max(total, ce["piso_total"])
    return total, items


def _componente_mediciones(p: Paciente, corte: date, cfg: dict) -> tuple[float, list]:
    cm = cfg["mediciones"]
    por_tipo: dict[str, list] = {}
    for m in p.mediciones:
        if m["fecha"] > corte:
            break
        if (corte - m["fecha"]).days <= cm["ventana_dias"]:
            por_tipo.setdefault(m["tipo_medicion"], []).append(m)
    items, total = [], 0.0
    for tipo, serie in por_tipo.items():
        ult = serie[-1]
        etiqueta = ETIQUETAS_MEDICION.get(tipo, tipo)
        if ult["fuera_de_rango"]:
            total += cm["fuera_de_rango"]
            items.append({"componente": "medicion", "fecha": ult["fecha"], "puntos": float(cm["fuera_de_rango"]),
                          "detalle": f"{etiqueta} fuera de rango ({ult['valor']:g} {ult['unidad']})"})
        reglas = cm["tipos"].get(tipo)
        if reglas and len(serie) >= 2:
            ult3 = serie[-3:]
            delta = ult3[-1]["valor"] - ult3[0]["valor"]
            if reglas["empeora_si"] == "baja":
                delta = -delta
            if delta >= reglas["umbral"]:
                total += cm["tendencia_empeora"]
                items.append({"componente": "medicion", "fecha": ult["fecha"], "puntos": float(cm["tendencia_empeora"]),
                              "detalle": f"{etiqueta} empeorando ({ult3[0]['valor']:g} → {ult3[-1]['valor']:g})"})
            elif delta <= -reglas["umbral"]:
                total += cm["tendencia_mejora"]
                items.append({"componente": "medicion", "fecha": ult["fecha"], "puntos": float(cm["tendencia_mejora"]),
                              "detalle": f"{etiqueta} mejorando ({ult3[0]['valor']:g} → {ult3[-1]['valor']:g})"})
    total = max(min(total, cm["tope_total"]), cm["piso_total"])
    return total, items


def _bandera(p: Paciente, corte: date, cfg: dict) -> tuple[bool, str | None]:
    cb = cfg["bandera_revision"]
    for e in reversed(p.eventos):
        if e["fecha"] > corte:
            continue
        dias = (corte - e["fecha"]).days
        if dias > cb["ventana_dias"]:
            break
        if e["severidad"] in cb["severidades"]:
            cuando = "hoy" if dias == 0 else "ayer" if dias == 1 else f"hace {dias} días"
            return True, f"{ETIQUETAS_SUBTIPO.get(e['subtipo'], e['subtipo'])} {cuando}"
    return False, None


def _alerta_contacto(p: Paciente, corte: date, cfg: dict) -> str | None:
    ca = cfg["alerta_contacto"]
    n = sum(1 for c in p.citas if c["estado_cita"] == "no_asistio" and c["fecha"] <= corte)
    if n >= ca["inasistencias_para_llamada"]:
        return f"{n} inasistencias: llamar y confirmar asistencia antes de citar"
    if n >= ca["inasistencias_para_alerta"]:
        return f"{n} inasistencia: confirmar datos de contacto"
    return None


def puntuar_paciente(p: Paciente, corte: date, cfg: dict) -> dict:
    """Puntaje de un paciente usando SOLO información con fecha <= corte."""
    if isinstance(corte, str):
        corte = _a_fecha(corte)
    c = config_para(cfg, p.especialidad)
    en_lista, motivo = estado_en_lista(p, corte)

    base = float(c["base_prioridad"][p.prioridad_inicial])
    espera, dias = _componente_espera(p, corte, c) if p.fecha_ingreso <= corte else (0.0, 0)
    eventos, it_ev = _componente_eventos(p, corte, c)
    medic, it_me = _componente_mediciones(p, corte, c)
    bandera, motivo_bandera = _bandera(p, corte, c)

    boleta = [
        {"componente": "base", "detalle": f"Prioridad médica inicial: {p.prioridad_inicial}",
         "fecha": p.fecha_ingreso, "puntos": base},
        {"componente": "espera", "detalle": f"{dias} días en lista", "fecha": p.fecha_ingreso, "puntos": espera},
    ] + it_ev + it_me
    for b in boleta:
        b["puntos"] = round(b["puntos"], 1)

    total = base + espera + eventos + medic
    razones = sorted([b for b in boleta if b["componente"] not in ("base",) and b["puntos"] > 0],
                     key=lambda b: -b["puntos"])[:3]
    return {
        "id_paciente": p.id_paciente,
        "especialidad": p.especialidad,
        "prioridad_inicial": p.prioridad_inicial,
        "fecha_ingreso": p.fecha_ingreso,
        "dias_espera": dias,
        "en_lista": en_lista,
        "motivo_fuera": motivo,
        "puntaje": round(total, 1),
        "base": round(base, 1),
        "espera": round(espera, 1),
        "eventos": round(eventos, 1),
        "mediciones": round(medic, 1),
        "clinico": round(eventos + medic, 1),
        "bandera_revision": bandera,
        "motivo_bandera": motivo_bandera,
        "alerta_contacto": _alerta_contacto(p, corte, c),
        "boleta": boleta,
        "top_razones": [f"{r['detalle']}: +{r['puntos']:g}" for r in razones],
        "corte": corte,
        "version_pesos": c.get("version"),
    }


def puntuar_lista(datos: Datos, corte, cfg: dict, especialidad: str | None = None,
                  solo_en_lista: bool = True) -> pd.DataFrame:
    """Lista de trabajo a una fecha de corte, ordenada por puntaje (mayor primero)."""
    if isinstance(corte, str):
        corte = _a_fecha(corte)
    filas = []
    for p in datos.pacientes.values():
        if especialidad and p.especialidad != especialidad:
            continue
        r = puntuar_paciente(p, corte, cfg)
        if solo_en_lista and not r["en_lista"]:
            continue
        filas.append(r)
    df = pd.DataFrame(filas)
    if df.empty:
        return df
    df = df.sort_values(["puntaje", "fecha_ingreso"], ascending=[False, True]).reset_index(drop=True)
    df["puesto"] = df.index + 1
    df["puesto_especialidad"] = df.groupby("especialidad").cumcount() + 1
    return df


def puesto_regla_actual(df: pd.DataFrame) -> pd.Series:
    """Puesto que tendría cada paciente con la regla actual del hospital:
    alta -> media -> baja y, dentro de cada una, el más antiguo primero."""
    orden = df.assign(_p=df["prioridad_inicial"].map(ORDEN_PRIORIDAD)).sort_values(["_p", "fecha_ingreso"])
    return pd.Series(range(1, len(orden) + 1), index=orden.index).reindex(df.index)


def iterar_cortes(inicio, fin, paso_dias: int = 1) -> Iterable[date]:
    d, f = _a_fecha(inicio), _a_fecha(fin)
    while d <= f:
        yield d
        d = date.fromordinal(d.toordinal() + paso_dias)
