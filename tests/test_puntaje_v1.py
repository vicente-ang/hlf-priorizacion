"""Tests del PUNTAJE v1 (modo opcional) con los 6 pacientes de ejemplo del hospital.
Los tests de la regla por defecto (carril rápido + plazo dinámico) están en test_regla_mvp.py.

Cada test traduce el comportamiento clínico esperado a una condición verificable.
Correr con:  python -m pytest -q
"""
import pytest

from motor import Datos, cargar_config, puntuar_paciente, puntuar_lista

HOY = "2026-10-13"


@pytest.fixture(scope="module")
def datos():
    return Datos.cargar()


@pytest.fixture(scope="module")
def cfg():
    return cargar_config()


def p(datos, cfg, pid, corte):
    return puntuar_paciente(datos.pacientes[pid], corte, cfg)


def test_1_deterioro_progresivo_sube_con_el_tiempo(datos, cfg):
    """PAC-00001: PHQ-9 empeora de a poco. El puntaje debe SUBIR, y no solo por la espera."""
    cortes = ["2026-02-01", "2026-05-01", "2026-07-01", "2026-09-30"]
    r = [p(datos, cfg, "PAC-HLF-00001", c) for c in cortes]
    puntajes = [x["puntaje"] for x in r]
    assert puntajes == sorted(puntajes), puntajes
    assert r[-1]["clinico"] > r[0]["clinico"] + 10   # sube por señales clínicas, no solo por tiempo


def test_2_deterioro_agudo_salta_y_levanta_bandera(datos, cfg):
    """PAC-00002: entra como 'baja'; urgencia ESI 2 + hospitalización -> el puntaje debe SALTAR."""
    antes = p(datos, cfg, "PAC-HLF-00002", "2026-07-01")
    despues = p(datos, cfg, "PAC-HLF-00002", "2026-08-10")
    assert despues["puntaje"] - antes["puntaje"] >= 25
    assert despues["bandera_revision"] and not antes["bandera_revision"]
    # El salto lo explican los eventos, y la boleta los muestra
    assert any("Hospitalización" in t for t in despues["top_razones"])


def test_3_mejora_resta_puntos(datos, cfg):
    """PAC-00028: buena respuesta y reducción de dosis -> el componente clínico es NEGATIVO,
    es decir, queda por debajo de lo que tendría solo por prioridad y espera."""
    r = p(datos, cfg, "PAC-HLF-00028", HOY)
    assert r["clinico"] < 0
    assert r["puntaje"] < r["base"] + r["espera"]


def test_4_inasistencias_alertan_pero_no_castigan(datos, cfg):
    """PAC-00020: falta a 2 citas. Debe generar alerta de contacto, sin cambiar su puntaje."""
    pac = datos.pacientes["PAC-HLF-00020"]
    r = puntuar_paciente(pac, HOY, cfg)
    assert r["alerta_contacto"] and "2 inasistencias" in r["alerta_contacto"]

    import copy
    sin_citas = copy.copy(pac)
    sin_citas.citas = []
    assert puntuar_paciente(sin_citas, HOY, cfg)["puntaje"] == r["puntaje"]


def test_5_estable_no_se_dispara_y_sale_al_ser_atendido(datos, cfg):
    """PAC-00032: sin señales; atendido el 2026-06-30. No debe dispararse y debe salir de la lista."""
    antes = p(datos, cfg, "PAC-HLF-00032", "2026-06-01")
    assert antes["en_lista"] and antes["clinico"] == 0 and not antes["bandera_revision"]
    hoy = p(datos, cfg, "PAC-HLF-00032", HOY)
    assert not hoy["en_lista"] and hoy["motivo_fuera"] == "atendido"


def test_6_fallecido_sale_de_la_lista(datos, cfg):
    """PAC-00009: fallece el 2026-09-08. Antes estaba en lista y con bandera; después, fuera."""
    antes = p(datos, cfg, "PAC-HLF-00009", "2026-09-05")
    assert antes["en_lista"] and antes["bandera_revision"]
    hoy = p(datos, cfg, "PAC-HLF-00009", HOY)
    assert not hoy["en_lista"] and hoy["motivo_fuera"] == "fallecido"
    lista = puntuar_lista(datos, HOY, cfg)
    assert "PAC-HLF-00009" not in set(lista["id_paciente"])


# --------------------------------------------------------------------------
# Propiedades generales del motor
# --------------------------------------------------------------------------
def test_no_mira_el_futuro(datos, cfg):
    """Un evento posterior al corte no puede cambiar el puntaje a esa fecha."""
    corte = "2026-07-01"
    antes = p(datos, cfg, "PAC-HLF-00002", corte)
    futuro = datos.con_evento("PAC-HLF-00002", {"fecha_evento": "2026-07-15", "tipo_evento": "hospitalizacion",
                                                "subtipo": "ingreso UCI", "severidad": "grave"})
    assert puntuar_paciente(futuro.pacientes["PAC-HLF-00002"], corte, cfg)["puntaje"] == antes["puntaje"]


def test_evento_nuevo_recalcula_en_el_acto(datos, cfg):
    """KPI < 72 h: al agregar un evento, el puntaje cambia en la misma llamada."""
    pid = "PAC-HLF-00028"
    antes = p(datos, cfg, pid, HOY)
    nuevo = datos.con_evento(pid, {"fecha_evento": HOY, "tipo_evento": "hospitalizacion",
                                   "subtipo": "ingreso hospitalario", "severidad": "grave"})
    despues = puntuar_paciente(nuevo.pacientes[pid], HOY, cfg)
    assert despues["puntaje"] == pytest.approx(antes["puntaje"] + 20, abs=0.2)
    assert despues["bandera_revision"]


def test_boleta_suma_el_puntaje(datos, cfg):
    """Transparencia: la suma de la boleta reproduce el puntaje (salvo topes/pisos)."""
    lista = puntuar_lista(datos, HOY, cfg)
    for r in lista.to_dict("records"):
        assert r["puntaje"] == pytest.approx(r["base"] + r["espera"] + r["eventos"] + r["mediciones"], abs=0.11)


def test_pesos_por_especialidad(datos, cfg):
    """Escalabilidad: una especialidad puede tener sus propios pesos sin tocar el código."""
    import copy
    cfg2 = copy.deepcopy(cfg)
    cfg2["especialidades"] = {"Salud Mental": {"eventos": {"puntos_por_subtipo": {"aumento dosis": 15}}}}
    a = p(datos, cfg, "PAC-HLF-00001", "2026-07-01")
    b = p(datos, cfg2, "PAC-HLF-00001", "2026-07-01")
    assert b["eventos"] > a["eventos"]

