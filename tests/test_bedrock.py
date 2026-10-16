"""Integración con Amazon Bedrock probada SIN cuenta de AWS: un cliente real de boto3 con Stubber.

El Stubber valida que la llamada `converse` que hacemos cumpla el contrato del servicio
(nombres de campos, tipos) y devuelve la respuesta que le indiquemos. Así se prueba:
  - que el formato de la llamada es correcto (lo que fallaría mañana con la cuenta real),
  - que el código entiende respuestas normales y raras (JSON con texto alrededor, basura, plazo nulo),
  - que ante cualquier error se usa el respaldo y la demo no se cae.
"""
import json

import pytest

boto3 = pytest.importorskip("boto3")
from botocore.stub import ANY, Stubber  # noqa: E402

from motor import Datos, cargar_regla, priorizar  # noqa: E402
from motor.explicar import explicar_con_bedrock  # noqa: E402
from motor.indicaciones import extraer, extraer_bedrock  # noqa: E402


def _respuesta(texto: str) -> dict:
    return {"output": {"message": {"role": "assistant", "content": [{"text": texto}]}},
            "stopReason": "end_turn", "usage": {"inputTokens": 10, "outputTokens": 10, "totalTokens": 20},
            "metrics": {"latencyMs": 5}}


@pytest.fixture
def bedrock(monkeypatch):
    """Devuelve una función para encolar respuestas; boto3.client queda apuntando al cliente simulado."""
    cliente = boto3.client("bedrock-runtime", region_name="us-east-1",
                           aws_access_key_id="prueba", aws_secret_access_key="prueba")
    stub = Stubber(cliente)
    monkeypatch.setattr(boto3, "client", lambda *a, **k: cliente)
    monkeypatch.setenv("BEDROCK_MODEL_ID", "modelo-de-prueba")
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    esperado = {"modelId": "modelo-de-prueba", "messages": ANY, "inferenceConfig": ANY}

    def encolar(texto=None, error=None):
        if error:
            stub.add_client_error("converse", service_error_code=error, http_status_code=400)
        else:
            stub.add_response("converse", _respuesta(texto), expected_params=esperado)
        stub.activate()
    yield encolar
    stub.deactivate()


@pytest.fixture(scope="module")
def fila():
    datos, cfg = Datos.cargar(), cargar_regla()
    df = priorizar(datos, "2026-08-10", cfg, especialidad="Cardiología")
    return df[df.id_paciente == "PAC-HLF-00002"].iloc[0].to_dict()


def test_explicacion_con_bedrock(bedrock, fila):
    bedrock("Está en el carril rápido por una hospitalización hace 4 días. Es una propuesta que valida el equipo.")
    texto, fuente = explicar_con_bedrock(fila)
    assert fuente == "bedrock" and texto.startswith("Está en el carril rápido")


def test_explicacion_cae_a_plantilla_si_bedrock_falla(bedrock, fila):
    bedrock(error="AccessDeniedException")       # p. ej. modelo no habilitado en la cuenta
    texto, fuente = explicar_con_bedrock(fila)
    assert fuente == "plantilla" and "carril rápido" in texto


def test_extraccion_bedrock_json_con_texto_alrededor(bedrock):
    bedrock('Claro, aquí está:\n```json\n{"continua_control": true, "plazo_dias": 21, "prioritario": false, '
            '"requiere_examen": true, "examenes": ["ECG"]}\n```')
    r = extraer_bedrock("Ver en tres semanitas con electro")
    assert r["fuente"] == "bedrock" and r["plazo_dias"] == 21 and r["estado"] == "completa"


def test_extraccion_bedrock_no_inventa_plazo(bedrock):
    """Si la IA responde plazo nulo, el caso sigue para revisión humana (y gana la lectura por reglas)."""
    bedrock(json.dumps({"continua_control": True, "plazo_dias": None, "prioritario": False,
                        "requiere_examen": False, "examenes": []}))
    r = extraer("Control después del verano")
    assert r["estado"] == "revisar" and r["plazo_dias"] is None


def test_extraccion_bedrock_resuelve_lo_que_las_reglas_no(bedrock):
    bedrock(json.dumps({"continua_control": True, "plazo_dias": 7, "prioritario": True,
                        "requiere_examen": True, "examenes": ["ECG"]}))
    r = extraer("Control a la brevedad con ECG, idealmente la próxima semana")
    # las reglas leen "semana" sin número -> revisar; Bedrock entrega 7 días
    assert r["fuente"] == "bedrock" and r["plazo_dias"] == 7


def test_extraccion_bedrock_respuesta_basura_usa_reglas(bedrock):
    bedrock("No entendí la indicación.")
    r = extraer("Control después del verano")
    assert r["fuente"] == "reglas" and r["estado"] == "revisar"


def test_reglas_resuelven_sin_llamar_a_bedrock(bedrock):
    """Los casos claros no gastan llamadas: si se llamara a Bedrock sin respuesta encolada, fallaría."""
    bedrock("{}")                                   # se encola una, pero no debería consumirse
    r = extraer("Control en 3 meses")
    assert r["fuente"] == "reglas" and r["plazo_dias"] == 90


def test_datos_identificables_no_salen_hacia_bedrock(bedrock, monkeypatch):
    """El RUT, teléfono y correo del texto libre se reemplazan antes de enviarlo."""
    from motor.privacidad import anonimizar_texto
    texto = "Paciente 12.345.678-9 tel +56 9 8765 4321 correo ana@mail.cl: control a la brevedad"
    limpio = anonimizar_texto(texto)
    assert "12.345.678-9" not in limpio and "8765" not in limpio and "ana@mail.cl" not in limpio
    enviados = []
    import boto3 as _b
    cliente = _b.client("bedrock-runtime")                     # el cliente simulado del fixture
    original = cliente.converse

    def espia(**kw):
        enviados.append(kw["messages"][0]["content"][0]["text"])
        return original(**kw)
    monkeypatch.setattr(cliente, "converse", espia)
    bedrock('{"continua_control": true, "plazo_dias": 7, "prioritario": true, "requiere_examen": false, "examenes": []}')
    extraer_bedrock(texto)
    assert enviados and "12.345.678-9" not in enviados[0] and "[RUT]" in enviados[0]


# --- Interconsultas sin priorizar: Bedrock solo dice qué criterios de la guía aparecen
def test_guia_bedrock_lee_criterios_y_la_tabla_decide(bedrock):
    from motor.guias import proponer
    bedrock('Claro: {"alta": ["focalidad"], "baja": []}')
    r = proponer("Cefalea distinta a la habitual, con hormigueo en el brazo izquierdo.", "Neurología")
    assert r["prioridad"] == "alta" and r["fuente"] == "bedrock" and r["criterios"] == ["focalidad"]


def test_guia_bedrock_no_puede_inventar_criterios(bedrock):
    from motor.guias import proponer
    bedrock('{"alta": ["me parece grave"], "baja": []}')
    r = proponer("Cefalea de larga data.", "Neurología")
    assert r["estado"] == "revisar" and r["prioridad"] is None


def test_guia_sin_bedrock_queda_para_revisar(monkeypatch):
    from motor.guias import proponer
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    r = proponer("Cefalea de larga data.", "Neurología")
    assert r["estado"] == "revisar" and r["fuente"] == "reglas"
