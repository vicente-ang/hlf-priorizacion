"""Tests de la lectura de indicaciones de control en texto libre (motor/indicaciones.py).

Las notas de ejemplo (data/indicaciones_ejemplo.csv) las escribió el equipo: sirven para verificar el
mecanismo, no para medir exactitud real. Con notas reales del hospital hay que volver a medir.
"""
import pytest

from motor import Datos, cargar_regla, evaluar_paciente, priorizar
from motor.indicaciones import evaluar_ejemplos, extraer, extraer_reglas


def test_ejemplos_ninguna_indicacion_se_pierde():
    _, r = evaluar_ejemplos(usar_bedrock=False)
    assert r["pct_estado_correcto"] == 100          # lo ambiguo queda en "revisar", lo claro se resuelve
    assert r["pct_resueltas_automaticamente"] >= 85
    assert r["pct_correctas_entre_resueltas"] >= 90
    assert r["pct_visibles_en_lista"] >= 90         # KPI del desafío


@pytest.mark.parametrize("texto,plazo", [
    ("Control en 3 meses", 90), ("ctrl 6m", 180), ("contol en 3 mese", 90), ("control en 2-3 meses", 60),
    ("volver en un año", 365), ("control anual", 365), ("citar en 6 semanas", 42), ("control en 15 días", 15),
])
def test_plazos(texto, plazo):
    assert extraer_reglas(texto)["plazo_dias"] == plazo


def test_alta_negacion_y_ambiguedad():
    assert extraer_reglas("Alta de especialidad, contrarreferencia a APS")["continua_control"] is False
    assert extraer_reglas("Control en 12 meses, sin exámenes")["requiere_examen"] is False
    r = extraer_reglas("Control después del verano")
    assert r["estado"] == "revisar" and r["plazo_dias"] is None      # no inventa un plazo
    r = extraer_reglas("Alta, pero control en APS en 3 meses")
    assert r["estado"] == "revisar"                                   # contradicción -> persona


def test_sin_bedrock_usa_reglas(monkeypatch):
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    assert extraer("Control a la brevedad")["fuente"] == "reglas"


def test_indicacion_cambia_el_plazo_y_el_alta_saca_de_la_lista():
    datos, cfg = Datos.cargar(), cargar_regla()
    pid, hoy = "PAC-HLF-00028", "2026-10-13"
    antes = priorizar(datos, hoy, cfg, especialidad="Salud Mental")
    puesto_antes = int(antes[antes.id_paciente == pid].puesto.iloc[0])

    d2 = datos.con_indicacion(pid, extraer("Control prioritario en 2 semanas"), "2026-09-01")
    despues = priorizar(d2, hoy, cfg, especialidad="Salud Mental")
    f = despues[despues.id_paciente == pid].iloc[0]
    assert "indicados por el médico" in f.motivo_plazo and f.puesto < puesto_antes

    d3 = datos.con_indicacion(pid, extraer("Alta de especialidad"), "2026-09-01")
    r = evaluar_paciente(d3.pacientes[pid], hoy, cfg)
    assert not r["en_lista"] and r["motivo_fuera"] == "alta_indicada"

    d4 = datos.con_indicacion(pid, extraer("Control a la brevedad"), "2026-09-01")
    assert evaluar_paciente(d4.pacientes[pid], hoy, cfg)["indicacion_revisar"]


def test_indicacion_futura_no_cuenta():
    datos, cfg = Datos.cargar(), cargar_regla()
    pid = "PAC-HLF-00028"
    d2 = datos.con_indicacion(pid, extraer("Alta de especialidad"), "2026-12-01")
    assert evaluar_paciente(d2.pacientes[pid], "2026-10-13", cfg)["en_lista"]
