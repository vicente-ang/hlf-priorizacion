"""Entradas inválidas: mensajes claros en vez de errores técnicos."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


def correr(*args):
    r = subprocess.run([sys.executable, "-B", *args], cwd=RAIZ, capture_output=True, text=True, timeout=120)
    return r.returncode, (r.stdout + r.stderr).strip().splitlines()[-1]


@pytest.mark.parametrize("args,mensaje", [
    (["priorizar.py", "--especialidad", "Cardiologia"], "No existe la especialidad"),
    (["priorizar.py", "--corte", "2024-01-01"], "No hay pacientes en espera"),
    (["demo_evento.py", "--paciente", "PAC-NO-EXISTE"], "No existe el paciente"),
    (["demo_evento.py", "--paciente", "PAC-HLF-00009"], "no está en la lista"),
])
def test_cli_mensajes_claros(args, mensaje):
    codigo, ultima = correr(*args)
    assert codigo != 0 and mensaje in ultima and "Traceback" not in ultima


def test_ingesta_sin_archivos(tmp_path):
    codigo, ultima = correr("ingesta.py", "--reporte", str(tmp_path / "vacio"), "--fecha", "2026-10-14",
                            "--almacen", str(tmp_path / "almacen"))
    assert codigo != 0 and "No hay archivos de reporte" in ultima


def test_lambda_rechaza_eventos_invalidos():
    from api.handler import lambda_handler
    r = lambda_handler({"id_paciente": "PAC-HLF-00001", "corte": "fecha-mala"})
    assert r["statusCode"] == 400
    r = lambda_handler({"id_paciente": "PAC-HLF-00001", "evento": {"fecha_evento": "2026-10-13", "tipo_evento": "x",
                                                                    "subtipo": "y", "severidad": "critica"}})
    assert r["statusCode"] == 400 and "severidad" in json.loads(r["body"])["error"]
    assert lambda_handler({"id_paciente": "NO-EXISTE"})["statusCode"] == 404
