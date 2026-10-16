"""Lo que pidió el hospital en las entrevistas 5 y 6, traducido a condiciones verificables.

E5: clusters (hospitalización con días, UCI y cirugía; urgencias; comorbilidad; ACG) en vez de signos vitales
    sueltos; dentro de la misma prioridad no ordenar por llegada; trazabilidad "de media a alta por X" y
    "del puesto 7 al 3"; extraer de varias fuentes unidas por RUT.
E6: repriorizar un día fijo a la semana (las 72 h son para agendar); interconsultas sin priorizar reciben una
    prioridad propuesta según la guía después de ~3 semanas.
"""
from datetime import date, timedelta

import pandas as pd
import pytest

from motor import Datos, cargar_regla, evaluar_paciente, priorizar
from motor.clusters import charlson, puntos_C, puntos_L
from motor.cortes import (aplicar_adelantos, alertas_desde_corte, corte_vigente, cortes_anteriores, frase_cambio,
                          historial_paciente, proximo_corte)
from motor.guias import proponer_reglas
from motor.privacidad import seudonimo
from motor.puntaje import Paciente

HOY = "2026-10-13"


@pytest.fixture(scope="module")
def datos():
    return Datos.cargar()


@pytest.fixture(scope="module")
def cfg():
    return cargar_regla()


def _pac(pid, ingreso, prioridad="media", eventos=(), esp="Cardiología", dx="I20 Angina de pecho"):
    p = Paciente(id_paciente=pid, especialidad=esp, sub_especialidad=esp, diagnostico=dx, prioridad_inicial=prioridad,
                 fecha_ingreso=date.fromisoformat(ingreso), estado="en_espera", origen="CESFAM/APS", edad=60, sexo="F",
                 comuna="La Florida", prevision="FONASA B", nivel_socioeconomico="medio", fecha_defuncion=None)
    for e in eventos:
        p.eventos.append({**e, "fecha": date.fromisoformat(e["fecha_evento"]), "id_paciente": pid})
    p.eventos.sort(key=lambda x: x["fecha"])
    return p


def _hosp(fecha, dias, cama="SALA", cirugia=False):
    return {"fecha_evento": fecha, "tipo_evento": "hospitalizacion",
            "subtipo": "ingreso UCI" if cama == "UCI" else "ingreso hospitalario", "severidad": "grave",
            "dias_estadia": dias, "tipo_cama": cama, "cirugia": cirugia, "tipo_ingreso": "urgente"}


# ----------------------------------------------------------------------------- clusters y LACE
def test_puntos_lace_y_charlson_publicados():
    assert [puntos_L(d) for d in (0.5, 1, 2, 3, 5, 10, 20)] == [0, 1, 2, 3, 4, 5, 7]
    assert [puntos_C(c) for c in (0, 2, 3, 4, 7)] == [0, 2, 3, 5, 5]
    assert charlson(["I50", "J44", "E11.2"])[0] == 4          # IC 1 + EPOC 1 + diabetes con daño 2
    assert charlson(["E11", "E11.2"])[0] == 2                   # cuenta solo la diabetes más grave
    assert charlson(["C50", "C78"])[0] == 6                     # metástasis reemplaza a cáncer
    assert charlson(["I10", "M17", "F41"])[0] == 0              # no son condiciones de Charlson


def test_ejemplo_del_hospital_uci_sala_cirugia_y_urgencia(cfg):
    """E5: '¿es más grave el hospitalizado 10 días, el de 5 días que operaron o el de 3 días en UCI?'.
    Dentro del carril: UCI primero (nivel de cuidado), luego más riesgo LACE, y la urgencia sin hospitalizar al
    final. El que llegó primero a la lista NO va primero por eso."""
    pacs = {
        "UCI": _pac("UCI", "2026-09-01", eventos=[_hosp("2026-10-01", 3, cama="UCI")]),
        "SALA10": _pac("SALA10", "2025-01-01", eventos=[_hosp("2026-10-01", 10)]),
        "OPERADO5": _pac("OPERADO5", "2025-06-01", eventos=[_hosp("2026-10-01", 5, cirugia=True)]),
        "URG": _pac("URG", "2024-01-01", prioridad="alta", eventos=[
            {"fecha_evento": "2026-10-05", "tipo_evento": "visita_urgencia", "subtipo": "triage ESI 2",
             "severidad": "grave"}]),
        "NADA": _pac("NADA", "2023-01-01", prioridad="alta"),
    }
    lista = priorizar(Datos(pacs), HOY, {**cfg, "agenda": {**cfg["agenda"], "cupo_antiguedad": 0}})
    assert list(lista.id_paciente) == ["UCI", "SALA10", "OPERADO5", "URG", "NADA"]
    fila = lista.set_index("id_paciente")
    assert fila.loc["SALA10", "lace"] == 8 and fila.loc["OPERADO5", "lace"] == 7   # L5+A3 vs L4+A3
    assert all(fila.loc[["UCI", "SALA10", "OPERADO5", "URG"], "prioridad_dinamica"] == "alta")


