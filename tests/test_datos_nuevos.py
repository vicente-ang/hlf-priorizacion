"""¿Funciona con un archivo distinto al del desafío? (simula la llegada de los datos reales)

Se arma una variante del dataset con: otras especialidades (sin Traumatología), fechas corridas 2 días hacia
adelante, sin agenda_box.csv, un subtipo de evento nuevo e indicaciones con columnas estructuradas. Luego se
usa con el validador, el motor, la interfaz y la carga diaria, apuntando la variable HLF_DATOS a esa carpeta.
"""
import shutil
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset_hlf_ambulatorio"
APP = str(Path(__file__).resolve().parents[1] / "app.py")
RENOMBRE = {"Traumatología": "Ortopedia", "Cardiología": "Cardiología adultos"}


def _correr_fechas(df, cols, dias=2):
    for c in cols:
        if c in df:
            f = pd.to_datetime(df[c], errors="coerce")
            df[c] = (f + pd.Timedelta(days=dias)).dt.strftime("%Y-%m-%d").where(f.notna(), df[c])
    return df


@pytest.fixture(scope="module")
def carpeta(tmp_path_factory):
    d = tmp_path_factory.mktemp("datos_nuevos")
    for f in DATASET.glob("*.csv"):
        if f.name == "agenda_box.csv":
            continue
        df = pd.read_csv(f, dtype=str)
        df = _correr_fechas(df, ["fecha_ingreso_lista", "fecha_evento", "fecha_medicion", "fecha_cita", "fecha_defuncion"])
        if "especialidad" in df:
            df["especialidad"] = df["especialidad"].replace(RENOMBRE)
        if f.name == "eventos_clinicos.csv":
            df.loc[df.index[:5], "subtipo"] = "consulta SAPU"
        df.to_csv(d / f.name, index=False)
    pd.DataFrame([
        {"id_paciente": "PAC-HLF-00028", "fecha_indicacion": "2026-09-01", "texto": "",
         "continua_control": "si", "prioridad_control": "prioritario", "plazo_dias": "14", "requiere_examen": "no",
         "examenes": ""},
        {"id_paciente": "PAC-HLF-00020", "fecha_indicacion": "2026-09-01", "texto": "Alta, contrarreferencia a APS",
         "continua_control": "", "prioridad_control": "", "plazo_dias": "", "requiere_examen": "", "examenes": ""},
    ]).to_csv(d / "indicaciones.csv", index=False)
    return d


def _fecha_mas_reciente(carpeta) -> date:
    fechas = []
    for archivo, col in [("lista_espera.csv", "fecha_ingreso_lista"), ("eventos_clinicos.csv", "fecha_evento"),
                         ("mediciones.csv", "fecha_medicion"), ("citaciones.csv", "fecha_cita")]:
        fechas.append(pd.to_datetime(pd.read_csv(carpeta / archivo)[col]).max().date())
    return max(fechas)


def test_validador_sin_errores_y_avisa(carpeta):
    from validar_datos import validar
    errores, avisos = validar(carpeta)
    assert errores == []
    texto = " ".join(avisos)
    assert "agenda_box" in texto and "consulta SAPU" in texto


def test_motor_con_datos_nuevos(carpeta):
    from motor import Datos, cargar_regla, evaluar_paciente, priorizar
    datos, cfg = Datos.cargar(carpeta), cargar_regla()
    assert datos.fecha_referencia() == _fecha_mas_reciente(carpeta)   # la más reciente de los datos (sin agenda)
    assert datos.fecha_referencia() > date(2026, 10, 10)
    lista = priorizar(datos, datos.fecha_referencia(), cfg)
    assert "Ortopedia" in set(lista.especialidad) and "Traumatología" not in set(lista.especialidad)
    r = evaluar_paciente(datos.pacientes["PAC-HLF-00028"], datos.fecha_referencia(), cfg)
    assert r["plazo_dias"] == 14 and "indicados por el médico" in r["motivo_plazo"]
    r = evaluar_paciente(datos.pacientes["PAC-HLF-00020"], datos.fecha_referencia(), cfg)
    assert not r["en_lista"] and r["motivo_fuera"] == "alta_indicada"


def test_interfaz_con_datos_nuevos(carpeta, tmp_path, monkeypatch):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    monkeypatch.setenv("HLF_DATOS", str(carpeta))
    monkeypatch.setenv("HLF_REGISTRO", str(tmp_path / "registro.csv"))
    at = st_testing.AppTest.from_file(APP, default_timeout=120).run()
    assert not at.exception
    fecha = next(d for d in at.date_input if d.label == "Hoy")
    assert fecha.value == _fecha_mas_reciente(carpeta)
    esp = next(s for s in at.selectbox if s.label == "Especialidad")
    assert esp.value == "Broncopulmonar"                            # sin Traumatología: la primera
    assert any("agenda_box.csv" in i.value for i in at.info)        # la agenda avisa en vez de caerse
    esp.set_value("Ortopedia").run()
    assert not at.exception


def test_carga_diaria_con_datos_nuevos(carpeta, tmp_path):
    from motor.ingesta import incorporar, leer_reporte
    almacen = tmp_path / "almacen"
    shutil.copytree(carpeta, almacen)
    reporte = tmp_path / "reporte"
    reporte.mkdir()
    pd.DataFrame([{"id_paciente": "PAC-HLF-00028", "id_evento": "EV-NUEVO-1", "fecha_evento": "2026-10-14",
                   "tipo_evento": "visita_urgencia", "subtipo": "triage ESI 2", "severidad": "grave",
                   "detalle": "urgencia"}]).to_csv(reporte / "eventos_clinicos.csv", index=False)
    assert incorporar(almacen, leer_reporte(reporte)) == {"eventos_clinicos.csv": 1}
    from motor import Datos, cargar_regla, evaluar_paciente
    d = Datos.cargar(almacen)
    assert evaluar_paciente(d.pacientes["PAC-HLF-00028"], "2026-10-14", cargar_regla())["carril_rapido"]
