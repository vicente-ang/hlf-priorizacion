r"""Publica el front estático (web/) en AWS. Idempotente: se puede correr varias veces.

Estrategia:
  1. Bucket S3 PRIVADO `hlf-priorizacion-web-<cuenta>` (acceso público bloqueado), con etiqueta
     proyecto=hlf-priorizacion.
  2. Sube index.html, estilos.css, app.js y datos.js con su Content-Type.
  3. Intenta servirlo con CloudFront + Origin Access Control (OAC). Si no hay permisos para CloudFront,
     cae a una Lambda con Function URL que lee los 4 archivos del bucket (fallback sin CloudFront).
  4. Invalida la caché de CloudFront al volver a subir.

Reglas de la cuenta compartida: solo recursos con nombre `hlf-...` y etiqueta proyecto=hlf-priorizacion; región
us-east-1; sin buckets públicos; sin usuarios/claves IAM nuevas.

Uso (con las credenciales del taller ya cargadas):
  . .\entorno.ps1
  python -m infra.desplegar_web                 # despliega/actualiza y muestra la URL
  python -m infra.desplegar_web --solo-subir    # solo re-sube los 4 archivos e invalida la caché
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

RAIZ = Path(__file__).resolve().parents[1]
WEB = RAIZ / "web"
REGION = "us-east-1"
TAG = {"Key": "proyecto", "Value": "hlf-priorizacion"}
ARCHIVOS = {
    "index.html": "text/html; charset=utf-8",
    "estilos.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "datos.js": "application/javascript; charset=utf-8",
}
COMENTARIO_CF = "hlf-priorizacion-web"       # marca para encontrar la distribución existente (idempotencia)


def _cuenta(sesion) -> str:
    return sesion.client("sts", region_name=REGION).get_caller_identity()["Account"]


def _nombre_bucket(cuenta: str) -> str:
    return f"hlf-priorizacion-web-{cuenta}"


# --------------------------------------------------------------------------------------------- S3
def asegurar_bucket(s3, bucket: str) -> None:
    try:
        s3.head_bucket(Bucket=bucket)
        existe = True
    except ClientError:
        existe = False
    if not existe:
        # us-east-1 no admite LocationConstraint
        s3.create_bucket(Bucket=bucket)
        print(f"bucket creado: {bucket}")
    s3.put_public_access_block(Bucket=bucket, PublicAccessBlockConfiguration={
        "BlockPublicAcls": True, "IgnorePublicAcls": True, "BlockPublicPolicy": True, "RestrictPublicBuckets": True})
    try:
        s3.put_bucket_tagging(Bucket=bucket, Tagging={"TagSet": [TAG]})
    except ClientError as e:
        print(f"aviso: no se pudo etiquetar el bucket ({e.response['Error']['Code']})")


def subir_archivos(s3, bucket: str) -> list[str]:
    subidos = []
    for nombre, ctype in ARCHIVOS.items():
        f = WEB / nombre
        if not f.exists():
            raise FileNotFoundError(f"falta {f}; corre primero: python -m web.construir")
        s3.upload_file(str(f), bucket, nombre, ExtraArgs={"ContentType": ctype, "CacheControl": "no-cache"})
        subidos.append(nombre)
    print(f"subidos a s3://{bucket}/: {', '.join(subidos)}")
    return subidos


# --------------------------------------------------------------------------------------------- CloudFront + OAC
def _oac(cf) -> str | None:
    """Devuelve el Id de un Origin Access Control llamado hlf-priorizacion-web (lo crea si falta)."""
    nombre = "hlf-priorizacion-web-oac"
    for item in cf.list_origin_access_controls().get("OriginAccessControlList", {}).get("Items", []):
        if item["Name"] == nombre:
            return item["Id"]
    r = cf.create_origin_access_control(OriginAccessControlConfig={
        "Name": nombre, "Description": "OAC front HLF", "SigningProtocol": "sigv4",
        "SigningBehavior": "always", "OriginAccessControlOriginType": "s3"})
    return r["OriginAccessControl"]["Id"]


def _distribucion_existente(cf) -> dict | None:
    for d in cf.list_distributions().get("DistributionList", {}).get("Items", []):
        if d.get("Comment") == COMENTARIO_CF:
            return d
    return None


def desplegar_cloudfront(sesion, bucket: str) -> str:
    """Crea (o reutiliza) una distribución CloudFront con OAC apuntando al bucket privado. Devuelve la URL."""
    cf = sesion.client("cloudfront", region_name=REGION)
    s3 = sesion.client("s3", region_name=REGION)
    cuenta = _cuenta(sesion)
    dom_origen = f"{bucket}.s3.{REGION}.amazonaws.com"

    existente = _distribucion_existente(cf)
    if existente:
        dist_id, dominio = existente["Id"], existente["DomainName"]
        print(f"CloudFront ya existe: {dist_id}")
    else:
        oac_id = _oac(cf)
        ref = f"hlf-web-{int(time.time())}"
        cfg = {
            "CallerReference": ref, "Comment": COMENTARIO_CF, "Enabled": True,
            "DefaultRootObject": "index.html",
            "Origins": {"Quantity": 1, "Items": [{
                "Id": "s3-hlf-web", "DomainName": dom_origen,
                "S3OriginConfig": {"OriginAccessIdentity": ""},
                "OriginAccessControlId": oac_id}]},
            "DefaultCacheBehavior": {
                "TargetOriginId": "s3-hlf-web", "ViewerProtocolPolicy": "redirect-to-https",
                "AllowedMethods": {"Quantity": 2, "Items": ["GET", "HEAD"]},
                "Compress": True,
                "CachePolicyId": "658327ea-f89d-4fab-a63d-7e88639e58f6"},  # Managed-CachingOptimized
        }
        r = cf.create_distribution(DistributionConfig=cfg)
        dist_id, dominio = r["Distribution"]["Id"], r["Distribution"]["DomainName"]
        print(f"CloudFront creada: {dist_id}")

    # Política del bucket: solo esta distribución puede leer (OAC + condición de SourceArn)
    arn_dist = f"arn:aws:cloudfront::{cuenta}:distribution/{dist_id}"
    politica = {"Version": "2012-10-17", "Statement": [{
        "Sid": "AllowCloudFrontOAC", "Effect": "Allow", "Principal": {"Service": "cloudfront.amazonaws.com"},
        "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*",
        "Condition": {"StringEquals": {"AWS:SourceArn": arn_dist}}}]}
    s3.put_bucket_policy(Bucket=bucket, Policy=json.dumps(politica))

    # Invalidar caché para que tome los archivos recién subidos
    try:
        cf.create_invalidation(DistributionId=dist_id, InvalidationBatch={
            "Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": f"inv-{int(time.time())}"})
        print("invalidación de caché solicitada")
    except ClientError as e:
        print(f"aviso: no se pudo invalidar la caché ({e.response['Error']['Code']})")
    return f"https://{dominio}/"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--solo-subir", action="store_true", help="solo re-sube los 4 archivos (e invalida la caché)")
    a = ap.parse_args()

    sesion = boto3.Session(region_name=REGION)
    cuenta = _cuenta(sesion)
    bucket = _nombre_bucket(cuenta)
    s3 = sesion.client("s3", region_name=REGION)

    asegurar_bucket(s3, bucket)
    subir_archivos(s3, bucket)

    if a.solo_subir:
        # intentar invalidar si ya hay distribución
        cf = sesion.client("cloudfront", region_name=REGION)
        try:
            d = _distribucion_existente(cf)
            if d:
                cf.create_invalidation(DistributionId=d["Id"], InvalidationBatch={
                    "Paths": {"Quantity": 1, "Items": ["/*"]}, "CallerReference": f"inv-{int(time.time())}"})
                print(f"caché invalidada en {d['Id']}; URL: https://{d['DomainName']}/")
        except ClientError as e:
            print(f"aviso: {e.response['Error']['Code']}")
        return

    try:
        url = desplegar_cloudfront(sesion, bucket)
        print(f"\nURL del front (puede tardar ~15 min en propagar): {url}")
        print("La lista vigente muestra 423 pacientes (web/datos.js).")
    except ClientError as e:
        code = e.response["Error"]["Code"]
        print(f"\nCloudFront no disponible ({code}). Fallback: Lambda Function URL.", file=sys.stderr)
        from infra.desplegar_web_lambda import desplegar_lambda_url
        url = desplegar_lambda_url(sesion, bucket)
        print(f"\nURL del front (Lambda): {url}")


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    main()
