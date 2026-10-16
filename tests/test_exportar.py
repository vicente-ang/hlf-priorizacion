"""Lista de llamadas del día y archivos descargables."""
import io

import pandas as pd
import pytest

from motor import Datos, cargar_regla, priorizar
from motor.agenda import llamadas_del_dia, proponer_agenda
from motor.exportar import a_csv, agenda_para_exportar, lista_para_exportar, llamadas_para_exportar

DIA = "2026-10-13"


@pytest.fixture(scope="module")
def caso():
    datos, cfg = Datos.cargar(), cargar_regla()
    lista = priorizar(datos, DIA, cfg)
    prop = proponer_agenda(datos, DIA, cfg, lista=lista)
    return lista, prop, llamadas_del_dia(prop, lista)


def test_una_llamada_por_persona_en_orden(caso):
    _, _, ll = caso
    assert len(ll) and ll.id_paciente.is_unique
    assert ll.orden_llamada.tolist() == list(range(1, len(ll) + 1))
    assert ll.grupo.is_monotonic_increasing                 # citados, luego próximos, luego reserva


def test_cubre_a_quien_hay_que_llamar(caso):
    lista, prop, ll = caso
    citas = prop["citas"]
    hay_que_confirmar = set(citas[citas.acciones.map(lambda a: any(x.startswith("Llamar") for x in a))].id_paciente)
    citados = ll[ll.grupo.str.startswith("1")]
    assert hay_que_confirmar <= set(citados.id_paciente)
    sin_datos = set(lista[lista.verificar_estado.notna()].id_paciente)
    assert set(citas.id_paciente) & sin_datos <= set(citados.id_paciente)
    assert set(prop["reserva"].id_paciente) == set(ll[ll.grupo.str.startswith("3")].id_paciente)


def test_proximos_sin_datos_son_los_de_la_siguiente_agenda(caso):
    lista, prop, ll = caso
    prox = ll[ll.grupo.str.startswith("2")]
    for r in prox.itertuples():
        cs = prop["citas"][prop["citas"].especialidad == r.especialidad]
        ultimo = cs.puesto_lista.max()
        assert ultimo < r.puesto_lista <= ultimo + len(cs)
        assert pd.notna(lista.set_index("id_paciente").loc[r.id_paciente, "verificar_estado"])
        assert "sin datos clínicos" in r.motivos


def test_csv_se_abre_en_excel_chile(caso):
    lista, prop, ll = caso
    for df in (lista_para_exportar(lista), agenda_para_exportar(prop), llamadas_para_exportar(ll)):
        b = a_csv(df)
        assert b.startswith("﻿".encode("utf-8"))      # BOM: Excel reconoce los tildes
        vuelta = pd.read_csv(io.BytesIO(b), sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)
        assert len(vuelta) == len(df) and list(vuelta.columns) == list(df.columns)
        assert not vuelta.isin(["nan", "None", "NaT"]).any().any()


def test_lista_exportada_explica_cada_puesto(caso):
    lista, _, _ = caso
    e = lista_para_exportar(lista)
    assert len(e) == len(lista)
    carril = e[e["Carril rápido"] == "sí"]
    assert len(carril) and (carril["Motivo del carril"] != "").all()
    assert (e["De dónde sale el plazo"] != "").all()


def test_sin_agenda_no_hay_llamadas():
    assert llamadas_del_dia({"citas": pd.DataFrame(), "reserva": pd.DataFrame()}, pd.DataFrame()).empty
    assert len(llamadas_para_exportar(pd.DataFrame())) == 0


def test_linea_de_comandos_agenda(tmp_path):
    import subprocess
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    mal = subprocess.run([sys.executable, str(raiz / "priorizar.py"), "--agenda", "13-10-2026"], capture_output=True,
                         text=True)
    assert mal.returncode != 0 and "AAAA-MM-DD" in mal.stderr and "Traceback" not in mal.stderr
    ok = subprocess.run([sys.executable, str(raiz / "priorizar.py"), "--agenda", DIA, "--especialidad",
                         "Traumatología", "--top", "1", "--salida", str(tmp_path)], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    ll = pd.read_csv(tmp_path / f"llamadas_{DIA}.csv", sep=";", encoding="utf-8-sig")
    assert len(ll) and set(ll.Especialidad) == {"Traumatología"}
