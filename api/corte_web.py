"""Lambda del corte del lunes: regenera el front (web/datos.js) y lo publica en el bucket del front.

Pensada para correr los lunes a las 07:00 (hora de Chile) por EventBridge Scheduler (ver
infra/desplegar_lambda_corte.py). Reconstruye `datos.js` con `web.construir` a partir de los datos del hospital y
las propuestas del agente que vienen empaquetadas en el zip de la función, y lo sube a `s3://<BUCKET_WEB>/datos.js`.
Si se define DISTRIBUTION_ID, invalida la caché de CloudFront para que el cambio se vea de inmediato.

Sin Docker: el zip trae el código del proyecto y PyYAML; pandas/numpy vienen de la capa administrada AWSSDKPandas.

Variables de entorno:
  BUCKET_WEB        bucket del front (obligatorio); por defecto intenta HLF_BUCKET_WEB.
  DISTRIBUTION_ID   distribución CloudFront a invalidar (opcional).
  HLF_HOY           fecha de corte a usar (opcional; por defecto, la fecha del evento o la de hoy).

Evento (todo opcional): {"hoy": "2026-10-19", "bucket_web": "...", "distribution_id": "..."}
"""
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

CTYPE = "application/javascript; charset=utf-8"


def lambda_handler(event, context=None):
    import boto3
    from web.construir import construir

    event = event or {}
    bucket = event.get("bucket_web") or os.environ.get("BUCKET_WEB") or os.environ.get("HLF_BUCKET_WEB")
    if not bucket:
        return {"statusCode": 500, "body": json.dumps({"error": "falta BUCKET_WEB"})}
    hoy = event.get("hoy") or os.environ.get("HLF_HOY") or date.today().isoformat()
    dist = event.get("distribution_id") or os.environ.get("DISTRIBUTION_ID")

    with tempfile.TemporaryDirectory() as tmp:
        destino = Path(tmp) / "datos.js"
        d = construir(hoy=hoy, salida=destino)
        s3 = boto3.client("s3")
        s3.upload_file(str(destino), bucket, "datos.js",
                       ExtraArgs={"ContentType": CTYPE, "CacheControl": "no-cache"})

    invalidado = False
    if dist:
        import time
        cf = boto3.client("cloudfront")
        cf.create_invalidation(DistributionId=dist, InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/datos.js"]}, "CallerReference": f"corte-{int(time.time())}"})
        invalidado = True

    cuerpo = {"hoy": hoy, "corte": d["meta"]["corte"], "pacientes": len(d["pacientes"]),
              "alertas": d.get("alertas", {}).get("n", 0), "bucket": bucket, "cloudfront_invalidado": invalidado}
    return {"statusCode": 200, "body": json.dumps(cuerpo, ensure_ascii=False)}
