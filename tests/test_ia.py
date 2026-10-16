"""Agente clínico, mundo sintético con verdad conocida, métricas y ciclo regulador (sin red)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from ia import agente, evaluar, mundo, regulador

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def mundo_chico(tmp_path_factory):
    salida = tmp_path_factory.mktemp("mundo")
    r = mundo.generar("dev", mundo.Parametros(semilla=11, n=80), salida)
    return salida / "dev", r


def test_mundo_reproducible_y_verdad_separada(mundo_chico, tmp_path):
    carpeta, r = mundo_chico
    assert r["pacientes"] == 80 and r["notas"] > 0
    otra = mundo.generar("dev", mundo.Parametros(semilla=11, n=80), tmp_path)
    assert otra == r                                                       # misma semilla, mismo mundo
    cols = set(pd.read_csv(carpeta / "lista_espera.csv").columns) | set(pd.read_csv(carpeta / "eventos_clinicos.csv").columns)
    assert not {"riesgo_90d", "categoria_ideal", "trayectoria"} & cols     # la verdad no está en los datos del agente
    v = pd.read_csv(carpeta.parent / "dev_verdad" / "verdad.csv")
    assert set(v.categoria_ideal.dropna()) <= {"alta", "media", "baja"}


def test_riesgo_sube_con_gravedad_y_tendencia():
    assert mundo.riesgo_90d(.8, 0, 0) > mundo.riesgo_90d(.4, 0, 0) > mundo.riesgo_90d(.1, 0, 0)
    assert mundo.riesgo_90d(.4, .02, 0) > mundo.riesgo_90d(.4, 0, 0) > mundo.riesgo_90d(.4, -.02, 0)


def test_ficha_no_trae_futuro_ni_verdad(mundo_chico):
    carpeta, _ = mundo_chico
    datos = agente.Datos.cargar(carpeta)
    notas = agente.cargar_notas(carpeta)
    p = next(iter(datos.pacientes.values()))
    from datetime import date
    corte = date(2026, 1, 1)
    f = agente.ficha(p, notas.get(p.id_paciente, []), corte)
    fechas = [l.split(" ")[1] for l in f.splitlines() if l.startswith("- 20")]
    assert all(x[:10] <= "2026-01-01" for x in fechas)
    assert "riesgo" not in f.lower() and "trayectoria" not in f.lower()


def test_agente_simulado_e_hibrido_no_baja_de_t1(mundo_chico):
    carpeta, _ = mundo_chico
    rub = (RAIZ / "ia" / "rubrica" / "v0.md").read_text(encoding="utf-8")
    df = agente.evaluar(carpeta, rub, "simulado")
    orden = {"alta": 0, "media": 1, "baja": 2}
    assert (df.categoria_final.map(orden) <= df.prioridad_inicial.map(orden)).all()      # nunca baja sola
    assert (df[df.carril_rapido].categoria_final == "alta").all()                         # piso de seguridad
    assert df.groupby("especialidad").puesto_final.apply(lambda s: sorted(s) == list(range(1, len(s) + 1))).all()
    json.loads(df.evidencia.iloc[0])


def test_metricas_ordenan_bien_al_oraculo(mundo_chico):
    carpeta, _ = mundo_chico
    v = pd.read_csv(carpeta.parent / "dev_verdad" / "verdad.csv").dropna(subset=["riesgo_90d"])
    oraculo = v.assign(categoria=v.categoria_ideal,
                       puesto=v.groupby("especialidad").riesgo_90d.rank(ascending=False, method="first"))
    m = evaluar.metricas(oraculo[["id_paciente", "especialidad", "categoria", "puesto"]], v)
    assert m["kappa"] == 1.0 and m["ndcg10"] == 1.0 and m["recall_top10"] == 1.0
    base = evaluar.comparar(carpeta)
    assert set(base.metodo) == {"fifo", "regla"} and (base.query("metodo == 'fifo'").sens_deterioro == 0).all()


def test_filtro_de_fuga():
    ngr = regulador.ngramas(["Control en CESFAM: angina de reposo en la última semana, CF III."])
    ok, rech = regulador.filtro_fuga([
        {"regla": "Si el paciente SIN-TR-00012 tuvo urgencia, subirlo.", "justificacion": ""},
        {"regla": "El 2026-03-02 hubo un brote, priorizar.", "justificacion": ""},
        {"regla": "Considerar alta si control en cesfam angina de reposo en la última semana.", "justificacion": ""},
        {"regla": "La trayectoria latente define el riesgo.", "justificacion": ""},
        {"regla": "Una petición explícita de APS de adelantar la atención es señal fuerte de deterioro.", "justificacion": ""},
    ], ngr)
    assert len(ok) == 1 and ok[0]["regla"].startswith("Una petición") and len(rech) == 4


def test_aplicar_regla_versiona_la_rubrica():
    rub = (RAIZ / "ia" / "rubrica" / "v0.md").read_text(encoding="utf-8")
    nueva = regulador.aplicar(rub, [{"regla": "Regla general de prueba.", "justificacion": ""}], "v1")
    assert "version: v1" in nueva and "## Reglas aprendidas" in nueva and "Regla general de prueba." in nueva


def test_agente_con_bedrock_simulado(mundo_chico, monkeypatch, tmp_path):
    """La llamada a Bedrock cumple el contrato del servicio (Stubber) y la salida JSON se usa tal cual."""
    boto3 = pytest.importorskip("boto3")
    from botocore.stub import ANY, Stubber
    from ia import bedrock
    carpeta, _ = mundo_chico
    cliente = boto3.client("bedrock-runtime", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    stub = Stubber(cliente)
    monkeypatch.setattr(bedrock, "_cliente", lambda region: cliente)
    monkeypatch.setattr(bedrock, "CACHE", tmp_path)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "modelo-prueba")
    salida = {"categoria": "alta", "puntaje": 88, "direccion": "sube",
              "criterios": {"evento_agudo": 0, "tendencia": 3, "alarma_especifica": 2, "comorbilidad": 1, "recurrencia": 0},
              "evidencia": [{"fecha": "2026-09-19", "fuente": "CESFAM", "cita": "pide adelantar"}], "ignorado": [],
              "confianza": "alta", "resumen": "Deterioro progresivo en notas."}
    stub.add_response("converse", {"output": {"message": {"role": "assistant", "content": [{"text": json.dumps(salida)}]}},
                                   "stopReason": "end_turn", "usage": {"inputTokens": 900, "outputTokens": 120, "totalTokens": 1020},
                                   "metrics": {"latencyMs": 10}},
                      expected_params={"modelId": "modelo-prueba", "system": ANY, "messages": ANY, "inferenceConfig": ANY,
                                       "outputConfig": ANY})
    stub.activate()
    df = agente.evaluar(carpeta, "rúbrica", "bedrock", concurrencia=1,
                        ids=[pd.read_csv(carpeta / "lista_espera.csv").id_paciente.iloc[0]])
    stub.deactivate()
    assert df.iloc[0].categoria_ia == "alta" and df.iloc[0].puntaje_ia == 88 and df.iloc[0].modo == "json_schema"
    assert df.iloc[0].tokens_entrada == 900


def test_comparar_usa_los_mismos_pacientes_que_el_agente(mundo_chico):
    """Con --muestra, FIFO y la regla se miden sobre los mismos pacientes que la IA (NDCG comparable)."""
    carpeta, _ = mundo_chico
    rub = (RAIZ / "ia" / "rubrica" / "v0.md").read_text(encoding="utf-8")
    ids = list(pd.read_csv(carpeta / "lista_espera.csv").id_paciente.iloc[:30])
    df = agente.evaluar(carpeta, rub, "simulado", ids=ids)
    tabla = evaluar.comparar(carpeta, df, otros={"palabras_clave": df})
    assert set(tabla.metodo) == {"fifo", "regla", "palabras_clave", "ia", "hibrido"}
    assert tabla.n.nunique() == 1 and tabla.n.iloc[0] == len(df)
    c = evaluar.conteos(carpeta, df)
    assert (c.detectados <= c.empeoraron).all() and (c.query("metodo == 'fifo'").detectados == 0).all()


def test_regulador_pide_reglas_cortas_y_recibe_lo_rechazado(monkeypatch):
    """El regulador conoce el límite de largo y, si su propuesta anterior no pasó el filtro, se le dice por qué."""
    from ia import bedrock
    visto = {}

    def falso(sistema, usuario, esquema, **kw):
        visto.update(sistema=sistema, usuario=usuario, esquema=esquema)
        return {"diagnostico_errores": "", "cambios": []}, {"modo": "json_schema"}

    monkeypatch.setattr(bedrock, "llamar_json", falso)
    errs = pd.DataFrame([{"id_paciente": "X1", "categoria_ia": "media", "puntaje_ia": 40, "categoria_ideal": "alta",
                          "error": 1}])
    largo = "x" * (regulador.MAX_LARGO + 1)
    _, rech = regulador.filtro_fuga([{"regla": largo, "justificacion": ""}], set())
    assert "demasiado larga" in rech[0] and str(regulador.MAX_LARGO) in rech[0]
    regulador.proponer(errs, {"X1": "ficha"}, "rúbrica", "bedrock", rechazadas=rech)
    assert "300 caracteres" in visto["sistema"] and "300 caracteres" in visto["usuario"]
    assert "NO PASÓ EL FILTRO" in visto["usuario"] and "demasiado larga" in visto["usuario"]


def _prop_demo():
    return pd.DataFrame([
        {"id_paciente": "A", "especialidad": "X", "fecha_ingreso": "2026-01-01", "prioridad_inicial": "media",
         "carril_rapido": False, "categoria_ia": "baja", "puntaje_ia": 10, "categoria_final": "media", "puesto_final": 2},
        {"id_paciente": "B", "especialidad": "X", "fecha_ingreso": "2026-02-01", "prioridad_inicial": "media",
         "carril_rapido": False, "categoria_ia": "alta", "puntaje_ia": 80, "categoria_final": "alta", "puesto_final": 1},
        {"id_paciente": "C", "especialidad": "X", "fecha_ingreso": "2025-06-01", "prioridad_inicial": "baja",
         "carril_rapido": True, "categoria_ia": "baja", "puntaje_ia": 20, "categoria_final": "alta", "puesto_final": 3},
        {"id_paciente": "D", "especialidad": "X", "fecha_ingreso": "2025-01-01", "prioridad_inicial": "baja",
         "carril_rapido": False, "categoria_ia": "baja", "puntaje_ia": 5, "categoria_final": "baja", "puesto_final": 4}])


def test_decisiones_aceptar_rechazar_absoluta_y_revertir():
    from ia import decisiones as dec
    prop = _prop_demo()
    sin = dec.aplicar(prop)
    assert list(sin.sort_values("puesto_vista").id_paciente) == ["B", "C", "A", "D"]       # híbrido: C por el piso
    assert (sin.estado == "pendiente").all()
    acept = dec.aplicar(prop, {"A": {"decision": "ia_aceptada"}, "C": {"decision": "ia_aceptada"}})
    cat = dict(zip(acept.id_paciente, acept.categoria_vista))
    assert cat["A"] == "baja"            # una persona confirmó bajarlo
    assert cat["C"] == "alta"            # pero nunca bajo el piso de la regla (evento grave relacionado)
    rech = dec.aplicar(prop, {"B": {"decision": "ia_rechazada"}})
    assert dict(zip(rech.id_paciente, rech.categoria_vista))["B"] == "media"               # se ignora a la IA
    absl = dec.aplicar(prop, {}, ["D"])
    assert absl.sort_values("puesto_vista").id_paciente.iloc[0] == "D"
    assert dict(zip(absl.id_paciente, absl.estado))["D"] == "prioridad absoluta"
    assert dec.aplicar(prop, {}, []).equals(sin)                                           # revertir = volver a sin


def test_pertinencia_de_la_ia_contra_la_regla():
    """La IA declara en `ignorado` los eventos no relacionados; si los cita sin declararlos, se marca para revisar."""
    from datetime import date
    from types import SimpleNamespace
    from ia import decisiones as dec
    from motor import cargar_regla
    cfg = cargar_regla()
    ev = {"fecha": date(2026, 9, 30), "subtipo": "triage ESI 2", "severidad": "grave", "diagnostico_cie10": "N20.0",
          "diagnostico_texto": "cólico renal"}
    p = SimpleNamespace(id_paciente="P1", especialidad="Traumatología", diagnostico="M54 Lumbago", eventos=[ev])
    datos = SimpleNamespace(pacientes={"P1": p})
    evid = json.dumps([{"fecha": "2026-09-30", "fuente": "Urgencia", "cita": "Cólico renal (N20.0)"}])
    base = {"id_paciente": "P1", "evidencia": evid, "corte": "2026-10-13"}
    ok = pd.DataFrame([{**base, "ignorado": json.dumps(["Cólico renal (N20.0): no pertinente a lumbago"])}])
    mal = pd.DataFrame([{**base, "ignorado": "[]"}])
    assert dec.revisar_pertinencia(ok, datos, cfg) == {}
    assert "P1" in dec.revisar_pertinencia(mal, datos, cfg)
    assert dec.descartados(ok, datos, cfg) == {"no_relacionados": 1, "descartados_por_ia": 1}


def test_los_tests_no_llaman_a_aws_aunque_la_terminal_tenga_entorno_ps1():
    """conftest.py borra BEDROCK_MODEL_ID y compañía en cada test: el resultado no depende de la terminal."""
    import os
    assert not any(os.environ.get(v) for v in ("BEDROCK_MODEL_ID", "BEDROCK_MODEL_ID_REGULADOR", "HLF_BUCKET"))
