"""Tests de aceptación de la REGLA POR DEFECTO (carril rápido + plazo dinámico) con los
6 pacientes de ejemplo que entregó el hospital (data/dataset_hlf_ambulatorio/pacientes_ejemplo_HLF.md).

Cada test traduce el comportamiento esperado a una condición verificable. No requieren
ningún insumo clínico adicional.   Correr con:  python -m pytest -q
"""
import copy
import json

import pytest

from motor import Datos, cargar_regla, evaluar_paciente, priorizar

HOY = "2026-10-13"


@pytest.fixture(scope="module")
def datos():
    return Datos.cargar()


@pytest.fixture(scope="module")
def cfg():
    return cargar_regla()


def ev(datos, cfg, pid, corte):
    return evaluar_paciente(datos.pacientes[pid], corte, cfg)


def fila(datos, cfg, pid, corte, modo=None):
    df = priorizar(datos, corte, cfg, modo=modo, especialidad=datos.pacientes[pid].especialidad)
    f = df[df.id_paciente == pid]
    return f.iloc[0].to_dict() if len(f) else None


# --------------------------------------------------------------------------
# Los 6 pacientes de ejemplo
# --------------------------------------------------------------------------
def test_1_deterioro_progresivo_se_detecta_y_no_pierde_lugar(datos, cfg):
    """PAC-00001 (alta): PHQ-9 empeora de a poco. Las señales de deterioro aparecen y crecen,
    su atraso aumenta, y se mantiene en la parte alta de su lista."""
    cortes = ["2026-02-01", "2026-05-01", "2026-07-01", "2026-09-30"]
    r = [ev(datos, cfg, "PAC-HLF-00001", c) for c in cortes]
    assert r[0]["senales_deterioro"] == [] and len(r[-1]["senales_deterioro"]) >= 2
    assert any("PHQ-9 empeorando" in s for s in r[-1]["senales_deterioro"])
    razones = [x["razon_atraso"] for x in r]
    assert razones == sorted(razones)
    f = fila(datos, cfg, "PAC-HLF-00001", "2026-09-30")
    assert f["puesto"] <= 0.25 * f["en_especialidad"]


def test_2_deterioro_agudo_entra_al_carril_rapido(datos, cfg):
    """PAC-00002 (baja): urgencia ESI 2 + hospitalización -> entra al carril rápido y salta adelante.
    Pasado el carril, el plazo de 14 días desde la hospitalización lo mantiene sobre la regla actual."""
    antes = fila(datos, cfg, "PAC-HLF-00002", "2026-07-01")
    durante = fila(datos, cfg, "PAC-HLF-00002", "2026-08-10")
    despues = fila(datos, cfg, "PAC-HLF-00002", HOY)
    assert not antes["carril_rapido"] and durante["carril_rapido"]
    assert durante["puesto"] <= 10 and durante["puesto"] < antes["puesto"] - 30
    assert not despues["carril_rapido"]
    assert "hospitalización" in despues["motivo_plazo"]
    assert despues["puesto"] < despues["puesto_regla_actual"]


def test_3_mejora_no_sube_y_queda_registrada(datos, cfg):
    """PAC-00028 (baja): buena respuesta y reducción de dosis. No entra al carril, no tiene señales
    de deterioro, su plazo no está vencido y las mejoras quedan visibles."""
    r = ev(datos, cfg, "PAC-HLF-00028", HOY)
    assert not r["carril_rapido"] and r["senales_deterioro"] == []
    assert len(r["senales_mejora"]) == 2
    assert r["dias_atraso"] < 0


def test_4_inasistencias_alertan_pero_no_mueven_la_lista(datos, cfg):
    """PAC-00020: falta a 2 citas. Alerta de contacto, pero el orden no cambia."""
    pac = datos.pacientes["PAC-HLF-00020"]
    r = evaluar_paciente(pac, HOY, cfg)
    assert r["alerta_contacto"] and "2 inasistencias" in r["alerta_contacto"]
    sin_citas = copy.copy(pac)
    sin_citas.citas = []
    r2 = evaluar_paciente(sin_citas, HOY, cfg)
    assert r2["alerta_contacto"] is None
    for k in ("carril_rapido", "razon_atraso", "fecha_objetivo"):
        assert r[k] == r2[k]


def test_5_estable_no_se_dispara_y_sale_al_ser_atendido(datos, cfg):
    """PAC-00032: sin señales; atendido el 2026-06-30."""
    antes = ev(datos, cfg, "PAC-HLF-00032", "2026-06-01")
    assert antes["en_lista"] and not antes["carril_rapido"] and antes["senales_deterioro"] == []
    hoy = ev(datos, cfg, "PAC-HLF-00032", HOY)
    assert not hoy["en_lista"] and hoy["motivo_fuera"] == "atendido"


