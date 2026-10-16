"""Tests de la interfaz (streamlit.testing): carga sin errores, registra un evento y guarda decisiones."""
from pathlib import Path

import pytest

st_testing = pytest.importorskip("streamlit.testing.v1")
APP = str(Path(__file__).resolve().parents[1] / "app.py")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("HLF_REGISTRO", str(tmp_path / "registro.csv"))
    return st_testing.AppTest.from_file(APP, default_timeout=120).run()


def test_carga_sin_errores(app):
    assert not app.exception
    assert app.title[0].value.startswith("Traumatología")
    assert len(app.tabs) == 12


def test_registrar_evento_es_alerta_y_se_puede_adelantar(app):
    """Entrevista 6: el evento no mueve la lista vigente; queda como alerta con su puesto proyectado y el equipo
    puede adelantarlo con un motivo que queda registrado."""
    sel = next(s for s in app.selectbox if s.key == "pid_evento")
    pid = sel.value
    puesto_antes = int(sel.format_func(pid).split("·")[0].strip("# "))
    next(s for s in app.selectbox if s.label == "Evento").set_value("Ingreso a UCI")
    next(b for b in app.button if b.label == "Registrar evento").click().run()
    assert not app.exception
    lista = next(s for s in app.selectbox if s.key == "pid_evento")
    assert int(lista.format_func(pid).split("·")[0].strip("# ")) == puesto_antes     # la lista vigente no se mueve
    next(b for b in app.button if b.label == "Adelantar a la lista vigente").click().run()
    assert not app.exception
    lista = next(s for s in app.selectbox if s.key == "pid_evento")
    assert lista.format_func(pid).startswith("#1 ")


def test_jefe_pide_ver_antes(app, tmp_path):
    next(r for r in app.radio if r.label == "Perfil").set_value("Jefe de especialidad").run()
    assert not app.exception
    next(b for b in app.button if b.label == "Pedir que lo vean antes").click().run()
    assert app.error and "motivo" in app.error[0].value
    next(t for t in app.text_area if t.key == "motivo_jefe").input("Lo vi ayer en la urgencia, está descompensado").run()
    next(b for b in app.button if b.label == "Pedir que lo vean antes").click().run()
    assert not app.exception
    registro = (tmp_path / "registro.csv").read_text(encoding="utf-8")
    assert "adelantado" in registro and "jefe de especialidad" in registro


def test_registrar_evento_sube_al_paciente(app):
    sel = next(s for s in app.selectbox if s.key == "pid_evento")
    pid = sel.value
    puesto_antes = int(sel.format_func(pid).split("·")[0].strip("# "))
    next(s for s in app.selectbox if s.label == "Evento").set_value("Hospitalización")
    next(b for b in app.button if b.label == "Registrar evento").click().run()
    assert not app.exception
    m = next(x for x in app.metric if "tras" in x.label)          # puesto si se repriorizara hoy
    puesto_despues = int(m.value.split()[1])
    assert puesto_despues < puesto_antes


def test_cambiar_puesto_exige_motivo_y_se_registra(app, tmp_path):
    decision = next(r for r in app.radio if r.label == "Decisión")
    decision.set_value("Cambiar el puesto").run()
    next(b for b in app.button if b.label == "Guardar decisión").click().run()
    assert app.error and "motivo" in app.error[0].value
    app.text_area[0].input("Paciente con dolor nocturno reportado por teléfono").run()
    next(b for b in app.button if b.label == "Guardar decisión").click().run()
    assert app.success
    registro = (tmp_path / "registro.csv").read_text(encoding="utf-8")
    assert "cambiado" in registro and "dolor nocturno" in registro


def test_leer_y_aplicar_indicacion(app):
    campo = next(t for t in app.text_input if t.label.startswith("Indicación"))
    campo.input("Control prioritario en 2 semanas con ecografía.").run()
    next(b for b in app.button if b.label == "Leer indicación").click().run()
    assert not app.exception
    aplicar = next(b for b in app.button if b.label.startswith("Aplicar a"))
    aplicar.click().run()
    assert not app.exception
    m = next(x for x in app.metric if "indicación aplicada" in x.label)
    assert int(m.delta.split()[0]) > 0          # subió en la lista