def test_clusters_vienen_de_las_fuentes(datos, cfg):
    r = evaluar_paciente(datos.pacientes["PAC-HLF-00002"], "2026-08-10", cfg)
    cl = r["clusters"]
    assert cl["hospitalizacion"]["n"] == 1 and cl["hospitalizacion"]["dias_cama"] > 0
    assert cl["urgencias"]["n"] >= 1 and cl["riesgo_aps"]["acg"] in ("G0", "G1", "G2", "G3")
    assert r["lace"] is not None and r["lace"] >= 3


def test_fuentes_completan_sin_duplicar(datos):
    f = datos.fuentes
    assert f["talamo_hospitalizaciones.csv"]["completados"] == 70 and f["talamo_hospitalizaciones.csv"]["agregados"] == 0
    assert f["talamo_urgencias.csv"]["completados"] == 110       # las del dataset: se completan, no se duplican
    n_hosp = sum(1 for p in datos.pacientes.values() for e in p.eventos if e["tipo_evento"] == "hospitalizacion")
    assert n_hosp == 70


def test_seudonimo_estable_para_unir_fuentes():
    assert seudonimo("12.345.678-5", sal="x") == seudonimo("12345678-5", sal="x") != seudonimo("12345678-5", sal="y")


# ----------------------------------------------------------------------------- trazabilidad T1 -> T2
def test_prioridad_dinamica_dice_por_que_cambio(datos, cfg):
    """E5: 'cambió de media a alta por X cosa'. PAC-00002 entra baja y sube a alta por la hospitalización."""
    r = evaluar_paciente(datos.pacientes["PAC-HLF-00002"], HOY, cfg)
    assert r["prioridad_inicial"] == "baja" and r["prioridad_origen"] == "especialista"
    assert r["prioridad_dinamica"] == "alta" and "hospitalización" in r["motivo_prioridad"]
    r = evaluar_paciente(datos.pacientes["PAC-HLF-00028"], HOY, cfg)        # mejora: no cambia
    assert r["prioridad_dinamica"] == "baja" and r["motivo_prioridad"] is None


def test_historial_por_corte_muestra_el_salto(datos, cfg):
    h = historial_paciente(datos, "PAC-HLF-00002", "2026-08-12", cfg, n=4)
    assert list(h.corte) == cortes_anteriores("2026-08-12", cfg, 4)
    assert h.puesto.iloc[-1] < h.puesto.iloc[0]
    frase = frase_cambio(h)
    assert frase.startswith("Subió") and "Hospitalización" in frase


# ----------------------------------------------------------------------------- corte semanal
def test_corte_un_dia_fijo(cfg):
    assert corte_vigente("2026-10-13", cfg) == date(2026, 10, 12)        # martes -> lunes
    assert corte_vigente("2026-10-12", cfg) == date(2026, 10, 12)        # el lunes es su propio corte
    assert proximo_corte("2026-10-13", cfg) == date(2026, 10, 19)


