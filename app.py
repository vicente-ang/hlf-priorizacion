"""Interfaz para el equipo de gestión de la demanda — Lista de espera dinámica HLF.

Correr:  streamlit run app.py
Usa el mismo motor que la simulación y la Lambda (motor.priorizar).

Ciclo semanal (entrevista 6): la lista oficial se reprioriza un día fijo (lunes) y con ella se agenda toda la
semana. Lo que llega después del corte (eventos, indicaciones) aparece como ALERTA con el puesto que tendría; no
mueve la lista sola. El jefe de especialidad o la gestora pueden adelantar a alguien con un motivo.
"""
from __future__ import annotations

import csv
import hmac
import json
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from motor import Datos, auditar, cargar_regla, priorizar  # noqa: E402
from motor.explicar import explicacion_plantilla, explicar_con_bedrock, hechos  # noqa: E402
from motor.agenda import llamadas_del_dia, proponer_agenda  # noqa: E402
from motor.exportar import a_csv, agenda_para_exportar, lista_para_exportar, llamadas_para_exportar  # noqa: E402
from motor.cambios import cambios, resumen_para_equipo, resumen_plantilla  # noqa: E402
from motor.clusters import clusters, texto_clusters  # noqa: E402
from motor.cortes import (TIPOS_ALERTA, aplicar_adelantos, corte_vigente, cortes_anteriores, fecha_larga,  # noqa: E402
                          quitar_agendados,
                          frase_cambio, historial_desde_listas, proximo_corte)
from motor.fuentes import resumen_fuentes  # noqa: E402
from motor.gestion import grupo_extremo, percentiles, sugerencias  # noqa: E402
from motor.guias import proponer, texto_propuesta  # noqa: E402
from motor.indicaciones import evaluar_ejemplos, extraer  # noqa: E402
from motor.puntaje import ETIQUETAS_MEDICION, ETIQUETAS_SUBTIPO  # noqa: E402

REGISTRO = Path(os.environ.get("HLF_REGISTRO", RAIZ / "salidas" / "registro_decisiones.csv"))
CAMPOS_REGISTRO = ["fecha_registro", "usuario", "rol", "fecha_lista", "especialidad", "id_paciente",
                   "puesto_propuesto", "motivo_propuesto", "decision", "puesto_final", "motivo", "modo",
                   "version_regla"]
RESULTADOS = RAIZ / "sim" / "resultados"
MODOS = {"Regla MVP (carril rápido + plazo)": "carril_plazo", "Regla actual del hospital": "actual",
         "Puntaje v1 (pesos a mano)": "puntaje"}
EVENTOS = {"Hospitalización": ("hospitalizacion", "ingreso hospitalario", "grave"),
           "Ingreso a UCI": ("hospitalizacion", "ingreso UCI", "grave"),
           "Urgencia (triage ESI 2)": ("visita_urgencia", "triage ESI 2", "grave"),
           "Urgencia por descompensación": ("visita_urgencia", "descompensación", "moderada"),
           "Examen alterado": ("examen_alterado", "resultado alterado", "moderada"),
           "Aumento de dosis": ("cambio_farmaco", "aumento dosis", "moderada"),
           # Reunión 7: un evento que no tiene que ver con la derivación se registra, pero no mueve a nadie
           "Urgencia por cólico renal (otro motivo)": ("visita_urgencia", "triage ESI 2", "grave",
                                                       {"diagnostico_cie10": "N20.0", "diagnostico_texto": "cólico renal"})}
ROLES = {"Gestora de demanda": "gestora de demanda", "Jefe de especialidad": "jefe de especialidad"}
COLOR = {"rojo": "#C2362B", "ambar": "#9A6212", "verde": "#0F6E6A", "pizarra": "#5B6B76", "tinta": "#1E2A32"}

st.set_page_config(page_title="Lista de espera dinámica HLF", layout="wide")
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame, button, input, textarea, select {
  font-family: 'Atkinson Hyperlegible', system-ui, sans-serif !important; }
