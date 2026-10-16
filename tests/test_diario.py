"""Carga del reporte diario: local (motor.ingesta) y la Lambda diaria contra un S3 simulado (moto)."""
import json
from pathlib import Path

import pandas as pd
import pytest

from motor import Datos, cargar_regla
from motor.cambios import cambios, resumen_plantilla
from motor.indicaciones import desde_fila
from motor.ingesta import incorporar, leer_reporte, separar_periodo

DATASET = Path(__file__).resolve().parents[1] / "data" / "dataset_hlf_ambulatorio"


@pytest.fixture
def semana(tmp_path):
    separar_periodo(DATASET, "2026-09-13", "2026-09-20", tmp_path / "almacen", tmp_path / "reporte")
    return tmp_path


def test_cambios_detecta_los_casos_de_ejemplo():
    datos, cfg = Datos.cargar(), cargar_regla()
    df, _ = cambios(datos, None, "2026-07-01", "2026-08-10", cfg, especialidad="Cardiología")
    assert "Entró al carril rápido" in set(df[df.id_paciente == "PAC-HLF-00002"].tipo)
    df, _ = cambios(datos, None, "2026-09-05", "2026-10-13", cfg, especialidad="Endocrinología")
    fila = df[df.id_paciente == "PAC-HLF-00009"].iloc[0]
    assert fila.tipo == "Salió de la lista" and fila.detalle == "falleció"


def test_sin_cambios_relevantes():
    datos, cfg = Datos.cargar(), cargar_regla()
    df, r = cambios(datos, None, "2026-10-12", "2026-10-13", cfg)
    assert "no hubo cambios relevantes" in resumen_plantilla(df, r)


def test_ingesta_reproduce_el_calculo_directo_y_no_duplica(semana):
    cfg = cargar_regla()
    antes = Datos.cargar(semana / "almacen")
    agregadas = incorporar(semana / "almacen", leer_reporte(semana / "reporte"))
    assert agregadas["eventos_clinicos.csv"] == 30
    despues = Datos.cargar(semana / "almacen")
    df_ing, _ = cambios(antes, despues, "2026-09-13", "2026-09-20", cfg)
    df_dir, _ = cambios(Datos.cargar(), None, "2026-09-13", "2026-09-20", cfg)
    assert sorted(zip(df_ing.tipo, df_ing.id_paciente)) == sorted(zip(df_dir.tipo, df_dir.id_paciente))
    otra_vez = incorporar(semana / "almacen", leer_reporte(semana / "reporte"))
    assert all(v == 0 for v in otra_vez.values())


def test_reporte_con_columnas_faltantes_se_rechaza(semana):
    malo = pd.DataFrame({"id_paciente": ["PAC-HLF-00001"], "fecha_evento": ["2026-09-21"]})
    with pytest.raises(ValueError, match="faltan columnas"):
        incorporar(semana / "almacen", {"eventos_clinicos.csv": malo})


def test_indicacion_estructurada_manda_sobre_el_texto():
    r = desde_fila({"texto": "control en 3 meses", "continua_control": "no"})
    assert r["continua_control"] is False and r["plazo_dias"] is None
    r = desde_fila({"continua_control": "si", "prioridad_control": "prioritario", "plazo_dias": "30",
                    "requiere_examen": "si", "examenes": "TAC; hemograma"})
    assert r["plazo_dias"] == 30 and r["prioritario"] and r["examenes"] == ["TAC", "hemograma"]


def test_lambda_diaria_con_s3_simulado(semana, monkeypatch):
    moto = pytest.importorskip("moto")
    boto3 = pytest.importorskip("boto3")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "prueba")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "prueba")
    monkeypatch.delenv("BEDROCK_MODEL_ID", raising=False)
    with moto.mock_aws():
        s3 = boto3.client("s3", region_name="us-east-1")
        s3.create_bucket(Bucket="hlf")
        for f in (semana / "almacen").glob("*.csv"):
            s3.upload_file(str(f), "hlf", f"almacen/{f.name}")
        s3.put_object(Bucket="hlf", Key="almacen/estado.json", Body=json.dumps({"ultima_fecha": "2026-09-13"}))
        for f in (semana / "reporte").glob("*.csv"):
            s3.upload_file(str(f), "hlf", f"reportes/2026-09-20/{f.name}")

        from api.diario import lambda_handler
        resp = lambda_handler({"bucket": "hlf", "fecha": "2026-09-20"})
        cuerpo = json.loads(resp["body"])
        assert resp["statusCode"] == 200
        assert cuerpo["cambios"]["Entró al carril rápido"] == 3
        claves = {o["Key"] for o in s3.list_objects_v2(Bucket="hlf")["Contents"]}
        assert "salidas/cambios_2026-09-20.csv" in claves and "salidas/resumen_2026-09-20.txt" in claves
        estado = json.loads(s3.get_object(Bucket="hlf", Key="almacen/estado.json")["Body"].read())
        assert estado["ultima_fecha"] == "2026-09-20"

        # domingo 20-09: no es día de corte -> alertas desde el corte del lunes 14-09, sin mover la lista vigente
        assert cuerpo["corte"]["vigente"] == "2026-09-14" and "salidas/alertas_2026-09-20.csv" in claves

        sin = lambda_handler({"bucket": "hlf", "fecha": "2026-09-21"})
        assert sin["statusCode"] == 404

        # lunes 21-09: día de corte -> publica la lista vigente de la semana
        for f in (semana / "reporte").glob("*.csv"):
            s3.upload_file(str(f), "hlf", f"reportes/2026-09-21/{f.name}")
        lunes = json.loads(lambda_handler({"bucket": "hlf", "fecha": "2026-09-21"})["body"])
        assert lunes["corte"]["publicado"] == "cortes/2026-09-21/lista_vigente.csv" and lunes["corte"]["personas"] > 400
        claves = {o["Key"] for o in s3.list_objects_v2(Bucket="hlf")["Contents"]}
        assert "cortes/2026-09-21/lista_vigente.csv" in claves
