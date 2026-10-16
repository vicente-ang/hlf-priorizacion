"""Front «pulso.» (web/): los datos que exporta el motor y el servidor que guarda las decisiones."""
import json
import threading
import urllib.error
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

import pytest

from web import construir, servidor


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    salida = tmp_path_factory.mktemp("web") / "datos.js"
    d = construir.construir(salida=salida)
    texto = salida.read_text(encoding="utf-8")
    assert texto.splitlines()[1].startswith("window.HLF = ")
    return d, json.loads(texto.split("window.HLF = ", 1)[1].rstrip().rstrip(";"))


def test_exporta_la_lista_vigente_del_motor(datos):
    d, js = datos
    assert js == d                                              # lo que lee el navegador es lo que calculó el motor
    m = d["meta"]
    assert m["corte"] == "2026-10-12" and m["proximo_corte"] == "2026-10-19" and len(m["cortes"]) == 8
    assert len(d["pacientes"]) == 423 and isinstance(m["p90"], int)
    for esp in {p["especialidad"] for p in d["pacientes"]}:     # puestos 1..n dentro de cada especialidad
        puestos = sorted(p["puesto"] for p in d["pacientes"] if p["especialidad"] == esp)
        assert puestos == list(range(1, len(puestos) + 1))
    p = next(x for x in d["pacientes"] if x["id"] == "PAC-HLF-00079")
    assert p["puesto"] == 42 and p["prioridad"] == "alta" and not p["carril"]
    assert [h["carril"] for h in p["historial"]][-3:] == [True, False, False]   # salió del carril a los 30 días
    assert p["hechos"] and p["antecedentes"] and "Dolor (EVA)" in p["mediciones"]
    assert p["ia"]["categoria"] == "alta" and p["ia"]["puesto_final"] == 3 and p["ia"]["evidencia"]


def test_exporta_ingresos_cambios_y_resumen_ia(datos):
    d, _ = datos
    assert len(d["ingresos"]) == 14 and all(i["tipo"] == "sin_priorizar" for i in d["ingresos"])
    epoc = next(i for i in d["ingresos"] if i["id"] == "PAC-HLF-00509")
    assert epoc["propuesta"] == "alta" and epoc["criterios"]
    assert d["cambios"] and all(c["nuevos"] for c in d["cambios"])
    ia = d["ia"]
    assert ia["evaluados"] == 423 and ia["errores"] == 0 and ia["modelo_nombre"] == "Claude Haiku 4.5"
    assert ia["pertinencia"] == {"no_relacionados": 21, "descartados_por_ia": 21}
    fila_ia = next(r for r in ia["test"] if r["metodo"] == "ia")
    assert (fila_ia["detectados"], fila_ia["empeoraron"]) == (22, 23)


def test_servidor_guarda_decisiones_y_rechaza_basura(tmp_path, monkeypatch):
    reg = tmp_path / "registro.csv"
    monkeypatch.setenv("HLF_REGISTRO", str(reg))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), partial(servidor.Manejador, directory=str(tmp_path)))
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/api/decision"

    def post(cuerpo):
        req = urllib.request.Request(url, data=json.dumps(cuerpo).encode(), headers={"Content-Type": "application/json"})
        try:
            return urllib.request.urlopen(req).status
        except urllib.error.HTTPError as e:
            return e.code
    try:
        assert post({"id_paciente": "PAC-HLF-00008", "decision": "ia_aceptada", "usuario": "Jefe", "motivo": "ok"}) == 204
        assert post({"id_paciente": "PAC-HLF-00008", "decision": "borrar_todo"}) == 400
    finally:
        srv.shutdown()
    texto = reg.read_text(encoding="utf-8")
    assert texto.startswith("fecha_registro,") and "ia_aceptada" in texto and "borrar_todo" not in texto
