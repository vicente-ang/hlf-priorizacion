r"""Despliega la Lambda del corte del lunes (api/corte_web.py) SIN Docker, con EventBridge Scheduler.

Empaqueta en un zip el código del proyecto (motor, ia, web, api, data del hospital y propuestas) y PyYAML;
pandas/numpy vienen de la capa administrada AWSSDKPandas para Python 3.12. Crea (idempotente) la función
`hlf-priorizacion-corte` y un schedule `cron(0 7 ? * MON *)` en zona America/Santiago que la invoca los lunes.

Reglas de la cuenta compartida: solo recursos `hlf-...` con etiqueta proyecto=hlf-priorizacion; us-east-1; sin
usuarios/claves IAM nuevas (se intenta crear UN rol de ejecución para la Lambda; si no se permite, se documenta el
bloqueo y el resto queda listo).

Uso:
  . .\entorno.ps1
  python -m infra.desplegar_lambda_corte            # empaqueta, crea/actualiza la Lambda y el schedule
  python -m infra.desplegar_lambda_corte --invocar  # además la invoca una vez para publicar datos.js ahora
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import time
import zipfile
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

RAIZ = Path(__file__).resolve().parents[1]
REGION = "us-east-1"
TAG = {"proyecto": "hlf-priorizacion"}
NOMBRE = "hlf-priorizacion-corte"
SCHEDULE = "hlf-priorizacion-corte-lunes"
# Capa pública AWSSDKPandas (trae pandas y numpy) para Python 3.12 en us-east-1.
CAPA_PANDAS = "arn:aws:lambda:us-east-1:336392948345:layer:AWSSDKPandas-Python312:13"
# Carpetas/archivos del proyecto que necesita web.construir en tiempo de ejecución.
INCLUIR_DIRS = ["motor", "web", "api", "ia/rubrica"]
INCLUIR_DATA = ["data/dataset_hlf_ambulatorio", "data/fuentes_sinteticas"]
INCLUIR_IA_RES = ["propuestas_hlf.csv", "ciclo_bedrock.csv", "test_conteos_bedrock.csv", "test_final_bedrock.csv"]


def _agregar_dir(z: zipfile.ZipFile, carpeta: Path, base: Path) -> None:
    for f in sorted(carpeta.rglob("*")):
        if f.is_file() and "__pycache__" not in f.parts and f.suffix != ".pyc":
            z.write(f, f.relative_to(base).as_posix())


def construir_zip() -> bytes:
    """Zip con el código del proyecto, los datos del hospital, las propuestas y PyYAML."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for d in INCLUIR_DIRS:
            _agregar_dir(z, RAIZ / d, RAIZ)
        for d in INCLUIR_DATA:
            _agregar_dir(z, RAIZ / d, RAIZ)
        z.write(RAIZ / "ia" / "__init__.py", "ia/__init__.py")
        # módulos .py del nivel superior de ia/ que web.construir (y su cadena) importa (decisiones, etc.)
        for f in sorted((RAIZ / "ia").glob("*.py")):
            z.write(f, f"ia/{f.name}")
        for nombre in INCLUIR_IA_RES:
            f = RAIZ / "ia" / "resultados" / nombre
            if f.exists():
                z.write(f, f"ia/resultados/{nombre}")
        # PyYAML dentro del zip (pandas/numpy van en la capa)
        try:
            import yaml
            yml = Path(yaml.__file__).parent
            _agregar_dir(z, yml, yml.parent)
        except Exception as e:  # noqa: BLE001
            print(f"aviso: no se pudo empaquetar PyYAML ({e}); agrégalo si la Lambda falla al importar yaml")
    return buf.getvalue()


def _rol(sesion, bucket_web: str) -> str | None:
    iam = sesion.client("iam")
    nombre_rol = "hlf-priorizacion-corte-rol"
    confianza = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": ["lambda.amazonaws.com", "scheduler.amazonaws.com"]},
        "Action": "sts:AssumeRole"}]}
    politica = {"Version": "2012-10-17", "Statement": [
        {"Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject"], "Resource": f"arn:aws:s3:::{bucket_web}/*"},
        {"Effect": "Allow", "Action": "cloudfront:CreateInvalidation", "Resource": "*"},
        {"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": f"arn:aws:lambda:{REGION}:*:function:{NOMBRE}"},
        {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
         "Resource": "arn:aws:logs:*:*:*"}]}
    try:
        r = iam.create_role(RoleName=nombre_rol, AssumeRolePolicyDocument=json.dumps(confianza),
                            Tags=[{"Key": k, "Value": v} for k, v in TAG.items()])
        iam.put_role_policy(RoleName=nombre_rol, PolicyName="corte-web", PolicyDocument=json.dumps(politica))
        print(f"rol creado: {nombre_rol} (esperando propagación)")
        time.sleep(12)
        return r["Role"]["Arn"]
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code == "EntityAlreadyExists":
            iam.update_assume_role_policy(RoleName=nombre_rol, PolicyDocument=json.dumps(confianza))
            iam.put_role_policy(RoleName=nombre_rol, PolicyName="corte-web", PolicyDocument=json.dumps(politica))
            time.sleep(8)
            return iam.get_role(RoleName=nombre_rol)["Role"]["Arn"]
        print(f"BLOQUEO IAM: no se pudo crear el rol ({code}). La Lambda no se desplegará; "
              f"el resto del proyecto no depende de esto.", file=sys.stderr)
        return None