def test_panel_de_kpis(app):
    etiquetas = [m.label for m in app.metric]
    assert any("72 h" in e for e in etiquetas) and any("≥ 90%" in e for e in etiquetas)


def test_agenda_del_box(app):
    """La pestaña de agenda muestra los boxes del día con su propuesta y la lista de reserva."""
    assert not app.exception
    textos = " ".join(m.value for m in app.markdown)
    assert "BOX-" in textos and "atenciones esperadas" in textos
    assert "A quién llamar" in textos and "de reserva" in textos


def test_descargas(app):
    """Lista, agenda y llamadas se pueden descargar (el archivo de la lista se arma al hacer clic)."""
    etiquetas = [b.proto.label for b in app.get("download_button")]
    for e in ("Descargar esta lista (CSV)", "Descargar todas las especialidades", "Descargar lista de llamadas (CSV)",
              "Descargar agenda propuesta (CSV)"):
        assert e in etiquetas


def test_que_cambio(app):
    """La pestaña de cambios compara con una fecha anterior y muestra el resumen."""
    from datetime import date
    fecha = next(d for d in app.date_input if d.label == "Hoy")
    fecha.set_value(date(2026, 9, 20)).run()          # domingo: la lista vigente es la del lunes 14-09
    assert not app.exception
    textos = " ".join(m.value for m in app.markdown)
    assert "carril rápido" in textos and "07-09-2026" in textos and "14-09-2026" in textos


def test_interconsultas_sin_priorizar(app):
    assert not app.exception
    textos = " ".join(m.value for m in app.markdown)
    assert "Propuesta:" in textos or "Por revisar" in textos
    next(b for b in app.button if b.label == "Confirmar prioridad").click().run()
    assert app.success


def test_clave_de_acceso(tmp_path, monkeypatch):
    monkeypatch.setenv("HLF_REGISTRO", str(tmp_path / "registro.csv"))
    monkeypatch.setenv("HLF_CLAVE", "secreta")
    at = st_testing.AppTest.from_file(APP, default_timeout=120).run()
    assert at.title[0].value == "Lista de espera dinámica HLF" and len(at.tabs) == 0     # nada visible sin clave
    at.text_input[0].input("otra").run()
    next(b for b in at.button if b.label == "Entrar").click().run()
    assert at.error and len(at.tabs) == 0
    at.text_input[0].input("secreta").run()
    next(b for b in at.button if b.label == "Entrar").click().run()
    assert not at.exception and len(at.tabs) == 12


def test_evento_no_relacionado_no_mueve(app):
    """Reunión 7: una urgencia que no tiene que ver con la derivación se muestra pero no mueve a nadie."""
    sel = next(s for s in app.selectbox if s.key == "pid_evento")
    next(s for s in app.selectbox if s.label == "Evento").set_value("Urgencia por cólico renal (otro motivo)")
    next(b for b in app.button if b.label == "Registrar evento").click().run()
    assert not app.exception
    assert any("no lo mueve" in i.value for i in app.info)


def test_agendar_saca_del_orden(app, tmp_path):
    """Reunión 7: quien ya tiene hora agendada sale del orden (no se le quita el cupo ni se le mueve)."""
    pid = next(s for s in app.selectbox if s.label == "Paciente" and s.key is None).value
    antes = len(next(s for s in app.selectbox if s.key == "pid_evento").options)
    next(b for b in app.button if b.label == f"Agendar a {pid}").click().run()
    assert not app.exception
    assert len(next(s for s in app.selectbox if s.key == "pid_evento").options) == antes - 1
    assert any("Ya agendados" in m.value for m in app.markdown)
    assert "agendado" in (tmp_path / "registro.csv").read_text(encoding="utf-8")


def test_pestana_gestion(app):
    assert not app.exception
    textos = " ".join(m.value for m in app.markdown)
    assert "esperan más de" in textos


