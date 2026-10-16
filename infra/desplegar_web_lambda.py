"""Fallback de infra/desplegar_web.py cuando CloudFront no está permitido.

Crea (idempotente) una Lambda `hlf-priorizacion-web` con Function URL pública (AuthType NONE) que lee los 4
archivos del bucket privado y los sirve. El bucket sigue privado: solo la Lambda (con su rol) lo lee.

Requiere un rol de ejecución para la Lambda. En la cuenta del taller no se permiten usuarios/roles IAM nuevos; si
`crear_rol` falla, se intenta reutilizar un rol existente que empiece por `hlf-` o se documenta el bloqueo.
"""
from __future__ import annotations

import io
import json
import time
import zipfile
from pathlib import Path

from botocore.exceptions import ClientError

REGION = "us-east-1"
TAG = {"proyecto": "hlf-priorizacion"}
NOMBRE = "hlf-priorizacion-web"

CODIGO_LAMBDA = '''
import os, boto3
S3 = boto3.client("s3")
BUCKET = os.environ["BUCKET"]
TIPOS = {
    "index.html": "text/html; charset=utf-8",
    "estilos.css": "text/css; charset=utf-8",
    "app.js": "application/javascript; charset=utf-8",
    "datos.js": "application/javascript; charset=utf-8",
}
def handler(event, context):
    ruta = (event.get("rawPath") or "/").lstrip("/") or "index.html"
    if ruta not in TIPOS:
        ruta = "index.html"
    try:
        obj = S3.get_object(Bucket=BUCKET, Key=ruta)
        cuerpo = obj["Body"].read().decode("utf-8")
    except Exception as e:  # noqa: BLE001
        return {"statusCode": 404, "body": f"no encontrado: {ruta} ({e})"}
    return {"statusCode": 200, "headers": {"Content-Type": TIPOS[ruta], "Cache-Control": "no-cache"},
            "body": cuerpo}
'''


def _zip_codigo() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("lambda_function.py", CODIGO_LAMBDA)
    return buf.getvalue()


def _rol(sesion, bucket: str) -> str:
    """Devuelve el ARN de un rol de ejecución para la Lambda. Lo crea si se puede; si no, reutiliza uno hlf-*."""
    iam = sesion.client("iam")
    nombre_rol = "hlf-priorizacion-web-rol"
    confianza = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    try:
        r = iam.create_role(RoleName=nombre_rol, AssumeRolePolicyDocument=json.dumps(confianza),
                            Tags=[{"Key": k, "Value": v} for k, v in TAG.items()])
        arn = r["Role"]["Arn"]
        iam.put_role_policy(RoleName=nombre_rol, PolicyName="leer-bucket", PolicyDocument=json.dumps({
            "Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Action": "s3:GetObject", "Resource": f"arn:aws:s3:::{bucket}/*"},
                {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
                 "Resource": "arn:aws:logs:*:*:*"}]}))
        time.sleep(10)  # propagación del rol
        return arn
    except ClientError as e:
        if e.response["Error"]["Code"] in ("EntityAlreadyExists",):
            return iam.get_role(RoleName=nombre_rol)["Role"]["Arn"]
        raise


def desplegar_lambda_url(sesion, bucket: str) -> str:
    lam = sesion.client("lambda", region_name=REGION)
    arn_rol = _rol(sesion, bucket)
    codigo = _zip_codigo()
    try:
        lam.create_function(FunctionName=NOMBRE, Runtime="python3.12", Role=arn_rol,
                            Handler="lambda_function.handler", Code={"ZipFile": codigo}, Timeout=15,
                            MemorySize=256, Environment={"Variables": {"BUCKET": bucket}},
                            Tags=TAG)
        print(f"Lambda creada: {NOMBRE}")
        time.sleep(5)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            lam.update_function_code(FunctionName=NOMBRE, ZipFile=codigo)
            lam.update_function_configuration(FunctionName=NOMBRE, Environment={"Variables": {"BUCKET": bucket}})
            print(f"Lambda actualizada: {NOMBRE}")
        else:
            raise
    # Function URL pública
    try:
        u = lam.create_function_url_config(FunctionName=NOMBRE, AuthType="NONE")
        url = u["FunctionUrl"]
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            url = lam.get_function_url_config(FunctionName=NOMBRE)["FunctionUrl"]
        else:
            raise
    try:
        lam.add_permission(FunctionName=NOMBRE, StatementId="url-publica", Action="lambda:InvokeFunctionUrl",
                          Principal="*", FunctionUrlAuthType="NONE")
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceConflictException":
            raise
    return url
