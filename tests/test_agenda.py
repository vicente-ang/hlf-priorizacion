"""Uso del box (motor/agenda.py): la propuesta respeta el orden clínico, los sobrecupos solo entran donde
caben y la lista de reserva es contactable."""
import pytest

from motor import Datos, cargar_regla, priorizar
from motor.agenda import citas_que_caben, parametros_box, proponer_agenda, riesgo_no_llega, simular_bloque, _ca

DIA = "2026-10-13"


@pytest.fixture(scope="module")
def datos():
    return Datos.cargar()


@pytest.fixture(scope="module")
def cfg():
    return cargar_regla()


@pytest.fixture(scope="module")
def prop(datos, cfg):
    return proponer_agenda(datos, DIA, cfg)


def test_respeta_el_orden_de_la_lista(datos, cfg, prop):
    """Se cita en el mismo orden de la lista priorizada: el riesgo de no llegar no cambia quién va primero."""
    lista = priorizar(datos, DIA, cfg)
    for esp, c in prop["citas"].groupby("especialidad"):
        esperado = lista[lista.especialidad == esp].sort_values("puesto").id_paciente.tolist()[:len(c)]
        orden = c.sort_values(["id_box", "orden"]).id_paciente.tolist()
        assert sorted(orden) == sorted(esperado)
        assert c.puesto_lista.max() == len(c)          # sin saltos: los primeros N de la lista


def test_sobrecupo_solo_donde_cabe(prop, cfg):
    b = prop["boxes"]
    ca = _ca(cfg)
    assert (b.sobrecupos <= ca["sobrecupo"]["max_por_box"]).all()
    con_sobre = b[b.sobrecupos > 0]
    assert len(con_sobre) > 0
    assert (con_sobre.prob_pasarse_tolerancia <= ca["sobrecupo"]["prob_max_pasarse"] + 1e-9).all()


def test_sin_sobrecupo_si_se_desactiva(datos, cfg):
    import copy
    c2 = copy.deepcopy(cfg)
    c2["agenda"]["sobrecupo"]["activo"] = False
    assert proponer_agenda(datos, DIA, c2)["resumen"]["sobrecupos"] == 0


def test_reserva_contactable_y_fuera_de_las_citas(datos, cfg, prop):
    lista = priorizar(datos, DIA, cfg).set_index("id_paciente")
    rv = prop["reserva"]
    assert len(rv) > 0
    assert not set(rv.id_paciente) & set(prop["citas"].id_paciente)
    assert lista.loc[rv.id_paciente, "alerta_contacto"].isna().all()


def test_riesgo_usa_la_historia_del_paciente(datos):
    p = datos.pacientes["PAC-HLF-00020"]               # 2 inasistencias antes del 2026-10-13
    r, k, n = riesgo_no_llega(p, DIA, 0.15, 4)
    assert k == 2 and r > 0.15
    r0, k0, n0 = riesgo_no_llega(datos.pacientes["PAC-HLF-00001"], DIA, 0.15, 4)
    assert n0 == 0 and r0 == pytest.approx(0.15)


def test_llamar_a_quien_tiene_inasistencias(prop):
    c = prop["citas"]
    altos = c[c.riesgo_no_llega >= 0.30]
    assert len(altos) > 0
    assert altos.acciones.map(lambda a: any(x.startswith("Llamar") for x in a)).all()


def test_citas_que_caben_baja_con_atenciones_largas(datos, cfg):
    params, ca = parametros_box(datos, DIA, cfg), _ca(cfg)
    gastro = citas_que_caben(params["Gastroenterología"], ca, 14)
    endo = citas_que_caben(params["Endocrinología"], ca, 14)
    assert params["Gastroenterología"]["minutos_media"] > params["Endocrinología"]["minutos_media"]
    assert gastro < endo


def test_simular_bloque_consistente():
    vacio = simular_bloque([], [30], 300, 30)
    assert vacio["asistentes"] == 0 and vacio["ociosos"] == 300
    lleno = simular_bloque([1.0] * 12, [40], 300, 30)
    assert lleno["asistentes"] == 12 and lleno["sobretiempo"] == pytest.approx(180) and lleno["p_pasarse"] == 1


def test_dia_sin_agenda(datos, cfg):
    assert proponer_agenda(datos, "2026-10-18", cfg)["resumen"]["bloques"] == 0     # domingo