h1 { font-weight: 700; letter-spacing: -0.01em; font-size: 2rem !important; margin-bottom: 0.2rem; }
h2, h3 { font-weight: 700; }
.estado { font-size: 1.05rem; color: #1E2A32; max-width: 75ch; }
.estado b.rojo { color: #C2362B; } .estado b.ambar { color: #9A6212; }
.ficha { border-left: 4px solid #0F6E6A; padding: 0.4rem 0 0.4rem 1rem; margin: 0.5rem 0 1rem; max-width: 80ch; }
.ficha.carril { border-left-color: #C2362B; }
.ficha.alerta { border-left-color: #9A6212; }
.nota { color: #5B6B76; font-size: 0.92rem; max-width: 80ch; }
.corte { background: #E9EFF1; padding: 0.5rem 0.8rem; border-radius: 6px; font-size: 0.92rem; }
</style>""", unsafe_allow_html=True)


# ----------------------------------------------------------------------------- acceso
# Si se define la variable HLF_CLAVE (en App Runner, como secreto), la interfaz pide clave.
_CLAVE = os.environ.get("HLF_CLAVE")
if _CLAVE and not st.session_state.get("autenticado"):
    st.title("Lista de espera dinámica HLF")
    st.markdown("<p class='nota'>Acceso para el equipo de gestión de la demanda.</p>", unsafe_allow_html=True)
    clave = st.text_input("Clave de acceso", type="password")
    if st.button("Entrar", type="primary"):
        if hmac.compare_digest(clave.encode(), _CLAVE.encode()):
            st.session_state.autenticado = True
            st.rerun()
        st.error("La clave no es correcta. Pídela al administrador del sistema.")
    st.stop()


# ----------------------------------------------------------------------------- estado
@st.cache_resource
def _cargar(ruta: str | None, fuentes: str | None):
    return Datos.cargar(ruta)


def _datos_base() -> Datos:
    """Datos de la carpeta de HLF_DATOS (o el dataset del desafío). La caché depende de la carpeta."""
    return _cargar(os.environ.get("HLF_DATOS"), os.environ.get("HLF_FUENTES"))


@st.cache_resource
def _cfg():
    return cargar_regla()


for _k, _v in {"eventos_demo": [], "antes_evento": None, "indicaciones_demo": [], "lectura": None,
               "adelantos": [], "agendados": {}, "decisiones_ia": {}, "historial_ia": [], "aviso_ia": None}.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


def datos_actuales() -> Datos:
    """Los datos base más lo que llegó en esta sesión (eventos e indicaciones de la demo)."""
    d = _datos_base()
    for pid, ev in st.session_state.eventos_demo:
        d = d.con_evento(pid, ev)
    for pid, ind, fecha in st.session_state.indicaciones_demo:
        d = d.con_indicacion(pid, ind, fecha)
    return d


@st.cache_data
def _evaluacion_indicaciones():
    return evaluar_ejemplos(usar_bedrock=False)


def guardar_decision(fila: dict):
    REGISTRO.parent.mkdir(exist_ok=True)
    nuevo = not REGISTRO.exists()
    with open(REGISTRO, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_REGISTRO, extrasaction="ignore")
        if nuevo:
            w.writeheader()
        w.writerow({k: fila.get(k, "") for k in CAMPOS_REGISTRO})


def _num(x: float, dec: int = 1) -> str:
    """Número con coma decimal (es-CL)."""
    return f"{x:.{dec}f}".replace(".", ",")


def _cambio(n) -> str:
    if n is None or pd.isna(n):
        return "nuevo"
    n = int(n)
    return f"▲ {n}" if n > 0 else f"▼ {-n}" if n < 0 else "="


def _prioridad(r) -> str:
    """'media → alta' (T1 → T2); marca si la prioridad de partida no es del especialista."""
    t1 = r["prioridad_inicial"]
    origen = r.get("prioridad_origen") or "especialista"
    if origen.startswith("propuesta"):
        t1 += " (guía)"
    elif origen.startswith("provisoria"):
        t1 += " (sin priorizar)"
    t2 = r.get("prioridad_dinamica")
    return t1 if not t2 or t2 == r["prioridad_inicial"] else f"{t1} → {t2}"


# ----------------------------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("Filtros")
    HOY = _datos_base().fecha_referencia()
    cfg = _cfg()
    hoy = st.date_input("Hoy", value=HOY, min_value=_datos_base().fecha_inicial(), max_value=HOY,
                        format="DD-MM-YYYY", help="Día de trabajo. La lista vigente es la del último corte.")
    corte = corte_vigente(hoy, cfg)
    prox = proximo_corte(hoy, cfg)
    st.markdown(f"<div class='corte'>Lista vigente: <b>corte del {fecha_larga(corte)}</b>.<br>Próximo corte: "
                f"{fecha_larga(prox)}.</div>", unsafe_allow_html=True)
    base = _datos_base()
    datos = datos_actuales()
    especialidades = sorted({p.especialidad for p in base.pacientes.values()})
    especialidad = st.selectbox("Especialidad", especialidades,
                                index=especialidades.index("Traumatología") if "Traumatología" in especialidades else 0)
    modo_nombre = st.radio("Cómo ordenar", list(MODOS), index=0)
    modo = MODOS[modo_nombre]
    perfil = st.radio("Perfil", list(ROLES), index=0, help="La gestora agenda; el jefe de especialidad revisa el "
                      "orden y puede pedir que vean antes a alguien. El médico de la consulta no ve la lista.")
    rol = ROLES[perfil]
    usuario = st.text_input("Tu nombre (para el registro)", value="Gestora HLF" if rol.startswith("gestora")
                            else "Jefe de especialidad")
    if base.fuentes:
        with st.expander("Fuentes cargadas"):
            st.markdown("<p class='nota'>Tálamo (lista, eventos, mediciones, citas) más:</p>", unsafe_allow_html=True)
            for linea in resumen_fuentes(base.fuentes):
                st.markdown(f"- {linea}")
            st.caption("Fuentes sintéticas para la demo (data/fuentes_sinteticas).")
    n_demo = (len(st.session_state.eventos_demo) + len(st.session_state.indicaciones_demo)
              + len(st.session_state.adelantos) + len(st.session_state.agendados) + len(st.session_state.decisiones_ia))
    if n_demo:
        st.caption(f"{n_demo} cambio(s) de demo en esta sesión (eventos, indicaciones, adelantos, agendados o decisiones sobre la IA).")
        if st.button("Quitar cambios de la demo"):
            for _k in ("eventos_demo", "indicaciones_demo", "adelantos", "historial_ia"):
                st.session_state[_k] = []
            st.session_state.agendados, st.session_state.decisiones_ia = {}, {}
            st.session_state.antes_evento, st.session_state.lectura = None, None
            st.rerun()


def _firma() -> str:
    """Identifica los datos en uso: carpeta + eventos e indicaciones agregados en la demo."""
    return repr((os.environ.get("HLF_DATOS"), st.session_state.eventos_demo,
                 [(p, i.get("texto"), i.get("plazo_dias"), i.get("continua_control"), f)
                  for p, i, f in st.session_state.indicaciones_demo]))


FIRMA_BASE = repr((os.environ.get("HLF_DATOS"), os.environ.get("HLF_FUENTES")))
FIRMA = _firma()


@st.cache_data(max_entries=64, show_spinner=False)
def _priorizar_c(firma, fecha, modo, especialidad, _datos, _cfg):
    return priorizar(_datos, fecha, _cfg, modo=modo, especialidad=especialidad)


@st.cache_data(max_entries=24, show_spinner=False)
def _cambios_c(firma, desde, hasta, modo, especialidad, _antes, _despues, _cfg):
    return cambios(_antes, _despues, desde, hasta, _cfg, modo=modo, especialidad=especialidad)


@st.cache_data(max_entries=24, show_spinner=False)
def _agenda_c(firma, dia, modo, especialidad, _datos, _cfg, _lista):
    return proponer_agenda(_datos, dia, _cfg, especialidad=especialidad, lista=_lista)


@st.cache_data(max_entries=24, show_spinner=False)
def _auditar_c(firma, corte, modo, _lista_total, _datos):
    return auditar(_lista_total, _datos)


_t0 = time.perf_counter()
lista_corte = _priorizar_c(FIRMA_BASE, corte, modo, None, base, cfg)          # la lista vigente (foto del corte)
ms_recalculo = (time.perf_counter() - _t0) * 1000
# Quien ya tiene hora agendada sale del orden (reunión 7); los adelantos con motivo suben al principio
lista_total = aplicar_adelantos(quitar_agendados(lista_corte, st.session_state.agendados), st.session_state.adelantos)
lista = lista_total[lista_total.especialidad == especialidad].reset_index(drop=True) if len(lista_total) else lista_total
anterior = _priorizar_c(FIRMA_BASE, corte - timedelta(days=7), modo, especialidad, base, cfg)
PUESTO_ANTERIOR = dict(zip(anterior.id_paciente, anterior.puesto)) if len(anterior) else {}
hay_novedades = hoy > corte or bool(st.session_state.eventos_demo or st.session_state.indicaciones_demo)
# Lo que llegó desde el corte (reportes diarios y cambios de la demo), con el puesto que tendría
alertas, res_alertas = (_cambios_c(FIRMA, corte, hoy, modo, especialidad, base, datos, cfg) if hay_novedades
                        else (pd.DataFrame(), {}))
if len(alertas):
    alertas = alertas[alertas.tipo.isin(TIPOS_ALERTA)].reset_index(drop=True)
proyeccion = _priorizar_c(FIRMA, hoy, modo, especialidad, datos, cfg) if hay_novedades else lista
ADELANTADOS = {a["id_paciente"] for a in st.session_state.adelantos}
CON_ALERTA = set(alertas.id_paciente) if len(alertas) else set()
ETIQ = {pid: f"#{p} · {pid}" for pid, p in zip(lista.id_paciente, lista.puesto)} if len(lista) else {}
ETIQ_PRIO = ({pid: f"#{p} · {pid} ({pr})" for pid, p, pr in zip(lista.id_paciente, lista.puesto, lista.prioridad_inicial)}
             if len(lista) else {})


def _fila(df: pd.DataFrame, pid: str) -> dict | None:
    f = df[df.id_paciente == pid] if len(df) else df
    return f.iloc[0].to_dict() if len(f) else None


def adelantar(pid: str, motivo: str, puesto: int):
    st.session_state.adelantos.append({"id_paciente": pid, "motivo": motivo.strip(), "usuario": usuario, "rol": rol})
    guardar_decision({"fecha_registro": datetime.now().isoformat(timespec="seconds"), "usuario": usuario, "rol": rol,
                      "fecha_lista": corte.isoformat(), "especialidad": especialidad, "id_paciente": pid,
                      "puesto_propuesto": puesto, "motivo_propuesto": "lista vigente", "decision": "adelantado",
                      "puesto_final": 1, "motivo": motivo.strip(), "modo": modo, "version_regla": cfg.get("version")})


# ----------------------------------------------------------------------------- encabezado
st.title(f"{especialidad}: a quién citar primero")
n_carril = int(lista.carril_rapido.sum()) if len(lista) else 0
n_verif = int(lista.verificar_estado.notna().sum()) if len(lista) else 0
n_sinprio = int((lista.prioridad_origen != "especialista").sum()) if len(lista) else 0
n_alertas = len(alertas)
st.markdown(
    f"<p class='estado'>{len(lista)} personas en la lista vigente. <b class='rojo'>{n_carril} en carril rápido</b> por "
    f"un evento grave reciente, <b class='ambar'>{n_alertas} {'alerta' if n_alertas == 1 else 'alertas'} desde el corte</b>, {n_verif} sin datos "
    f"recientes que conviene llamar y {n_sinprio} interconsultas sin priorizar. "
    "La herramienta propone el orden; el equipo decide.</p>", unsafe_allow_html=True)

(tab_lista, tab_ia, tab_alertas, tab_cambios, tab_sinprio, tab_gestion, tab_indic, tab_impacto, tab_equidad, tab_kpi,
 tab_registro, tab_agenda) = st.tabs(["Lista vigente", "Agente IA", "Alertas del día", "Qué cambió en el corte",
                                      "Sin priorizar", "Gestión (P90)", "Indicaciones", "Impacto", "Equidad",
                                      "Indicadores", "Decisiones", "Agenda y llamadas"])

# ----------------------------------------------------------------------------- lista vigente
with tab_lista:
    if lista.empty:
        st.info("No hay pacientes esperando en esta especialidad a esa fecha. Prueba con otra fecha o especialidad.")
    else:
        vista = pd.DataFrame({
            "Puesto": lista.puesto,
            "Vs. corte anterior": [_cambio(PUESTO_ANTERIOR[i] - p) if i in PUESTO_ANTERIOR else "nuevo"
                                        for i, p in zip(lista.id_paciente, lista.puesto)],
            "Paciente": lista.id_paciente,
            "Prioridad": [_prioridad(r) for r in lista.to_dict("records")],
            "Días en lista": lista.dias_espera,
            "Por qué está aquí": lista.motivo_puesto.str.capitalize(),
            "Atraso": lista.dias_atraso.clip(lower=0),
            "Avisos": [", ".join(x for x in (("alerta desde el corte" if i in CON_ALERTA else None),
                                             ("llamar: sin datos" if pd.notna(v) else None),
                                             ("inasistencias" if pd.notna(c) else None)) if x)
                       for i, v, c in zip(lista.id_paciente, lista.verificar_estado, lista.alerta_contacto)],
            "Vs. regla actual": lista.cambio_puestos.map(_cambio),
        })

        def _estilo(col):
            if col.name == "Por qué está aquí":
                return [f"color: {COLOR['rojo']}; font-weight: 700" if v == "Carril rápido" else
                        f"color: {COLOR['ambar']}; font-weight: 700" if v.startswith("Adelantado") else
                        f"color: {COLOR['verde']}" if v == "Cupo por antigüedad" else "" for v in col]
            if col.name in ("Vs. corte anterior", "Vs. regla actual"):
                return [f"color: {COLOR['verde']}" if v.startswith("▲") else
                        f"color: {COLOR['pizarra']}" if v.startswith("▼") else "" for v in col]
            if col.name == "Prioridad":
                return [f"color: {COLOR['rojo']}" if "→ alta" in v else
                        f"color: {COLOR['ambar']}" if "→" in v or "(" in v else "" for v in col]
            if col.name == "Avisos":
                return [f"color: {COLOR['ambar']}" if v else "" for v in col]
            return [""] * len(col)

        st.dataframe(vista.style.apply(_estilo), hide_index=True, width="stretch", height=420, column_config={
            "Puesto": st.column_config.NumberColumn(width="small"),
            "Vs. corte anterior": st.column_config.TextColumn(width="small", help=(
                f"Puestos que subió (▲) o bajó (▼) desde el corte del {(corte - timedelta(days=7)).strftime('%d-%m')}")),
            "Paciente": st.column_config.TextColumn(width="medium"),
            "Prioridad": st.column_config.TextColumn(width="medium", help=(
                "Prioridad de partida (la del especialista; o la de la guía si nadie la priorizó) → prioridad de hoy, "
                "según lo que le pasó mientras espera")),
            "Días en lista": st.column_config.NumberColumn(width="small"),
            "Por qué está aquí": st.column_config.TextColumn(width="large"),
            "Atraso": st.column_config.NumberColumn(width="small", help="Días que lleva pasado de su plazo vigente"),
            "Avisos": st.column_config.TextColumn(width="medium"),
            "Vs. regla actual": st.column_config.TextColumn(width="small", help=(
                "Cuánto cambia respecto de alta → media → baja por antigüedad"))})
        st.markdown(f"<p class='nota'>Foto del corte del {fecha_larga(corte)}: con ella se agenda hasta el próximo "
                    "corte. Lo que llegó después está en «Alertas del día».</p>", unsafe_allow_html=True)
        _sufijo = f"{corte.isoformat()}_{modo}"
        d1, d2, _ = st.columns([1, 1, 2])
        with d1:
            st.download_button("Descargar esta lista (CSV)", lambda: a_csv(lista_para_exportar(lista)),
                               file_name=f"lista_{especialidad}_{_sufijo}.csv".replace(" ", "_"), mime="text/csv",
                               on_click="ignore", help="Con el motivo, la prioridad de partida y la de hoy. Se abre en Excel.")
        with d2:
            st.download_button("Descargar todas las especialidades", lambda: a_csv(lista_para_exportar(lista_total)),
                               file_name=f"lista_todas_{_sufijo}.csv", mime="text/csv", on_click="ignore")

        ag_esp = {k: v for k, v in st.session_state.agendados.items() if base.pacientes[k].especialidad == especialidad}
        if ag_esp:
            st.markdown(f"**Ya agendados** ({len(ag_esp)}): salen del orden hasta su cita.")
            st.dataframe(pd.DataFrame({"Paciente": list(ag_esp),
                                       "Fecha de la cita": [date.fromisoformat(v).strftime("%d-%m-%Y")
                                                            for v in ag_esp.values()]}),
                         hide_index=True, width="content")

        st.subheader("Detalle del paciente")
        pid = st.selectbox("Paciente", lista.id_paciente.tolist(), format_func=lambda i: ETIQ.get(i, i))
        r = _fila(lista, pid)
        p = base.pacientes[pid]
        clase = "ficha carril" if r["carril_rapido"] else "ficha alerta" if pid in CON_ALERTA else "ficha"
        st.markdown(f"<div class='{clase}'><b>{pid}</b>, {p.edad} años, {p.diagnostico}. "
                    f"Derivado desde {p.origen}.<br>" + "<br>".join(hechos(r)) + "</div>", unsafe_allow_html=True)
        if pid in CON_ALERTA:
            a = alertas[alertas.id_paciente == pid].iloc[0]
            pr = "" if pd.isna(a.puesto_ahora) else f" Si se repriorizara hoy quedaría en el puesto {int(a.puesto_ahora)}."
            st.warning(f"Desde el corte llegó: {a.llego or a.detalle}.{pr} Ver «Alertas del día».")
        if st.button("Redactar explicación con Bedrock"):
            texto, fuente = explicar_con_bedrock(r)
            st.write(texto)
            if fuente != "bedrock":
                st.caption("Bedrock no está configurado en este equipo (BEDROCK_MODEL_ID y AWS_REGION): "
                           "se muestra la explicación de respaldo.")

        # Historial por corte: trazabilidad T1 -> T2 (entrevista 5: "puesto previo 1500 y aumentó por ABC")
        listas_h = {c: _priorizar_c(FIRMA_BASE, c, modo, especialidad, base, cfg) for c in cortes_anteriores(hoy, cfg)}
        hist = historial_desde_listas(listas_h, base, pid)
        st.markdown("**Cómo ha cambiado, corte a corte**")
        frase = frase_cambio(hist)
        if frase:
            st.markdown(frase)
        st.dataframe(pd.DataFrame({
            "Corte": hist.corte.map(lambda f: f.strftime("%d-%m-%Y")),
            "Puesto": hist.puesto.map(lambda x: "—" if pd.isna(x) else str(int(x))),
            "De": hist.de.map(lambda x: "" if pd.isna(x) else str(int(x))),
            "Prioridad ese día": hist.prioridad.fillna(""), "Por qué": hist.por_que.astype(str).str.capitalize(),
            "Lo que llegó desde el corte anterior": hist.llego}).iloc[::-1],
            hide_index=True, width="stretch",
            column_config={"Lo que llegó desde el corte anterior": st.column_config.TextColumn(width="large")})

        # Clusters (entrevista 5): la información agrupada, no el signo vital suelto
        cl = texto_clusters(r["clusters"] if isinstance(r.get("clusters"), dict) else clusters(p, corte, cfg))
        if cl:
            st.markdown("**Clusters de información** (Tálamo, Rayen, ECICEP)")
            st.markdown("\n".join(f"- {x}" for x in cl))

        med = pd.DataFrame([m for m in p.mediciones if m["fecha"] <= corte])
        evs = pd.DataFrame([e for e in p.eventos if e["fecha"] <= corte
                            and e["subtipo"] not in ("control", "control crónico", "control de rutina")])
        if not med.empty or not evs.empty:
            st.markdown("**Lo que le ha pasado mientras espera**")
            regla_ev = None
            if not evs.empty:
                evs = evs.assign(fecha=pd.to_datetime(evs.fecha), evento=evs.subtipo.map(lambda s: ETIQUETAS_SUBTIPO.get(s, s)))
                regla_ev = alt.Chart(evs[["fecha", "evento", "severidad"]]).mark_rule(strokeWidth=2).encode(
                    x=alt.X("fecha:T", axis=alt.Axis(format="%d-%m-%y"), title=None),
                    color=alt.Color("severidad:N", scale=alt.Scale(domain=["leve", "moderada", "grave"],
                                    range=["#8FA3AD", COLOR["ambar"], COLOR["rojo"]]), title="Evento (gravedad)"),
                    tooltip=["evento", "severidad", alt.Tooltip("fecha:T", format="%d-%m-%Y")])
            tipos = sorted(med.tipo_medicion.unique()) if not med.empty else []
            for tipo in tipos or [None]:
                capas = []
                if tipo:
                    m = med[med.tipo_medicion == tipo].assign(fecha=lambda x: pd.to_datetime(x.fecha))
                    base_ch = alt.Chart(m).encode(x=alt.X("fecha:T", title=None, axis=alt.Axis(format="%d-%m-%y")),
                                                  y=alt.Y("valor:Q", title=f"{ETIQUETAS_MEDICION.get(tipo, tipo)} ({m.unidad.iloc[0]})"))
                    capas += [base_ch.mark_line(color=COLOR["tinta"]),
                              base_ch.mark_circle(size=70).encode(
                                  color=alt.condition("datum.fuera_de_rango", alt.value(COLOR["rojo"]), alt.value(COLOR["tinta"])),
                                  tooltip=[alt.Tooltip("fecha:T", format="%d-%m-%Y"), "valor", "fuera_de_rango"])]
                if regla_ev is not None:
                    capas.append(regla_ev)
                st.altair_chart(alt.layer(*capas).properties(height=170), width="stretch")

        if rol.startswith("gestora"):
            st.markdown("**Tu decisión**")
            c1, c2 = st.columns([1, 2])
            with c1:
                decision = st.radio("Decisión", ["Confirmar el puesto propuesto", "Cambiar el puesto"],
                                    label_visibility="collapsed")
                nuevo_puesto = st.number_input("Nuevo puesto", min_value=1, max_value=len(lista), value=int(r["puesto"]),
                                               disabled=decision.startswith("Confirmar"))
            with c2:
                motivo = st.text_area("Motivo (obligatorio si cambias el puesto)", height=90)
            if st.button("Guardar decisión", type="primary"):
                if decision.startswith("Cambiar") and not motivo.strip():
                    st.error("Para cambiar el puesto escribe el motivo: queda en el registro y sirve para mejorar la regla.")
                else:
                    guardar_decision({"fecha_registro": datetime.now().isoformat(timespec="seconds"), "usuario": usuario,
                                      "rol": rol, "fecha_lista": corte.isoformat(), "especialidad": especialidad,
                                      "id_paciente": pid, "puesto_propuesto": int(r["puesto"]),
                                      "motivo_propuesto": r["motivo_puesto"],
                                      "decision": "confirmado" if decision.startswith("Confirmar") else "cambiado",
                                      "puesto_final": int(nuevo_puesto), "motivo": motivo.strip(),
                                      "modo": modo, "version_regla": cfg.get("version")})
                    st.success(f"Decisión guardada para {pid}.")
            st.markdown("**Agendar**")
            st.markdown("<p class='nota'>Con hora agendada, sale del orden (no se le quita el cupo a nadie ni se le "
                        "vuelve a mover). Sale formalmente de la lista cuando la cita se hace; si no llega, vuelve.</p>",
                        unsafe_allow_html=True)
            a1, a2 = st.columns([1, 2])
            with a1:
                fecha_cita = st.date_input("Fecha de la cita", value=hoy + timedelta(days=3), min_value=hoy,
                                           format="DD-MM-YYYY", key="fecha_cita",
                                           help="La norma es agendar al menos 72 horas antes de la hora.")
            with a2:
                st.write("")
                if st.button(f"Agendar a {pid}"):
                    st.session_state.agendados[pid] = fecha_cita.isoformat()
                    guardar_decision({"fecha_registro": datetime.now().isoformat(timespec="seconds"),
                                      "usuario": usuario, "rol": rol, "fecha_lista": corte.isoformat(),
                                      "especialidad": especialidad, "id_paciente": pid,
                                      "puesto_propuesto": int(r["puesto"]), "motivo_propuesto": r["motivo_puesto"],
                                      "decision": "agendado", "motivo": f"cita el {fecha_cita.strftime('%d-%m-%Y')}",
                                      "modo": modo, "version_regla": cfg.get("version")})
                    st.rerun()
        else:
            st.markdown("**Pedir que lo vean antes**")
            st.markdown("<p class='nota'>Por ejemplo: «lo vi ayer en la urgencia, está mal, lo tengo que ver esta "
                        "semana». Sube al principio de la lista vigente y queda en el registro con tu nombre.</p>",
                        unsafe_allow_html=True)
            motivo_j = st.text_area("Motivo (obligatorio)", height=80, key="motivo_jefe")
            if st.button("Pedir que lo vean antes", type="primary"):
                if not motivo_j.strip():
                    st.error("Escribe el motivo: queda en el registro.")
                elif pid in ADELANTADOS:
                    st.info(f"{pid} ya está adelantado.")
                else:
                    adelantar(pid, motivo_j, int(r["puesto"]))
                    st.rerun()

# ----------------------------------------------------------------------------- agente IA (Bedrock)
IA_RES = RAIZ / "ia" / "resultados"


@st.cache_data(show_spinner=False)
def _leer_csv(ruta: str, mtime: float) -> pd.DataFrame:      # mtime en la clave: si el archivo cambia, se relee
    return pd.read_csv(ruta)


ORDEN_CAT = {"alta": 0, "media": 1, "baja": 2}
NOMBRE_MODELO = {"us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5",
                 "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude Sonnet 4.5"}


@st.cache_data(show_spinner=False)
def _revision_ia(ruta: str, mtime: float, firma: str, _prop, _datos, _cfg):
    from ia.decisiones import descartados, revisar_pertinencia
    return revisar_pertinencia(_prop, _datos, _cfg), descartados(_prop, _datos, _cfg)


def _decidir_ia(pid: str, fila: dict, decision: str, motivo: str, puesto_antes: int, puesto_despues: int):
    """Guarda la decisión en la sesión (cambia el orden que se ve) y en el registro (auditoría)."""
    st.session_state.historial_ia.append({"Hora": datetime.now().strftime("%H:%M:%S"), "Paciente": pid,
                                          "Acción": decision.replace("ia_", "").replace("_", " "),
                                          "Motivo": motivo, "Quién": f"{usuario} ({rol})",
                                          "Puesto": f"#{puesto_antes} → #{puesto_despues}"})
    guardar_decision({"fecha_registro": datetime.now().isoformat(timespec="seconds"), "usuario": usuario, "rol": rol,
                      "fecha_lista": corte.isoformat(), "especialidad": especialidad, "id_paciente": pid,
                      "puesto_propuesto": int(fila["puesto_final"]),
                      "motivo_propuesto": f"IA: {fila['categoria_ia']} ({fila['puntaje_ia']})",
                      "decision": decision, "puesto_final": puesto_despues, "motivo": motivo, "modo": "ia",
                      "version_regla": fila.get("version_rubrica", "")})


with tab_ia:
    from ia.decisiones import aplicar as aplicar_decisiones_ia
    st.markdown("<p class='nota'>Un agente en Amazon Bedrock lee la historia de cada paciente (eventos, mediciones y notas "
                "del CESFAM o epicrisis) y propone si subirlo de grupo y un puntaje de riesgo para ordenarlo dentro de su "
                "grupo, citando la evidencia y diciendo qué descartó por no estar relacionado con la derivación. La regla "
                "pone el piso (evento grave relacionado ⇒ alta), la IA puede proponer subir y <b>bajar lo confirma el jefe "
                "de especialidad</b>. Cada decisión se puede revertir y queda registrada.</p>", unsafe_allow_html=True)
    if st.session_state.aviso_ia:
        st.success(st.session_state.aviso_ia)
        st.session_state.aviso_ia = None
    arch_prop = IA_RES / "propuestas_hlf.csv"
    if not arch_prop.exists():
        st.info("Aún no hay propuestas. Correr: python -m ia.agente --datos data/dataset_hlf_ambulatorio --modo bedrock "
                "--salida ia/resultados/propuestas_hlf.csv")
    else:
        prop = _leer_csv(str(arch_prop), arch_prop.stat().st_mtime)
        if (prop.modo == "simulado").all():
            st.warning("Propuestas en modo simulado (reglas y palabras clave, sin Bedrock): sirven para probar el circuito, "
                       "no son la IA. Con Bedrock: definir BEDROCK_MODEL_ID y AWS_REGION y volver a correr el agente.")
        else:
            modelo = prop.modelo.dropna().iloc[0] if "modelo" in prop and prop.modelo.notna().any() else "Bedrock"
            fecha_corte_ia = pd.Timestamp(prop.corte.iloc[0]).strftime("%d-%m-%Y")
            n_err = int(prop.error.notna().sum()) if "error" in prop else 0
            st.caption(f"{NOMBRE_MODELO.get(modelo, modelo)} en Amazon Bedrock (Converse, salida JSON validada) · rúbrica "
                       f"{prop.version_rubrica.iloc[0]} · datos al {fecha_corte_ia} · {len(prop)} pacientes evaluados, "
                       f"{n_err} errores · {int(prop.tokens_entrada.sum()):,} tokens de entrada y "
                       f"{int(prop.tokens_salida.sum()):,} de salida".replace(",", "."))
        revisar, desc = _revision_ia(str(arch_prop), arch_prop.stat().st_mtime, FIRMA_BASE, prop, base, cfg)
        if desc["no_relacionados"]:
            st.caption(f"Pertinencia: de {desc['no_relacionados']} eventos que la regla considera no relacionados con la "
                       f"derivación, la IA declaró como descartados {desc['descartados_por_ia']}.")
        absolutos = [a["id_paciente"] for a in st.session_state.adelantos]
        vista = aplicar_decisiones_ia(prop, st.session_state.decisiones_ia, absolutos)
        pe = vista[vista.especialidad == especialidad].copy()
        if pe.empty:
            st.info("Sin propuestas para esta especialidad.")
        else:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Evaluados", len(pe))
            m2.metric("La IA propone subir de grupo", int(pe.propone_subir.sum()) if "propone_subir" in pe
                      else int((pe.categoria_ia.map(ORDEN_CAT) < pe.prioridad_inicial.map(ORDEN_CAT)).sum()))
            m3.metric("Propone bajar (requiere jefe)", int(pe.propone_bajar.sum()))
            m4.metric("Decisiones en esta sesión", int(pe.estado.ne("pendiente").sum()))
            como = st.radio("Ordenar por", ["Híbrido con decisiones", "Solo IA", "Regla vigente"],
                            horizontal=True, key="orden_ia")
            puesto_regla = dict(zip(lista.id_paciente, lista.puesto)) if len(lista) else {}
            pe["puesto_regla"] = pe.id_paciente.map(puesto_regla)
            col = {"Híbrido con decisiones": "puesto_vista", "Solo IA": "puesto_ia", "Regla vigente": "puesto_regla"}[como]
            pe = pe.sort_values(col, na_position="last")
            st.dataframe(pd.DataFrame({
                "Puesto": pe[col].map(lambda x: "—" if pd.isna(x) else str(int(x))),
                "Paciente": pe.id_paciente,
                "Prioridad T1 → IA": [t if c == t or pd.isna(c) else f"{t} → {c}" for t, c in zip(pe.prioridad_inicial, pe.categoria_ia)],
                "Puntaje IA": pe.puntaje_ia, "Categoría": pe.categoria_vista, "Estado": pe.estado,
                "Confianza": pe.confianza,
                "Puesto en la regla": pe.puesto_regla.map(lambda x: "—" if pd.isna(x) else str(int(x))),
                "Revisar": ["⚠ cita un evento no relacionado" if pid in revisar else "" for pid in pe.id_paciente],
                "Resumen": pe.resumen}), hide_index=True, width="stretch", height=360,
                column_config={"Resumen": st.column_config.TextColumn(width="large")})
            pid_ia = st.selectbox("Paciente", pe.id_paciente.tolist(), key="pid_ia")
            fia = pe[pe.id_paciente == pid_ia].iloc[0].to_dict()
            evid = json.loads(fia["evidencia"]) if isinstance(fia.get("evidencia"), str) and fia["evidencia"] else []
            ign = json.loads(fia["ignorado"]) if isinstance(fia.get("ignorado"), str) and fia["ignorado"] else []
            pr = fia.get("puesto_regla")
            recorrido = (f"Recorrido: regla vigente #{'—' if pd.isna(pr) else int(pr)} → propuesta IA (híbrida) "
                         f"#{int(fia['puesto_final'])} → con las decisiones de hoy #{int(fia['puesto_vista'])}")
            st.markdown(f"<div class='ficha{' carril' if fia['categoria_vista'] == 'alta' else ''}'><b>{pid_ia}</b>: T1 "
                        f"{fia['prioridad_inicial']}, IA {fia['categoria_ia']} (puntaje {fia['puntaje_ia']}, confianza "
                        f"{fia['confianza']}), categoría {fia['categoria_vista']} · estado: {fia['estado']}.<br>"
                        f"{fia['resumen']}<br>"
                        + "".join(f"<br>· {e.get('fecha')} [{e.get('fuente')}]: {e.get('cita')}" for e in evid)
                        + ("<br><br><i>Descartado por no estar relacionado:</i>" + "".join(f"<br>· {x}" for x in ign)
                           if ign else "")
                        + f"<br><br>{recorrido}</div>", unsafe_allow_html=True)
            if pid_ia in revisar:
                st.warning("La IA cita como evidencia un evento que la regla considera no relacionado con la derivación: "
                           + "; ".join(revisar[pid_ia]) + ". Revisar antes de aceptar.")
            es_jefe = rol.startswith("jefe")
            if fia["propone_bajar"] and fia["estado"] == "pendiente":
                st.warning("La IA propone bajarlo de su prioridad inicial: no se aplica sola. "
                           + ("Puedes confirmarlo con «Aceptar propuesta»." if es_jefe
                              else "Lo confirma el jefe de especialidad (cambia el perfil en la barra lateral)."))
            motivo_ia = st.text_input("Motivo (obligatorio para rechazar o dar prioridad absoluta)", key="motivo_ia")
            c1, c2, c3, c4 = st.columns(4)
            tiene = pid_ia in st.session_state.decisiones_ia or pid_ia in absolutos
            antes = int(fia["puesto_vista"])

            def _puesto_tras(decs, abss):
                v = aplicar_decisiones_ia(prop[prop.especialidad == especialidad], decs, abss)
                return int(v.loc[v.id_paciente == pid_ia, "puesto_vista"].iloc[0])

            with c1:
                if st.button("Aceptar propuesta", key="btn_ia_aceptada", disabled=tiene):
                    if fia["propone_bajar"] and not es_jefe:
                        st.error("Bajar de categoría lo confirma el jefe de especialidad.")
                    else:
                        nuevas = {**st.session_state.decisiones_ia, pid_ia: {"decision": "ia_aceptada"}}
                        despues = _puesto_tras(nuevas, absolutos)
                        st.session_state.decisiones_ia = nuevas
                        _decidir_ia(pid_ia, fia, "ia_aceptada", motivo_ia.strip(), antes, despues)
                        st.session_state.aviso_ia = f"Propuesta aceptada para {pid_ia}: #{antes} → #{despues}."
                        st.rerun()
            with c2:
                if st.button("Rechazar", key="btn_ia_rechazada", disabled=tiene):
                    if not motivo_ia.strip():
                        st.error("Escribe por qué la rechazas: sirve para mejorar la rúbrica.")
                    else:
                        nuevas = {**st.session_state.decisiones_ia, pid_ia: {"decision": "ia_rechazada"}}
                        despues = _puesto_tras(nuevas, absolutos)
                        st.session_state.decisiones_ia = nuevas
                        _decidir_ia(pid_ia, fia, "ia_rechazada", motivo_ia.strip(), antes, despues)
                        st.session_state.aviso_ia = f"Propuesta rechazada para {pid_ia}: #{antes} → #{despues}."
                        st.rerun()
            with c3:
                if st.button("Prioridad absoluta", key="btn_ia_absoluta", disabled=pid_ia in absolutos):
                    if not motivo_ia.strip():
                        st.error("La prioridad absoluta necesita un motivo.")
                    else:
                        despues = _puesto_tras(st.session_state.decisiones_ia, absolutos + [pid_ia])
                        st.session_state.adelantos.append({"id_paciente": pid_ia, "motivo": motivo_ia.strip(),
                                                           "usuario": usuario, "rol": rol})
                        _decidir_ia(pid_ia, fia, "prioridad_absoluta", motivo_ia.strip(), antes, despues)
                        st.session_state.aviso_ia = (f"{pid_ia} con prioridad absoluta: #{antes} → #{despues} "
                                                     "(también en la lista vigente).")
                        st.rerun()
            with c4:
                if st.button("Revertir", key="btn_ia_revertir", disabled=not tiene):
                    previa = (st.session_state.decisiones_ia.get(pid_ia, {}).get("decision")
                              or ("prioridad_absoluta" if pid_ia in absolutos else ""))
                    nuevas = {k: v for k, v in st.session_state.decisiones_ia.items() if k != pid_ia}
                    nuevos_abs = [a for a in st.session_state.adelantos if a["id_paciente"] != pid_ia]
                    despues = _puesto_tras(nuevas, [a["id_paciente"] for a in nuevos_abs])
                    st.session_state.decisiones_ia, st.session_state.adelantos = nuevas, nuevos_abs
                    _decidir_ia(pid_ia, fia, "revertida", f"revierte: {previa.replace('_', ' ')}"
                                + (f" · {motivo_ia.strip()}" if motivo_ia.strip() else ""), antes, despues)
                    st.session_state.aviso_ia = f"Decisión revertida para {pid_ia}: #{antes} → #{despues}."
                    st.rerun()
            if st.session_state.historial_ia:
                st.markdown("**Cambios de esta sesión** (también quedan en Decisiones)")
                st.dataframe(pd.DataFrame(st.session_state.historial_ia[::-1]), hide_index=True, width="stretch")
        # Aprendizaje del agente (ciclo regulador) y comparación en TEST
        ciclos = sorted(IA_RES.glob("ciclo_*.csv"), key=lambda f: ("simulado" in f.name, f.name))
        if ciclos:
            st.markdown("**Aprendizaje: el agente regulador propone reglas y solo se aceptan si mejoran en DEV** "
                        "(línea: rúbrica vigente; círculos: rúbricas candidatas probadas)")
            cl = _leer_csv(str(ciclos[0]), ciclos[0].stat().st_mtime)
            linea = alt.Chart(cl).mark_line(point=True, color=COLOR["verde"]).encode(
                x=alt.X("iteracion:O", title="Iteración"), y=alt.Y("dev_objetivo:Q", title="Objetivo en DEV",
                                                                   scale=alt.Scale(zero=False)),
                tooltip=["iteracion", "version", "aceptada", "cambios"])
            capas = linea
            if "dev_objetivo_candidata" in cl and cl.dev_objetivo_candidata.notna().any():
                capas = linea + alt.Chart(cl.dropna(subset=["dev_objetivo_candidata"])).mark_point(
                    shape="circle", size=90, filled=False, color=COLOR["ambar"]).encode(
                    x="iteracion:O", y="dev_objetivo_candidata:Q", tooltip=["iteracion", "cambios"])
            st.altair_chart(capas.properties(height=200), width="stretch")
            st.dataframe(cl[["iteracion", "version", "aceptada", "cambios", "rechazos"]], hide_index=True, width="stretch")
            modo_c = ciclos[0].name.replace("ciclo_", "").replace(".csv", "")
            tc = IA_RES / f"test_conteos_{modo_c}.csv"
            tf = IA_RES / f"test_final_{modo_c}.csv"
            if tc.exists():
                c = _leer_csv(str(tc), tc.stat().st_mtime)
                nombres = {"fifo": "Regla actual (FIFO)", "regla": "Regla MVP", "palabras_clave": "Palabras clave (sin LLM)",
                           "ia": "IA (Bedrock)", "hibrido": "IA + piso de la regla"}
                st.markdown(f"**Medición final en TEST** ({int(c.n.iloc[0])} pacientes que el agente y el regulador nunca "
                            "vieron, con otros parámetros y otra redacción de notas; los mismos para todos los métodos)")
                st.dataframe(pd.DataFrame({
                    "Método": c.metodo.map(nombres).fillna(c.metodo),
                    "Empeoraron y los subió": [f"{d} de {e}" for d, e in zip(c.detectados, c.empeoraron)],
                    "Subió sin que empeoraran": [f"{f} de {n}" for f, n in zip(c.falsas_alarmas, c.no_empeoraron)],
                    "Debían ser alta y quedaron en baja": [f"{q} de {a}" for q, a in zip(c.quedaron_en_baja, c.debian_ser_alta)]}),
                    hide_index=True, width="stretch")
            if tf.exists():
                with st.expander("Todas las métricas en TEST (κ, NDCG@10, τ de Kendall)"):
                    st.dataframe(_leer_csv(str(tf), tf.stat().st_mtime), hide_index=True, width="stretch")
            st.caption("Mundo sintético con verdad conocida (ia/mundo.py). La validación real es con especialistas (κ).")

# ----------------------------------------------------------------------------- alertas del día
with tab_alertas:
    st.markdown(
        f"<p class='nota'>La lista oficial se reprioriza cada {fecha_larga(corte).split()[0]} y con ella se agenda "
        "(cada persona, al menos 72 horas antes de su hora). Lo que llega en los reportes diarios no la mueve sola: "
        "aparece aquí con el puesto que tendría. Si no puede esperar al próximo corte, se adelanta con un motivo.</p>",
        unsafe_allow_html=True)
    if not lista.empty:
        st.markdown("**Probar: llega un evento**")
        c1, c2 = st.columns(2)
        with c1:
            pid_ev = st.selectbox("Paciente", lista.id_paciente.tolist(), key="pid_evento",
                                  index=min(len(lista) - 1, len(lista) // 2), format_func=lambda i: ETIQ_PRIO.get(i, i))
        with c2:
            tipo_ev = st.selectbox("Evento", list(EVENTOS))
        if st.button("Registrar evento"):
            antes = _fila(lista, pid_ev)
            tipo, subtipo, sev, *extra = EVENTOS[tipo_ev]
            st.session_state.eventos_demo.append((pid_ev, {"fecha_evento": hoy.isoformat(), "tipo_evento": tipo,
                                                           "subtipo": subtipo, "severidad": sev,
                                                           **(extra[0] if extra else {})}))
            st.session_state.antes_evento = (pid_ev, tipo_ev, antes)
            st.rerun()
        if st.session_state.antes_evento and st.session_state.antes_evento[1] != "indicación de control":
            pid_a, tipo_a, antes = st.session_state.antes_evento
            ahora = _fila(proyeccion, pid_a)
            vigente_a = _fila(lista, pid_a)
            no_relacionado = len(EVENTOS.get(tipo_a, ())) > 3 and ahora is not None and ahora["puesto"] >= antes["puesto"]
            if ahora and no_relacionado:
                st.metric(f"{pid_a} tras «{tipo_a}» (si se repriorizara hoy)",
                          f"Puesto {ahora['puesto']} de {len(proyeccion)}",
                          delta=f"{antes['puesto'] - ahora['puesto']} puestos", delta_color="off")
                st.info("No tiene que ver con aquello por lo que espera (" + base.pacientes[pid_a].diagnostico + "): "
                        "queda registrado y a la vista, pero no lo mueve ni genera alerta. Así una urgencia por un "
                        "esguince o un cólico no adelanta a alguien que espera por otra cosa.")
            elif ahora and vigente_a:
                st.metric(f"{pid_a} tras «{tipo_a}» (si se repriorizara hoy)",
                          f"Puesto {ahora['puesto']} de {len(proyeccion)}",
                          delta=f"{antes['puesto'] - ahora['puesto']} puestos", delta_color="normal")
                st.markdown(f"<div class='ficha alerta'>{explicacion_plantilla(ahora, antes)}<br><br>"
                            f"En la lista vigente sigue en el puesto {vigente_a['puesto']}: la alerta llega "
                            f"al equipo con el reporte de mañana y el {fecha_larga(prox)} entra al nuevo orden."
                            "</div>", unsafe_allow_html=True)
                if pid_a not in ADELANTADOS:
                    etiqueta = "Pedir que lo vean antes" if rol.startswith("jefe") else "Adelantar a la lista vigente"
                    motivo_a = st.text_input("Motivo para adelantar (queda en el registro)", key="motivo_adelanto",
                                             value=f"{tipo_a} el {hoy.strftime('%d-%m')}")
                    if st.button(etiqueta, type="primary"):
                        if not motivo_a.strip():
                            st.error("Escribe el motivo para adelantar.")
                        else:
                            adelantar(pid_a, motivo_a, int(vigente_a["puesto"]))
                            st.rerun()
                else:
                    st.success(f"{pid_a} fue adelantado: ahora es el puesto 1 de la lista vigente.")

    st.markdown("**Alertas desde el corte**")
    if alertas.empty:
        st.caption(f"Nada nuevo desde el corte del {fecha_larga(corte)} en {especialidad}. Para ver alertas con los "
                   "datos del desafío, prueba con «Hoy» en 18-09-2026 o registra un evento arriba.")
    else:
        st.markdown(f"<div class='ficha alerta'>{resumen_plantilla(alertas, res_alertas)}</div>", unsafe_allow_html=True)
        vista_a = pd.DataFrame({
            "Alerta": alertas.tipo, "Paciente": alertas.id_paciente,
            "Puesto vigente": alertas.puesto_antes.map(lambda x: "—" if pd.isna(x) else str(int(x))),
            "Si se repriorizara hoy": alertas.puesto_ahora.map(lambda x: "—" if pd.isna(x) else str(int(x))),
            "Detalle": alertas.detalle, "Lo que llegó": alertas.llego})
        st.dataframe(vista_a, hide_index=True, width="stretch",
                     column_config={"Lo que llegó": st.column_config.TextColumn(width="large")})
        if st.button("Redactar el aviso para el equipo con Bedrock"):
            texto, fuente = resumen_para_equipo(alertas, res_alertas)
            st.write(texto)
            if fuente != "bedrock":
                st.caption("Bedrock no está configurado en este equipo: se muestra el resumen de respaldo.")

# ----------------------------------------------------------------------------- qué cambió en el corte
with tab_cambios:
    st.markdown("<p class='nota'>La revisión del día de corte: qué cambió en la lista vigente respecto del corte "
                "anterior, según lo que llegó en los reportes de la semana. Primero, quién entró al carril rápido.</p>",
                unsafe_allow_html=True)
    previos = [c for c in cortes_anteriores(hoy, cfg) if c < corte][::-1]
    c1, c2 = st.columns([1, 2])
    with c1:
        desde = st.selectbox("Comparar con el corte del", previos, format_func=lambda f: f.strftime("%d-%m-%Y"),
                             key="desde_cambios")
    with c2:
        toda = st.checkbox("Ver todas las especialidades", value=False)
    df_c, res_c = _cambios_c(FIRMA_BASE, desde, corte, modo, None if toda else especialidad, base, base, cfg)
    st.markdown(f"<div class='ficha'>{resumen_plantilla(df_c, res_c)}</div>", unsafe_allow_html=True)
    if st.button("Redactar resumen para el equipo con Bedrock"):
        texto, fuente = resumen_para_equipo(df_c, res_c)
        st.write(texto)
        if fuente != "bedrock":
            st.caption("Bedrock no está configurado en este equipo: se muestra el resumen de respaldo.")
    if df_c.empty:
        st.caption("Sin cambios en el período. En los datos del desafío la última semana trae pocos eventos: "
                   "prueba con «Hoy» en 20-09-2026.")
    else:
        vista_c = pd.DataFrame({
            "Cambio": df_c.tipo, "Especialidad": df_c.especialidad, "Paciente": df_c.id_paciente,
            "Puesto antes": df_c.puesto_antes.map(lambda x: "—" if pd.isna(x) else str(int(x))),
            "Puesto ahora": df_c.puesto_ahora.map(lambda x: "—" if pd.isna(x) else str(int(x))),
            "Detalle": df_c.detalle, "Lo que llegó": df_c.llego})

        def _estilo_c(col):
            if col.name == "Cambio":
                return [f"color: {COLOR['rojo']}; font-weight: 700" if v == "Entró al carril rápido" else
                        f"color: {COLOR['ambar']}" if v in ("Nueva señal de deterioro", "Sin datos recientes") else
                        f"color: {COLOR['verde']}" if v == "Subió" else "" for v in col]
            return [""] * len(col)

        st.dataframe(vista_c.style.apply(_estilo_c), hide_index=True, width="stretch", height=380,
                     column_config={"Cambio": st.column_config.TextColumn(width="medium"),
                                    "Detalle": st.column_config.TextColumn(width="medium"),
                                    "Lo que llegó": st.column_config.TextColumn(width="medium")})
    st.markdown("<p class='nota'>En operación, la Lambda diaria carga los reportes de cada fuente a las 7:00; el "
                "lunes además publica la lista vigente (cortes/AAAA-MM-DD/lista_vigente.csv en S3).</p>",
                unsafe_allow_html=True)

# ----------------------------------------------------------------------------- interconsultas sin priorizar
with tab_sinprio:
    st.markdown("<p class='nota'>Hay especialidades que no priorizan las interconsultas. Mientras nadie la lee, la "
                "interconsulta espera con plazo medio. Si pasan 3 semanas, se usa la prioridad que propone la guía "
                "por diagnóstico al leer el texto: reglas primero y, si no encuentran criterios, IA generativa "
                "(Bedrock) que solo dice qué criterios de la guía aparecen. El especialista o el jefe la confirman.</p>",
                unsafe_allow_html=True)
    sp = [p for p in base.pacientes.values() if p.sin_priorizar and p.fecha_ingreso <= hoy]
    if not sp:
        st.info("No hay interconsultas sin priorizar en los datos cargados.")
    else:
        dias_lim = cfg.get("sin_priorizar", {}).get("dias_para_proponer", 21)
        tabla_sp = pd.DataFrame([{
            "Especialidad": p.especialidad, "Paciente": p.id_paciente, "Diagnóstico": p.diagnostico,
            "Días sin priorizar": (hoy - p.fecha_ingreso).days,
            "Lo que escribió quien derivó": p.texto_interconsulta,
            "Propuesta": (p.propuesta or {}).get("prioridad") or "—",
            "Estado": ("por revisar" if (p.propuesta or {}).get("estado") != "ok" else
                       "en uso, confirmar" if (hoy - p.fecha_ingreso).days >= dias_lim else
                       f"se usa desde el día {dias_lim}")} for p in sp]).sort_values(["Especialidad", "Días sin priorizar"],
                                                                                    ascending=[True, False])
        st.dataframe(tabla_sp, hide_index=True, width="stretch",
                     column_config={"Lo que escribió quien derivó": st.column_config.TextColumn(width="large")})
        pid_sp = st.selectbox("Interconsulta", tabla_sp.Paciente.tolist(), key="pid_sinprio",
                              format_func=lambda i: f"{i} · {base.pacientes[i].especialidad}")
        psp = base.pacientes[pid_sp]
        st.markdown(f"<div class='ficha'>«{psp.texto_interconsulta}»<br>{texto_propuesta(psp.propuesta)}</div>",
                    unsafe_allow_html=True)
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            if st.button("Releer con Bedrock"):
                prop = proponer(psp.texto_interconsulta, psp.especialidad, usar_bedrock=True)
                st.write(texto_propuesta(prop))
                if prop["fuente"] != "bedrock":
                    st.caption("Bedrock no está configurado en este equipo: se muestra la lectura con reglas.")
        with c2:
            prio_final = st.selectbox("Prioridad", ["alta", "media", "baja"],
                                      index=["alta", "media", "baja"].index((psp.propuesta or {}).get("prioridad") or "media"))
        with c3:
            if st.button("Confirmar prioridad", type="primary"):
                guardar_decision({"fecha_registro": datetime.now().isoformat(timespec="seconds"), "usuario": usuario,
                                  "rol": rol, "fecha_lista": corte.isoformat(), "especialidad": psp.especialidad,
                                  "id_paciente": pid_sp, "motivo_propuesto": texto_propuesta(psp.propuesta),
                                  "decision": f"prioridad {prio_final}", "motivo": "confirmación de prioridad",
                                  "modo": modo, "version_regla": cfg.get("version")})
                st.success(f"Prioridad {prio_final} registrada para {pid_sp}. Entra con ella en el próximo corte.")

# ----------------------------------------------------------------------------- gestión de la lista (P90)
with tab_gestion:
    st.markdown("<p class='nota'>Para la gestión de la demanda (reunión 7): cómo se distribuye la espera, quiénes están "
                "en el extremo (el percentil 90 o más de un número de días) y si se agrupan por diagnóstico, para "
                "decidir una estrategia focalizada (un operativo, un día de atención, una compra de prestaciones). "
                "Hoy esto se arma a mano en Excel.</p>", unsafe_allow_html=True)
    tabla_p = percentiles(lista_total)
    if tabla_p.empty:
        st.info("No hay pacientes en la lista vigente.")
    else:
        st.dataframe(tabla_p, hide_index=True, width="stretch")
        g1, g2 = st.columns([1, 2])
        with g1:
            criterio = st.radio("Grupo extremo", ["Sobre el P90 de la especialidad", "Más de N días"],
                                key="criterio_p90")
        with g2:
            n_dias = st.number_input("N días", min_value=30, max_value=1500, value=365, step=15, key="n_dias_p90",
                                     disabled=criterio.startswith("Sobre"))
        dx_map = {pid: p.diagnostico for pid, p in base.pacientes.items()}
        tabla_g, umbral = grupo_extremo(lista_total, especialidad,
                                        None if criterio.startswith("Sobre") else int(n_dias), dx_map)
        st.markdown(f"<div class='ficha'>{'<br>'.join(sugerencias(tabla_g, especialidad, umbral))}</div>",
                    unsafe_allow_html=True)
        if not tabla_g.empty:
            st.dataframe(tabla_g, hide_index=True, width="stretch")
            extremo = lista[lista.dias_espera > umbral]
            st.download_button("Descargar el grupo extremo (CSV)", lambda: a_csv(lista_para_exportar(extremo)),
                               file_name=f"grupo_extremo_{especialidad}_{corte.isoformat()}.csv".replace(" ", "_"),
                               mime="text/csv", on_click="ignore")

# ----------------------------------------------------------------------------- indicaciones de control
with tab_indic:
    st.markdown("<p class='nota'>El médico escribe la indicación de control en texto libre. La herramienta la "
                "convierte en un plazo dentro de la lista: primero con reglas en español y, solo si quedan dudas, "
                "con IA generativa (Bedrock). Si ninguna está segura, queda marcada para que una persona la revise: "
                "ninguna indicación se pierde.</p>", unsafe_allow_html=True)
    if lista.empty:
        st.info("No hay pacientes en esta lista.")
    else:
        c1, c2, c3 = st.columns([1, 2, 1])
        with c1:
            pid_ind = st.selectbox("Paciente", lista.id_paciente.tolist(), key="pid_indicacion",
                                   index=min(len(lista) - 1, len(lista) // 2), format_func=lambda i: ETIQ.get(i, i))
        with c2:
            texto_ind = st.text_input("Indicación escrita por el médico",
                                      value="Control prioritario en 2 semanas con ecografía.")
        with c3:
            fecha_ind = st.date_input("Fecha de la consulta", value=hoy - timedelta(days=60), max_value=hoy,
                                      format="DD-MM-YYYY", help="Cuándo se escribió. Muchas indicaciones llevan "
                                      "semanas escritas sin que el control exista en la lista.")
        if st.button("Leer indicación"):
            st.session_state.lectura = (pid_ind, texto_ind, extraer(texto_ind), fecha_ind)
        if st.session_state.lectura:
            pid_l, texto_l, ind, fecha_l = st.session_state.lectura
            si_no = {True: "sí", False: "no", None: "no se pudo determinar"}
            st.markdown(
                f"<div class='ficha'><b>{texto_l}</b><br>"
                f"Continúa en control: {si_no[ind['continua_control']]}<br>"
                f"Plazo: {str(ind['plazo_dias']) + ' días' if ind['plazo_dias'] else 'sin plazo claro'}<br>"
                f"Prioritario: {si_no[ind['prioritario']]}<br>"
                f"Requiere examen: {si_no[ind['requiere_examen']]}"
                f"{' (' + ', '.join(ind['examenes']) + ')' if ind['examenes'] else ''}<br>"
                f"Leído con: {'reglas' if ind['fuente'] == 'reglas' else 'IA generativa (Bedrock)'}"
                f"{'<br><b>Por revisar:</b> ' + ind['motivo_revision'] if ind['estado'] == 'revisar' else ''}</div>",
                unsafe_allow_html=True)
            if st.button(f"Aplicar a {pid_l} en la lista", type="primary"):
                antes = _fila(lista, pid_l)
                st.session_state.indicaciones_demo.append((pid_l, {**ind, "texto": texto_l}, fecha_l.isoformat()))
                st.session_state.antes_evento = (pid_l, "indicación de control", antes)
                st.session_state.lectura = None
                st.rerun()
        if st.session_state.antes_evento and st.session_state.antes_evento[1] == "indicación de control":
            pid_a, _, antes = st.session_state.antes_evento
            ahora = _fila(proyeccion, pid_a)
            if ahora is None:
                st.success(f"{pid_a} sale de la lista en el próximo corte: el médico indicó alta o contrarreferencia.")
            else:
                st.metric(f"{pid_a} con la indicación aplicada (si se repriorizara hoy)",
                          f"Puesto {ahora['puesto']} de {len(proyeccion)}",
                          delta=f"{antes['puesto'] - ahora['puesto']} puestos")
                st.write(explicacion_plantilla(ahora, antes))
                st.caption(f"Entra al orden en el corte del {fecha_larga(prox)}; si no puede esperar, se adelanta "
                           "desde «Alertas del día».")

        st.markdown("**¿Qué tan bien lee las indicaciones?** Prueba con 30 notas de ejemplo")
        res, resumen = _evaluacion_indicaciones()
        st.markdown(
            f"Se resuelven solas el **{resumen['pct_resueltas_automaticamente']:.0f}%**; entre ellas, el plazo es exacto en "
            f"el **{resumen['pct_correctas_entre_resueltas']:.0f}%**. Las ambiguas quedan para revisar en el "
            f"**{resumen['pct_estado_correcto']:.0f}%** de los casos que lo requerían. Notas escritas por el equipo: "
            "hay que volver a medir con notas reales del hospital.")
        st.dataframe(res[["id_nota", "texto", "estado", "continua_control", "plazo_dias", "prioritario",
                          "requiere_examen", "examenes"]].rename(columns={
            "id_nota": "Nota", "texto": "Texto", "estado": "Resultado", "continua_control": "Continúa",
            "plazo_dias": "Plazo (días)", "prioritario": "Prioritario", "requiere_examen": "Examen",
            "examenes": "Exámenes"}), hide_index=True, width="stretch", height=300)

# ----------------------------------------------------------------------------- impacto
with tab_impacto:
    archivo = RESULTADOS / "metricas.csv"
    if not archivo.exists():
        st.info("Aún no hay resultados. Genera la simulación con: python sim/simulador.py")
    else:
        met = pd.read_csv(archivo)
        met = met[met.politica.isin(["actual", "carril", "carril_plazo", "puntaje"])]
        cap = st.radio("Capacidad simulada (qué parte de la lista alcanza a atenderse en 6 meses)",
                       sorted(met.capacidad.unique(), key=lambda s: int(s.rstrip("%"))), index=1, horizontal=True)
        nombres = {"actual": "Regla actual", "carril": "Actual + carril rápido", "carril_plazo": "Regla MVP",
                   "puntaje": "Puntaje v1"}
        g = met[met.capacidad == cap].assign(Regla=lambda x: x.politica.map(nombres))
        c1, c2 = st.columns(2)
        for col, titulo, cont in [("pct_atendidos_<=30d_tras_evento", "% atendidos ≤ 30 días tras un evento grave", c1),
                                  ("eventos_graves_en_espera", "Eventos graves ocurridos estando en lista (menos es mejor)", c2)]:
            with cont:
                st.markdown(f"**{titulo}**")
                st.altair_chart(alt.Chart(g).mark_bar().encode(
                    x=alt.X(f"{col}:Q", title=None), y=alt.Y("Regla:N", sort=list(nombres.values()), title=None,
                                                             axis=alt.Axis(labelLimit=220)),
                    color=alt.condition(alt.datum.politica == "carril_plazo", alt.value(COLOR["verde"]), alt.value("#AFC0C7")),
                    tooltip=["Regla", col]).properties(height=170), width="stretch")
        tabla = g.set_index("Regla")[["pct_atendidos_<=30d_tras_evento", "mediana_dias_evento_a_atencion",
                                       "eventos_graves_en_espera", "atendidos_baja", "siguen_esperando_>365d",
                                       "pct_atendido_nse_bajo", "pct_atendido_rural"]]
        tabla.columns = ["% ≤30 d tras evento grave", "Mediana días evento → atención", "Eventos graves en lista",
                         "'Baja' atendidos", "Siguen > 365 días", "% NSE bajo atendido", "% rural atendido"]
        st.dataframe(tabla, width="stretch")
        st.markdown("<p class='nota'>Datos sintéticos. Supone que atender antes no evita los eventos (conservador) y "
                    "que todos asisten. El % atendido tras un evento grave es en parte la definición del carril: mide el "
                    "cumplimiento del KPI de reacción, no un beneficio clínico demostrado.</p>", unsafe_allow_html=True)
        if (RESULTADOS / "cadencia.md").exists():
            with st.expander("¿Repriorizar cada día o una vez por semana?"):
                st.markdown((RESULTADOS / "cadencia.md").read_text(encoding="utf-8"))
        if (RESULTADOS / "robustez.md").exists():
            with st.expander("¿Y si cambia la muestra? Robustez en 30 submuestras"):
                st.markdown((RESULTADOS / "robustez.md").read_text(encoding="utf-8"))

# ----------------------------------------------------------------------------- equidad
with tab_equidad:
    st.markdown("<p class='nota'>Compara el peso de cada grupo en toda la lista con su peso en el primer cuarto de cada "
                "especialidad (los que se citan pronto). Un índice bajo 0,8 indica que el grupo queda relegado. "
                "Medir necesidad por uso de servicios puede desfavorecer a quien accede menos (Obermeyer et al., 2019), "
                "por eso se vigila y se llama a quienes no tienen datos recientes.</p>", unsafe_allow_html=True)
    aud = _auditar_c(FIRMA_BASE, corte, modo, lista_corte, base)
    if aud.empty:
        st.info("No hay pacientes en lista a esa fecha.")
    else:
        alertas_eq = aud[aud.Alerta]
        if alertas_eq.empty:
            st.success("Ningún grupo con 10 o más pacientes queda bajo el índice 0,8 en esta lista.")
        else:
            st.warning("Grupos relegados: " + ", ".join(f"{a.Grupo} ({a['Índice de representación']:.2f})"
                                                         for _, a in alertas_eq.iterrows()))
        st.dataframe(aud.drop(columns="Alerta"), hide_index=True, width="stretch",
                     column_config={"Grupo": st.column_config.TextColumn(width="large")})
        verif = lista_corte[lista_corte.verificar_estado.notna()]
        st.markdown(f"**{len(verif)} pacientes sin eventos ni mediciones en 180 días.** No sabemos cómo están: "
                    "conviene llamarlos o enviarles un cuestionario antes de asumir que siguen estables.")
        st.dataframe(verif[["especialidad", "puesto", "id_paciente", "prioridad_inicial", "dias_espera", "dias_sin_datos"]]
                     .rename(columns={"especialidad": "Especialidad", "puesto": "Puesto", "id_paciente": "Paciente",
                                      "prioridad_inicial": "Prioridad médica", "dias_espera": "Días en lista",
                                      "dias_sin_datos": "Días sin datos"}), hide_index=True, width="stretch")

# ----------------------------------------------------------------------------- KPIs del desafío
with tab_kpi:
    st.markdown("<p class='nota'>Los cuatro indicadores que propuso el hospital, medidos sobre esta lista y los "
                "datos de ejemplo.</p>", unsafe_allow_html=True)
    _, resumen_ind = _evaluacion_indicaciones()
    k1, k2 = st.columns(2)
    k1.metric("Evento clínico → reevaluación (meta < 72 h)", "< 24 h",
              help=("El reporte diario de las 7:00 deja cada evento grave como alerta para el equipo, con el puesto que "
                    f"tendría. Recalcular toda la lista toma {_num(ms_recalculo / 1000, 2)} s. La lista oficial se "
                    "reprioriza cada lunes para que el orden con que se agenda no cambie a diario."))
    k2.metric("Lista revisada con criterio común (meta 100%)",
              f"{100 * len(lista_corte) / max(1, len(lista_corte)):.0f}%",
              help="Todas las personas en espera se evalúan con la misma regla en cada corte.")
    k3, k4 = st.columns(2)
    k3.metric("Indicaciones de control visibles en la lista (meta ≥ 90%)",
              f"{resumen_ind['pct_visibles_en_lista']:.0f}%",
              help=f"{resumen_ind['pct_resueltas_automaticamente']:.0f}% se resuelven solas y el resto queda marcado "
                   "para revisar. Medido con 30 notas de ejemplo.")
    k4.metric("Concordancia con la priorización clínica (meta κ ≥ 0,70)", "Pendiente",
              help="Lo mide un médico distinto del que priorizó al derivar (entrevista 6), con validar_concordancia.py, "
                   "o la marcha blanca con el registro de decisiones.")
    st.markdown("<p class='nota'>La concordancia la debe medir alguien distinto de quien priorizó al derivar: "
                "<code>python validar_concordancia.py</code> compara la propuesta con el orden que entregue un médico "
                "revisor (o un agente revisor con las guías del hospital, mientras no haya médicos). En marcha blanca, "
                "cada confirmación o cambio de puesto queda en el registro de decisiones.</p>", unsafe_allow_html=True)
    if (RESULTADOS / "concordancia.md").exists():
        with st.expander("Casos de validación tomados de las entrevistas"):
            st.markdown((RESULTADOS / "concordancia.md").read_text(encoding="utf-8"))
    if REGISTRO.exists():
        reg = pd.read_csv(REGISTRO)
        if len(reg) and "decision" in reg:
            st.metric("Acuerdo del equipo con la propuesta (registro de decisiones)",
                      f"{100 * (reg.decision == 'confirmado').mean():.0f}%", help=f"{len(reg)} decisiones registradas.")

# ----------------------------------------------------------------------------- registro
with tab_registro:
    # Revertir lo que se hizo en esta sesión sobre la lista vigente (adelantos y agendados); lo de la IA se revierte
    # en su pestaña. Revertir no borra el registro: agrega una fila "revertida".
    cambios_sesion = ([("adelanto", a["id_paciente"], a.get("motivo", "")) for a in st.session_state.adelantos]
                      + [("agendado", pid, f"cita {f}") for pid, f in st.session_state.agendados.items()])
    if cambios_sesion:
        st.markdown("**Cambios de esta sesión en la lista vigente**")
        elegido = st.selectbox("Cambio", range(len(cambios_sesion)), key="cambio_revertir",
                               format_func=lambda i: f"{cambios_sesion[i][0]} · {cambios_sesion[i][1]} · {cambios_sesion[i][2]}")
        if st.button("Revertir este cambio", key="btn_revertir_sesion"):
            tipo, pid_r, det = cambios_sesion[elegido]
            if tipo == "adelanto":
                st.session_state.adelantos = [a for a in st.session_state.adelantos if a["id_paciente"] != pid_r]
            else:
                st.session_state.agendados = {k: v for k, v in st.session_state.agendados.items() if k != pid_r}
            guardar_decision({"fecha_registro": datetime.now().isoformat(timespec="seconds"), "usuario": usuario,
                              "rol": rol, "fecha_lista": corte.isoformat(), "especialidad": especialidad,
                              "id_paciente": pid_r, "decision": "revertida", "motivo": f"revierte {tipo}: {det}",
                              "modo": modo, "version_regla": cfg.get("version")})
            st.rerun()
    if not REGISTRO.exists():
        st.info("Todavía no hay decisiones guardadas. Confirma o cambia un puesto en la lista vigente.")
    else:
        reg = pd.read_csv(REGISTRO)
        cambiados = int(reg.decision.isin(["cambiado", "adelantado"]).sum()) if "decision" in reg else 0
        st.markdown(f"{len(reg)} decisiones guardadas; {cambiados} cambiaron o adelantaron el puesto propuesto. "
                    "Cada una con usuario, rol, fecha y motivo: la respuesta a «¿por qué subiste a este y no a este "
                    "otro?». Los cambios con su motivo son la base para revisar la regla cada mes.")
        st.dataframe(reg.iloc[::-1], hide_index=True, width="stretch")
        st.download_button("Descargar registro (CSV)", REGISTRO.read_bytes(), file_name="registro_decisiones.csv",
                           mime="text/csv")

# ----------------------------------------------------------------------------- agenda y llamadas
with tab_agenda:
    st.markdown("<p class='nota'>Complementario. El hospital gestiona la eficiencia del box por otro carril; aquí la "
                "lista vigente se convierte en a quién llamar, al menos 72 horas antes de su hora. Además propone "
                "sobrecupos solo donde caben y una lista de reserva. El riesgo de no llegar decide acciones de agenda, "
                "nunca el orden clínico.</p>", unsafe_allow_html=True)
    if base.agenda is None:
        fechas_validas = None
        st.info("No hay agenda de boxes en los datos cargados (agenda_box.csv). Agrégala para proponer la agenda del día.")
    else:
        fechas_agenda = sorted(pd.to_datetime(base.agenda[base.agenda.especialidad == especialidad].fecha).dt.date.unique())
        fechas_validas = [f for f in fechas_agenda if f <= hoy]
    if fechas_validas is None:
        pass
    elif not fechas_validas:
        st.info(f"{especialidad} no tiene bloques de box hasta el {hoy.strftime('%d-%m-%Y')}.")
    else:
        dia = st.selectbox("Día de agenda", fechas_validas[::-1], format_func=lambda f: fecha_larga(f), key="dia_agenda")
        lista_dia = lista if corte_vigente(dia, cfg) == corte else _priorizar_c(
            FIRMA_BASE, corte_vigente(dia, cfg), modo, especialidad, base, cfg)
        prop = _agenda_c(FIRMA_BASE + repr(st.session_state.adelantos), dia, modo, especialidad, base, cfg, lista_dia)
        res = prop["resumen"]
        if not res["bloques"]:
            st.info("Ese día no hay bloques para esta especialidad.")
        else:
            boxes_txt = "1 box" if res["bloques"] == 1 else f"{res['bloques']} boxes"
            sobre_txt = (f", {res['sobrecupos']} de ellas en sobrecupo," if res["sobrecupos"] else "")
            texto = (f"{boxes_txt} con {res['cupos']} cupos. Se citan {res['citados']} personas{sobre_txt} y se "
                     f"esperan {_num(res['asistentes_esperados'], 1)} atenciones. Llamar antes a "
                     f"{res['llamar']}; {res['reserva']} quedan de reserva.")
            if res["cupos_sin_paciente"]:
                texto += f" La lista no alcanza para {res['cupos_sin_paciente']} cupos."
            st.markdown(f"<p class='estado'>{texto}</p>", unsafe_allow_html=True)

            # Lista de llamadas: una fila por persona, en el orden en que conviene llamar
            st.markdown("**A quién llamar**")
            llamadas = llamadas_del_dia(prop, lista_dia)
            n_g = llamadas.grupo.str[0].value_counts() if len(llamadas) else {}
            partes = [txt for n, txt in [
                (n_g.get("1", 0), "{} citados para confirmar o preguntar cómo están"),
                (n_g.get("2", 0), "{} próximos en la lista sin datos recientes, para no perder un cupo en alguien que "
                                  "ya no necesita la hora"),
                (n_g.get("3", 0), "{} de reserva, a llamar solo si se libera un cupo")] if n for txt in [txt.format(n)]]
            frase = (", ".join(partes[:-1]) + " y " + partes[-1] if len(partes) > 1 else partes[0]) if partes else \
                "Nadie que llamar para esta agenda"
            st.markdown(f"<p class='nota'>{frase[0].upper() + frase[1:]}. El archivo trae una columna para anotar el "
                        "resultado de cada llamada.</p>", unsafe_allow_html=True)
            tabla_ll = llamadas_para_exportar(llamadas)
            if len(tabla_ll):
                st.dataframe(tabla_ll.drop(columns=["Resultado", "Especialidad", "Cuándo"]), hide_index=True,
                             width="stretch", column_config={
                                 "Orden de llamada": st.column_config.NumberColumn("N.º", width="small"),
                                 "Grupo": st.column_config.TextColumn(width="small"),
                                 "Puesto en lista": st.column_config.NumberColumn("Puesto", width="small"),
                                 "Box": st.column_config.TextColumn(width="small"),
                                 "Orden en el box": st.column_config.TextColumn("Orden", width="small"),
                                 "Qué conversar": st.column_config.TextColumn(width="large")})
            d1, d2, _ = st.columns([1, 1, 2])
            with d1:
                st.download_button("Descargar lista de llamadas (CSV)", a_csv(tabla_ll),
                                   file_name=f"llamadas_{especialidad}_{dia.isoformat()}.csv".replace(" ", "_"),
                                   mime="text/csv", on_click="ignore", disabled=tabla_ll.empty)
            with d2:
                st.download_button("Descargar agenda propuesta (CSV)", a_csv(agenda_para_exportar(prop)),
                                   file_name=f"agenda_{especialidad}_{dia.isoformat()}.csv".replace(" ", "_"),
                                   mime="text/csv", on_click="ignore")

            for bx in prop["boxes"].itertuples():
                sobreagendado = bx.citas_que_caben < bx.capacidad
                st.markdown(f"**{bx.id_box}** · {bx.capacidad} cupos de {bx.minutos_por_cupo} min · atención media "
                            f"{bx.minutos_atencion_media} min · {_num(bx.asistentes_esperados, 1)} atenciones esperadas · "
                            f"sobretiempo esperado {bx.sobretiempo_esperado_min} min")
                if sobreagendado:
                    st.warning(f"Con las duraciones reales de atención caben {bx.citas_que_caben} citas en este bloque, "
                               f"no {bx.capacidad}: la probabilidad de pasarse más de 30 min es "
                               f"{bx.prob_pasarse_tolerancia:.0%}. Conviene revisar la capacidad del bloque.")
                c = prop["citas"][prop["citas"].id_box == bx.id_box]
                st.dataframe(pd.DataFrame({
                    "Orden": c.orden, "Tipo": c.rol.map({"cupo": "Cupo", "sobrecupo": "Sobrecupo"}),
                    "Paciente": c.id_paciente, "Puesto en lista": c.puesto_lista,
                    "Por qué está en la lista": c.motivo_puesto.str.capitalize(),
                    "Riesgo de no llegar": (c.riesgo_no_llega * 100).round().astype(int).astype(str) + "%",
                    "Antes de la cita": c.acciones.map(lambda a: "; ".join(a))}),
                    hide_index=True, width="stretch",
                    column_config={"Antes de la cita": st.column_config.TextColumn(width="large")})
            if len(prop["reserva"]):
                st.markdown("**Lista de reserva** (llamar en orden si alguien avisa que no viene)")
                rv = prop["reserva"]
                st.dataframe(pd.DataFrame({"Orden": rv.orden, "Paciente": rv.id_paciente,
                                           "Puesto en lista": rv.puesto_lista, "Prioridad": rv.prioridad_inicial}),
                             hide_index=True, width="stretch")
        archivo_ag = RESULTADOS / "agenda.csv"
        if archivo_ag.exists():
            sim_ag = pd.read_csv(archivo_ag).set_index("politica")
            at = lambda k: _num(sim_ag.loc[k, "atendidos_por_100_cupos"], 1)  # noqa: E731
            n_bloques = f"{int(sim_ag['bloques'].iloc[0]):,}".replace(",", ".") + " " if "bloques" in sim_ag else ""
            st.markdown(
                f"<p class='nota'>En la simulación de los {n_bloques}bloques de box, llamar antes y usar la lista de "
                f"reserva sube de {at('A')} a {at('C')} atenciones por cada 100 cupos; con sobrecupos solo donde "
                f"caben, a {at('E')}. Un sobrecupo fijo de 2 llega a {at('D')}, pero el "
                f"{_num(sim_ag.loc['D', 'pct_bloques_sobretiempo_30'], 0)}% de las jornadas se pasaría más de 30 "
                f"minutos.</p>", unsafe_allow_html=True)