def desplegar(sesion, bucket_web: str, dist_id: str | None) -> str | None:
    arn_rol = _rol(sesion, bucket_web)
    if not arn_rol:
        return None
    lam = sesion.client("lambda", region_name=REGION)
    paquete = construir_zip()
    print(f"zip de la Lambda: {len(paquete) / 1024:.0f} KB")
    env = {"Variables": {"BUCKET_WEB": bucket_web, **({"DISTRIBUTION_ID": dist_id} if dist_id else {})}}
    try:
        lam.create_function(FunctionName=NOMBRE, Runtime="python3.12", Role=arn_rol,
                            Handler="api.corte_web.lambda_handler", Code={"ZipFile": paquete}, Timeout=120,
                            MemorySize=1024, Layers=[CAPA_PANDAS], Environment=env, Tags=TAG)
        print(f"Lambda creada: {NOMBRE}")
        time.sleep(6)
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceConflictException":
            lam.update_function_code(FunctionName=NOMBRE, ZipFile=paquete)
            time.sleep(4)
            lam.update_function_configuration(FunctionName=NOMBRE, Layers=[CAPA_PANDAS], Environment=env,
                                              Timeout=120, MemorySize=1024, Runtime="python3.12",
                                              Handler="api.corte_web.lambda_handler")
            print(f"Lambda actualizada: {NOMBRE}")
        else:
            raise
    arn = lam.get_function(FunctionName=NOMBRE)["Configuration"]["FunctionArn"]
    _schedule(sesion, arn_rol, arn)
    return arn


def _schedule(sesion, arn_rol: str, arn_fn: str) -> None:
    """EventBridge Scheduler: lunes 07:00 America/Santiago. Permite que el scheduler invoque la Lambda."""
    sch = sesion.client("scheduler", region_name=REGION)
    objetivo = {"Arn": arn_fn, "RoleArn": arn_rol, "Input": json.dumps({})}
    try:
        sch.create_schedule(Name=SCHEDULE, ScheduleExpression="cron(0 7 ? * MON *)",
                            ScheduleExpressionTimezone="America/Santiago",
                            FlexibleTimeWindow={"Mode": "OFF"}, Target=objetivo,
                            State="ENABLED")
        print(f"schedule creado: {SCHEDULE} (lunes 07:00 America/Santiago)")
    except ClientError as e:
        if e.response["Error"]["Code"] == "ConflictException":
            sch.update_schedule(Name=SCHEDULE, ScheduleExpression="cron(0 7 ? * MON *)",
                                ScheduleExpressionTimezone="America/Santiago",
                                FlexibleTimeWindow={"Mode": "OFF"}, Target=objetivo, State="ENABLED")
            print(f"schedule actualizado: {SCHEDULE}")
        else:
            print(f"aviso: no se pudo crear el schedule ({e.response['Error']['Code']}); "
                  f"la Lambda queda lista para invocarse a mano o por otro trigger.", file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--invocar", action="store_true", help="invoca la Lambda una vez al terminar")
    a = ap.parse_args()
    sesion = boto3.Session(region_name=REGION)
    cuenta = sesion.client("sts").get_caller_identity()["Account"]
    bucket_web = f"hlf-priorizacion-web-{cuenta}"
    # buscar la distribución CloudFront del front (comentario hlf-priorizacion-web)
    dist_id = None
    try:
        cf = sesion.client("cloudfront", region_name=REGION)
        for d in cf.list_distributions().get("DistributionList", {}).get("Items", []):
            if d.get("Comment") == "hlf-priorizacion-web":
                dist_id = d["Id"]
    except ClientError:
        pass
    arn = desplegar(sesion, bucket_web, dist_id)
    if not arn:
        print("Despliegue incompleto por bloqueo de IAM (documentado). Nada más que hacer.")
        return
    print(f"\nLambda: {arn}\nSchedule: {SCHEDULE} · cron(0 7 ? * MON *) America/Santiago\nBucket web: {bucket_web}"
          f"\nCloudFront: {dist_id or 'no encontrada'}")
    if a.invocar:
        lam = sesion.client("lambda", region_name=REGION)
        r = lam.invoke(FunctionName=NOMBRE, Payload=json.dumps({}).encode())
        print("invocación:", r["StatusCode"], r["Payload"].read().decode("utf-8")[:400])


if __name__ == "__main__":
    sys.path.insert(0, str(RAIZ))
    main()