def test_6_fallecido_sale_de_la_lista(datos, cfg):
    """PAC-00009: fallece el 2026-09-08. Antes estaba en el carril rápido (UCI); después, fuera."""
    antes = ev(datos, cfg, "PAC-HLF-00009", "2026-09-05")
    assert antes["en_lista"] and antes["carril_rapido"]
    hoy = ev(datos, cfg, "PAC-HLF-00009", HOY)
    assert not hoy["en_lista"] and hoy["motivo_fuera"] == "fallecido"
    assert "PAC-HLF-00009" not in set(priorizar(datos, HOY, cfg)["id_paciente"])


# --------------------------------------------------------------------------
# Propiedades de la regla
# --------------------------------------------------------------------------
def test_no_mira_el_futuro(datos, cfg):
    corte = "2026-07-01"
    antes = ev(datos, cfg, "PAC-HLF-00002", corte)
    futuro = datos.con_evento("PAC-HLF-00002", {"fecha_evento": "2026-07-15", "tipo_evento": "hospitalizacion",
                                                "subtipo": "ingreso UCI", "severidad": "grave"})
    despues = evaluar_paciente(futuro.pacientes["PAC-HLF-00002"], corte, cfg)
    for k in ("carril_rapido", "razon_atraso", "senales_deterioro"):
        assert despues[k] == antes[k]


def test_evento_grave_entra_al_carril_en_el_acto(datos, cfg):
    """KPI < 72 h: al registrar un evento grave, el paciente queda entre los primeros de su lista."""
    pid = "PAC-HLF-00028"
    nuevo = datos.con_evento(pid, {"fecha_evento": HOY, "tipo_evento": "visita_urgencia",
                                   "subtipo": "triage ESI 2", "severidad": "grave"})
    f = fila(nuevo, cfg, pid, HOY)
    en_carril = int(priorizar(nuevo, HOY, cfg, especialidad=f["especialidad"])["carril_rapido"].sum())
    assert f["carril_rapido"] and f["puesto"] <= en_carril + 1


def test_evento_nunca_baja_la_urgencia(datos, cfg):
    """Un evento nuevo de cualquier gravedad nunca disminuye la razón de atraso."""
    for pid in ("PAC-HLF-00001", "PAC-HLF-00020", "PAC-HLF-00028", "PAC-HLF-00136"):
        antes = ev(datos, cfg, pid, HOY)["razon_atraso"]
        for sub, tipo, sev in [("resultado alterado", "examen_alterado", "moderada"),
                               ("ingreso hospitalario", "hospitalizacion", "grave")]:
            d2 = datos.con_evento(pid, {"fecha_evento": "2026-08-01", "tipo_evento": tipo,
                                        "subtipo": sub, "severidad": sev})
            assert evaluar_paciente(d2.pacientes[pid], HOY, cfg)["razon_atraso"] >= antes


def test_cupo_por_antiguedad(datos, cfg):
    """1 de cada 10 puestos va al que más espera; con cupo 0 no hay ninguno."""
    df = priorizar(datos, HOY, cfg)
    for esp, g in df.groupby("especialidad"):
        g = g.sort_values("puesto")
        cupos = g[g.motivo_puesto == "cupo por antigüedad"]
        assert len(cupos) == len(g) // 10
        assert set(cupos.puesto) == {10 * k for k in range(1, len(g) // 10 + 1)}
        for _, c in cupos.iterrows():   # es el más antiguo entre los que quedaban desde su puesto
            restantes = g[g.puesto >= c.puesto]
            assert c.fecha_ingreso == restantes.fecha_ingreso.min()
    cfg0 = copy.deepcopy(cfg)
    cfg0["agenda"]["cupo_antiguedad"] = 0
    assert (priorizar(datos, HOY, cfg0).motivo_puesto != "cupo por antigüedad").all()


def test_modos_dan_la_misma_lista_en_distinto_orden(datos, cfg):
    ids = {m: set(priorizar(datos, HOY, cfg, modo=m)["id_paciente"]) for m in ("carril_plazo", "carril", "actual", "puntaje")}
    assert len({frozenset(v) for v in ids.values()}) == 1
    act = priorizar(datos, HOY, cfg, modo="actual")
    assert (act.puesto == act.puesto_regla_actual).all()


def test_explicacion_y_handler(datos, cfg):
    """La explicación funciona sin AWS (plantilla) y la Lambda recalcula al llegar un evento."""
    from api.handler import lambda_handler
    from motor.explicar import explicacion_plantilla

    assert "falleció" in explicacion_plantilla(ev(datos, cfg, "PAC-HLF-00009", HOY))
    f = fila(datos, cfg, "PAC-HLF-00002", "2026-08-10")
    texto = explicacion_plantilla(f)
    assert "carril rápido" in texto and "Hospitalización" in texto and "nan" not in texto

    resp = lambda_handler({"id_paciente": "PAC-HLF-00028",
                           "evento": {"fecha_evento": HOY, "tipo_evento": "visita_urgencia",
                                      "subtipo": "triage ESI 2", "severidad": "grave"}})
    cuerpo = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert cuerpo["despues"]["carril_rapido"] and cuerpo["despues"]["puesto"] < cuerpo["antes"]["puesto"]
