# Hace que pytest encuentre los paquetes del repositorio.
#
# Tests herméticos: aunque la terminal tenga cargado entorno.ps1 (BEDROCK_MODEL_ID, credenciales, bucket), ningún
# test llama a AWS de verdad. Sin esto, con Bedrock configurado, `extraer("Control a la brevedad")` le pregunta al
# modelo (las reglas dudan) y el resultado deja de ser determinista. Los tests que prueban la llamada a Bedrock
# fijan su propio BEDROCK_MODEL_ID con monkeypatch y usan el Stubber de boto3.
import pytest

VARIABLES_AWS = ("BEDROCK_MODEL_ID", "BEDROCK_MODEL_ID_REGULADOR", "HLF_BUCKET", "HLF_FUENTES")


@pytest.fixture(autouse=True)
def _sin_aws_real(monkeypatch):
    for v in VARIABLES_AWS:
        monkeypatch.delenv(v, raising=False)
    yield