def test_pestana_agente_ia(app, tmp_path):
    assert not app.exception
    sel = next(s for s in app.selectbox if s.key == "pid_ia")
    next(t for t in app.text_input if t.key == "motivo_ia").input("No concuerda con la nota del CESFAM").run()
    next(b for b in app.button if b.key == "btn_ia_rechazada").click().run()
    assert not app.exception
    assert "ia_rechazada" in (tmp_path / "registro.csv").read_text(encoding="utf-8")


def _tabla_ia(app):
    return next(d.value for d in app.dataframe if "Revisar" in d.value.columns)


def test_ia_prioridad_absoluta_y_revertir(app, tmp_path):
    """Plan del equipo: desde la pestaña IA se puede dar prioridad absoluta (con motivo) y revertirla."""
    tabla = _tabla_ia(app)
    pid = tabla.Paciente.iloc[-1]                                  # el último de la especialidad
    next(s for s in app.selectbox if s.key == "pid_ia").set_value(pid).run()
    next(t for t in app.text_input if t.key == "motivo_ia").input("Indicación del jefe tras comité").run()
    next(b for b in app.button if b.key == "btn_ia_absoluta").click().run()
    assert not app.exception
    assert _tabla_ia(app).Paciente.iloc[0] == pid                  # primero de su especialidad
    assert any(pid in str(d.value.values) for d in app.dataframe if "Acción" in d.value.columns)
    next(s for s in app.selectbox if s.key == "pid_ia").set_value(pid).run()
    next(b for b in app.button if b.key == "btn_ia_revertir").click().run()
    assert not app.exception
    assert _tabla_ia(app).Paciente.iloc[0] != pid
    reg = (tmp_path / "registro.csv").read_text(encoding="utf-8")
    assert "prioridad_absoluta" in reg and "revertida" in reg


def test_ia_bajar_lo_confirma_el_jefe(app, tmp_path):
    tabla = _tabla_ia(app)
    baja = [p for p, t in zip(tabla.Paciente, tabla["Prioridad T1 → IA"]) if t.endswith("→ baja") and t.startswith("media")]
    assert baja
    next(s for s in app.selectbox if s.key == "pid_ia").set_value(baja[0]).run()
    next(b for b in app.button if b.key == "btn_ia_aceptada").click().run()
    assert any("jefe de especialidad" in e.value for e in app.error)
    assert not (tmp_path / "registro.csv").exists() or "ia_aceptada" not in (tmp_path / "registro.csv").read_text(encoding="utf-8")
    next(r for r in app.radio if r.label == "Perfil").set_value("Jefe de especialidad").run()
    next(s for s in app.selectbox if s.key == "pid_ia").set_value(baja[0]).run()
    next(b for b in app.button if b.key == "btn_ia_aceptada").click().run()
    assert not app.exception
    assert "ia_aceptada" in (tmp_path / "registro.csv").read_text(encoding="utf-8")
    fila = _tabla_ia(app).set_index("Paciente").loc[baja[0]]
    assert fila["Categoría"] == "baja" and fila["Estado"] == "aceptada"


def test_revertir_adelanto_desde_decisiones(app, tmp_path):
    sel = next(s for s in app.selectbox if s.key == "pid_evento")
    pid = sel.value
    puesto_antes = int(sel.format_func(pid).split("·")[0].strip("# "))
    next(s for s in app.selectbox if s.label == "Evento").set_value("Ingreso a UCI")
    next(b for b in app.button if b.label == "Registrar evento").click().run()
    next(b for b in app.button if b.label == "Adelantar a la lista vigente").click().run()
    assert next(s for s in app.selectbox if s.key == "pid_evento").format_func(pid).startswith("#1 ")
    next(b for b in app.button if b.key == "btn_revertir_sesion").click().run()
    assert not app.exception
    lista = next(s for s in app.selectbox if s.key == "pid_evento")
    assert int(lista.format_func(pid).split("·")[0].strip("# ")) == puesto_antes
    assert "revertida" in (tmp_path / "registro.csv").read_text(encoding="utf-8")