def test_evento_entre_cortes_es_alerta_y_no_mueve_la_lista_vigente(datos, cfg):
    esp = "Traumatología"
    corte = corte_vigente(HOY, cfg)
    vigente = priorizar(datos, corte, cfg, especialidad=esp)
    pid = vigente.id_paciente.iloc[len(vigente) // 2]
    con = datos.con_evento(pid, {"fecha_evento": HOY, "tipo_evento": "hospitalizacion",
                                 "subtipo": "ingreso hospitalario", "severidad": "grave"})
    vigente_despues = priorizar(con, corte, cfg, especialidad=esp)
    assert list(vigente.id_paciente) == list(vigente_despues.id_paciente)      # la lista vigente no se mueve
    al, _ = alertas_desde_corte(con, HOY, cfg, especialidad=esp)
    fila = al[al.id_paciente == pid].iloc[0]
    assert fila.tipo == "Entró al carril rápido"
    assert fila.puesto_proyectado < fila.puesto_vigente


def test_adelantar_exige_motivo_y_sube_al_principio(datos, cfg):
    lista = priorizar(datos, "2026-10-12", cfg, especialidad="Traumatología")
    pid = lista.id_paciente.iloc[40]
    nueva = aplicar_adelantos(lista, [{"id_paciente": pid, "motivo": "lo vi ayer en urgencia", "usuario": "Dra. X",
                                       "rol": "jefe de especialidad"}])
    assert nueva.id_paciente.iloc[0] == pid and nueva.puesto.iloc[0] == 1
    assert "lo vi ayer en urgencia" in nueva.motivo_puesto.iloc[0]
    assert len(nueva) == len(lista) and nueva.puesto.tolist() == list(range(1, len(lista) + 1))


# ----------------------------------------------------------------------------- interconsultas sin priorizar
def test_guia_lee_criterios_y_negaciones():
    assert proponer_reglas("Lumbago con pérdida de fuerza en pierna", "Traumatología")["prioridad"] == "alta"
    assert proponer_reglas("Ansiedad, niega ideación suicida. Buena red de apoyo.", "Salud Mental")["prioridad"] == "baja"
    assert proponer_reglas("Sin fiebre. Fractura de radio distal.", "Traumatología")["prioridad"] == "alta"
    assert proponer_reglas("Cefalea de larga data", "Neurología")["estado"] == "revisar"
    assert proponer_reglas("", "Neurología")["estado"] == "revisar"


def test_sin_priorizar_espera_provisoria_y_despues_usa_la_guia(datos, cfg):
    p = datos.pacientes["PAC-HLF-00501"]                     # 34 días sin priorizar, texto con pérdida de fuerza
    assert p.sin_priorizar
    antes = evaluar_paciente(p, p.fecha_ingreso + timedelta(days=10), cfg)
    assert antes["prioridad_inicial"] == "media" and antes["prioridad_origen"].startswith("provisoria")
    hoy = evaluar_paciente(p, HOY, cfg)
    assert hoy["prioridad_inicial"] == "alta" and hoy["prioridad_origen"].startswith("propuesta por guía")
    revisar = evaluar_paciente(datos.pacientes["PAC-HLF-00508"], HOY, cfg)   # texto sin criterios
    assert revisar["prioridad_origen"].startswith("provisoria")


def test_exportar_lleva_la_trazabilidad(datos, cfg):
    from motor.exportar import lista_para_exportar
    t = lista_para_exportar(priorizar(datos, HOY, cfg, especialidad="Cardiología"))
    for col in ("Prioridad actual", "Por qué cambió la prioridad", "Origen de la prioridad", "Índice LACE"):
        assert col in t.columns
    assert isinstance(t, pd.DataFrame) and len(t)


# ----------------------------------------------------------------------------- validación ciega (KPI 4)
def test_kappa_ponderado():
    from validar_concordancia import kappa_ponderado
    assert kappa_ponderado(["alta", "media", "baja"] * 5, ["alta", "media", "baja"] * 5) == 1.0
    k = kappa_ponderado(["alta", "media", "baja", "alta"], ["media", "media", "baja", "alta"])
    assert 0 < k < 1


def test_muestra_ciega_y_comparacion(tmp_path, monkeypatch):
    import validar_concordancia as vc
    monkeypatch.setattr(vc, "SALIDA", tmp_path)
    fm, fc = vc.muestra(30, "2026-10-12", None)
    casos = pd.read_csv(fm)
    assert len(casos) == 30 and "puesto" not in casos.columns and "prioridad_propuesta" not in casos.columns
    clave = pd.read_csv(fc)
    casos["prioridad_revisor"] = clave["prioridad_propuesta"]            # revisor que coincide en todo
    casos.to_csv(fm, index=False)
    r = vc.comparar(fm)
    assert r["n"] == 30 and r["kappa"] == 1.0 and r["acuerdo"] == 1.0


# ----------------------------------------------------------------------------- reunión 7
def test_evento_no_relacionado_no_mueve_y_uci_siempre_cuenta(cfg):
    """'Dos urgencias por esguince en alguien derivado por hipoacusia no impactan'."""
    esguince = {"fecha_evento": "2026-10-05", "tipo_evento": "visita_urgencia", "subtipo": "triage ESI 2",
                "severidad": "grave", "diagnostico_cie10": "S93.4", "diagnostico_texto": "esguince de tobillo"}
    respiratorio = {**esguince, "diagnostico_cie10": "J44.1", "diagnostico_texto": "EPOC descompensada"}
    sin_dx = {k: v for k, v in esguince.items() if not k.startswith("diagnostico")}
    uci_otro = {**_hosp("2026-10-05", 4, cama="UCI"), "diagnostico_cie10": "K35.8"}
    casos = {"ESGUINCE": esguince, "RESP": respiratorio, "SINDX": sin_dx, "UCI": uci_otro}
    r = {k: evaluar_paciente(_pac(k, "2026-01-01", eventos=[e]), HOY, cfg) for k, e in casos.items()}
    assert not r["ESGUINCE"]["carril_rapido"] and r["ESGUINCE"]["eventos_no_relacionados"]
    assert r["ESGUINCE"]["prioridad_dinamica"] == "media"               # no cambia su prioridad
    assert r["RESP"]["carril_rapido"]                                     # cardiópata con descompensación respiratoria
    assert r["SINDX"]["carril_rapido"]                                    # sin diagnóstico: se asume relacionado
    assert r["UCI"]["carril_rapido"]                                      # la UCI siempre cuenta
    trauma = evaluar_paciente(_pac("T", "2026-01-01", eventos=[esguince], esp="Traumatología",
                                   dx="M17 Artrosis de rodilla"), HOY, cfg)
    assert trauma["carril_rapido"]                                        # para Traumatología el esguince sí cuenta


def test_recurrencia_va_antes_que_comorbilidad(cfg):
    """'Un segundo infarto en corto plazo va por sobre alguien con un infarto y otras comorbilidades'."""
    dos = _pac("DOS", "2026-03-01", eventos=[_hosp("2026-07-20", 5), _hosp("2026-10-01", 5)])
    uno = _pac("UNO", "2025-01-01", eventos=[_hosp("2026-10-01", 5)], dx="I50 Insuficiencia cardíaca")
    uno.comorbilidades = [{"cie10": c, "fecha": None} for c in ("E11.2", "N18", "J44")]
    lista = priorizar(Datos({"DOS": dos, "UNO": uno}), HOY, {**cfg, "agenda": {**cfg["agenda"], "cupo_antiguedad": 0}})
    fila = lista.set_index("id_paciente")
    assert list(lista.id_paciente) == ["DOS", "UNO"]
    assert fila.loc["DOS", "recurrencia"] == 2 and fila.loc["UNO", "lace"] > fila.loc["DOS", "lace"]


def test_agendado_sale_del_orden_y_vuelve_si_no_llega(datos, cfg):
    pid = "PAC-HLF-00008"
    con = datos.con_cita(pid, "2026-10-16", fecha_agendamiento="2026-10-13")
    assert evaluar_paciente(con.pacientes[pid], "2026-10-14", cfg)["motivo_fuera"] == "agendado"
    assert evaluar_paciente(con.pacientes[pid], "2026-10-12", cfg)["en_lista"]      # antes de agendar seguía
    p = con.pacientes[pid]
    p.citas = [{**c, "estado_cita": "no_asistio"} if c.get("id_cita") == "CT-NUEVA" else c for c in p.citas]
    assert evaluar_paciente(p, "2026-10-17", cfg)["en_lista"]                       # no llegó: vuelve


def test_gestion_p90_agrupa_por_diagnostico(datos, cfg):
    from motor.gestion import grupo_extremo, percentiles, sugerencias
    lista = priorizar(datos, "2026-10-12", cfg)
    t = percentiles(lista)
    assert set(t.Especialidad) == set(lista.especialidad) and (t["P90 de espera (días)"] >= t["Mediana de espera (días)"]).all()
    dx = {pid: p.diagnostico for pid, p in datos.pacientes.items()}
    g, umbral = grupo_extremo(lista, "Cardiología", diagnosticos=dx)
    assert umbral > 0 and g.Personas.sum() == (lista[lista.especialidad == "Cardiología"].dias_espera > umbral).sum()
    assert any("estrategia focalizada" in x or "oferta general" in x for x in sugerencias(g, "Cardiología", umbral))
