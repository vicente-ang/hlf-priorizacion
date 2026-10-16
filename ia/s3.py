"""Sincronización mínima con S3 para el agente IA del HLF.

Sube/baja carpetas locales a un prefijo de S3. Se usa para publicar la rúbrica vigente y los resultados del
agente (propuestas, bitácora del ciclo, resumen) al bucket del stack (`ReportesBucket` de infra/template.yaml) o a
cualquier bucket indicado con la variable `HLF_BUCKET`.

Regla de fuga: NUNCA se suben las carpetas `data/mundo/*_verdad` al prefijo que lee el agente. `subir_mundo` filtra
explícitamente esos directorios.

Uso:
  python -m ia.s3 subir  --bucket mi-bucket            # sube ia/rubrica, ia/resultados y data/mundo (sin *_verdad)
  python -m ia.s3 bajar  --bucket mi-bucket --prefijo ia/resultados --destino ia/resultados
Variables: HLF_BUCKET (bucket por defecto), AWS_REGION.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def _cliente(region: str | None = None):
    import boto3
    return boto3.client("s3", region_name=region or os.environ.get("AWS_REGION"))


def _bucket(nombre: str | None) -> str:
    b = nombre or os.environ.get("HLF_BUCKET")
    if not b:
        raise RuntimeError("Falta el bucket: pásalo con --bucket o la variable HLF_BUCKET")
    return b


def subir(carpeta_local: str | Path, bucket: str | None = None, prefijo: str = "ia", region: str | None = None,
          excluir: tuple[str, ...] = ()) -> list[str]:
    """Sube recursivamente `carpeta_local` a s3://<bucket>/<prefijo>/<carpeta_local.name>/...
    Devuelve las claves subidas. `excluir`: subcadenas de ruta que se omiten (p. ej. '_verdad')."""
    cli, b = _cliente(region), _bucket(bucket)
    base = Path(carpeta_local)
    subidas = []
    for f in sorted(base.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(base).as_posix()
        ruta_rel = f"{base.name}/{rel}"
        if any(x in ruta_rel for x in excluir):
            continue
        clave = f"{prefijo}/{ruta_rel}"
        cli.upload_file(str(f), b, clave)
        subidas.append(clave)
    return subidas


def bajar(bucket: str | None = None, prefijo: str = "ia", destino: str | Path = ".", region: str | None = None) -> list[str]:
    """Baja todos los objetos bajo s3://<bucket>/<prefijo> a `destino`, conservando la estructura."""
    cli, b = _cliente(region), _bucket(bucket)
    destino = Path(destino)
    paginador = cli.get_paginator("list_objects_v2")
    bajadas = []
    for pag in paginador.paginate(Bucket=b, Prefix=prefijo):
        for obj in pag.get("Contents", []):
            clave = obj["Key"]
            local = destino / clave
            local.parent.mkdir(parents=True, exist_ok=True)
            cli.download_file(b, clave, str(local))
            bajadas.append(clave)
    return bajadas


def subir_estandar(bucket: str | None = None, region: str | None = None) -> list[str]:
    """Sube lo que K4 pide: ia/rubrica, ia/resultados y data/mundo (sin ninguna carpeta *_verdad)."""
    claves = []
    claves += subir(RAIZ / "ia" / "rubrica", bucket, "ia", region)
    claves += subir(RAIZ / "ia" / "resultados", bucket, "ia", region)
    claves += subir(RAIZ / "data" / "mundo", bucket, "ia", region, excluir=("_verdad/",))
    return claves


def listar(bucket: str | None = None, prefijo: str = "ia", region: str | None = None) -> list[str]:
    cli, b = _cliente(region), _bucket(bucket)
    paginador = cli.get_paginator("list_objects_v2")
    return [o["Key"] for pag in paginador.paginate(Bucket=b, Prefix=prefijo) for o in pag.get("Contents", [])]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("accion", choices=["subir", "bajar", "listar"])
    ap.add_argument("--bucket")
    ap.add_argument("--prefijo", default="ia")
    ap.add_argument("--carpeta", help="carpeta local a subir (si no, sube el conjunto estándar de K4)")
    ap.add_argument("--destino", default=".")
    a = ap.parse_args()
    if a.accion == "subir":
        claves = subir(a.carpeta, a.bucket, a.prefijo) if a.carpeta else subir_estandar(a.bucket)
        print(f"{len(claves)} objetos subidos a s3://{_bucket(a.bucket)}/")
    elif a.accion == "bajar":
        claves = bajar(a.bucket, a.prefijo, a.destino)
        print(f"{len(claves)} objetos bajados desde s3://{_bucket(a.bucket)}/{a.prefijo}")
    else:
        for k in listar(a.bucket, a.prefijo):
            print(k)


if __name__ == "__main__":
    sys.exit(main())
