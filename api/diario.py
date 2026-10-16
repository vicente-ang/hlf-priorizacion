"""Lambda diaria: carga el reporte del día desde S3 y deja el resumen de cambios.

Flujo en AWS (infra/template.yaml):
  07:00 (EventBridge Scheduler) -> esta Lambda
    1. baja el almacén        s3://<bucket>/almacen/*.csv          (si no existe, lo crea con el dataset de la imagen)
    2. baja el reporte        s3://<bucket>/reportes/<fecha>/*.csv  (las filas nuevas del día, exportadas de Polo)
    3. incorpora, recalcula y compara con la carga anterior (motor.ingesta + motor.cambios)
    4. sube el almacén actualizado, salidas/cambios_<fecha>.csv y salidas/resumen_<fecha>.txt
       (el resumen lo redacta Bedrock si está configurado; si no, la plantilla)
    5. corte semanal (motor/cortes.py): si hoy es el día de corte (lunes), publica la lista vigente en
       cortes/<fecha>/lista_vigente.csv; los otros días deja salidas/alertas_<fecha>.csv con lo que llegó desde
       el corte (eventos graves con su puesto proyectado), sin mover la lista vigente.

Evento de entrada (todo opcional): {"fecha": "2026-10-14", "bucket": "...", "desde": "2026-10-13"}
Sin fecha usa la de hoy. Sin bucket usa la variable de entorno BUCKET.
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor.ingesta import TODAS, preparar_almacen  # noqa: E402

DATASET = Path(os.environ.get("DATA_DIR", RAIZ / "data" / "dataset_hlf_ambulatorio"))


def _bajar(s3, bucket: str, prefijo: str, destino: Path) -> int:
    destino.mkdir(parents=True, exist_ok=True)
    n = 0
    for pagina in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefijo):
        for obj in pagina.get("Contents", []):
            relativo = obj["Key"][len(prefijo):]          # conserva subcarpetas (almacen/fuentes/...)
            nombre = relativo.rsplit("/", 1)[-1]
            if nombre in TODAS or nombre == "estado.json" or nombre.endswith(".csv"):
                (destino / relativo).parent.mkdir(parents=True, exist_ok=True)
                s3.download_file(bucket, obj["Key"], str(destino / relativo))
                n += 1
    return n


def lambda_handler(event, context=None):
    import boto3
    from ingesta import cargar_reporte

    event = event or {}
    bucket = event.get("bucket") or os.environ["BUCKET"]
    fecha = event.get("fecha") or date.today().isoformat()
    s3 = boto3.client("s3")
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        almacen, reporte = tmp / "almacen", tmp / "reporte"
        if _bajar(s3, bucket, "almacen/", almacen) == 0:
            almacen.rmdir()
            preparar_almacen(almacen, DATASET)
        if _bajar(s3, bucket, f"reportes/{fecha}/", reporte) == 0:
            return {"statusCode": 404, "body": json.dumps({"error": f"no hay reporte en reportes/{fecha}/"})}
        try:
            df, r, agregadas = cargar_reporte(almacen, reporte, fecha, event.get("desde"), verbose=False)
        except SystemExit as e:                   # reporte inválido: no se toca el almacén en S3
            return {"statusCode": 400, "body": json.dumps({"error": str(e)}, ensure_ascii=False)}
        from motor.cambios import resumen_para_equipo
        texto, fuente = resumen_para_equipo(df, r)
        for f in almacen.rglob("*"):
            if f.is_file():
                s3.upload_file(str(f), bucket, f"almacen/{f.relative_to(almacen).as_posix()}")
        csv = tmp / f"cambios_{fecha}.csv"
        df.to_csv(csv, index=False)
        s3.upload_file(str(csv), bucket, f"salidas/cambios_{fecha}.csv")
        s3.put_object(Bucket=bucket, Key=f"salidas/resumen_{fecha}.txt", Body=texto.encode("utf-8"))
        # Corte semanal o alertas del día
        from motor import Datos, cargar_regla, priorizar
        from motor.cortes import alertas_desde_corte, corte_vigente, es_dia_de_corte
        from motor.exportar import lista_para_exportar
        cfg, datos = cargar_regla(), Datos.cargar(almacen)
        if es_dia_de_corte(fecha, cfg):
            lista = priorizar(datos, fecha, cfg)
            destino, clave = tmp / "lista_vigente.csv", f"cortes/{fecha}/lista_vigente.csv"
            lista_para_exportar(lista).to_csv(destino, index=False, sep=";", decimal=",", encoding="utf-8-sig")
            corte = {"publicado": clave, "personas": int(len(lista))}
        else:
            al, _ = alertas_desde_corte(datos, fecha, cfg)
            destino, clave = tmp / f"alertas_{fecha}.csv", f"salidas/alertas_{fecha}.csv"
            al.to_csv(destino, index=False)
            corte = {"vigente": corte_vigente(fecha, cfg).isoformat(), "alertas": int(len(al)), "archivo": clave}
        s3.upload_file(str(destino), bucket, clave)
    cuerpo = {"fecha": fecha, "filas_incorporadas": agregadas, "resumen": texto, "fuente_resumen": fuente,
              "cambios": {k: v for k, v in r.items() if isinstance(v, int)}, "corte": corte}
    return {"statusCode": 200, "body": json.dumps(cuerpo, ensure_ascii=False)}
