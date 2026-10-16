"""Carga el reporte del día y muestra qué cambió en la lista.

Uso diario (con los reportes de la carpeta Polo exportados a CSV):
  python ingesta.py --reporte <carpeta_del_reporte> --fecha 2026-10-14
      -> suma el reporte al almacén (data/almacen), recalcula y escribe salidas/cambios_<fecha>.csv

Demo con los datos del desafío (separa la semana del 14 al 20 de septiembre como si fuera un reporte):
  python ingesta.py --demo

El almacén recuerda la fecha de la última carga (almacen/estado.json), así el resumen compara siempre con
la lista de la carga anterior.
"""
import argparse
import json
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from motor import Datos, cargar_regla  # noqa: E402
from motor.cambios import cambios, resumen_para_equipo  # noqa: E402
from motor.ingesta import incorporar, leer_reporte, preparar_almacen, separar_periodo  # noqa: E402

DATASET = RAIZ / "data" / "dataset_hlf_ambulatorio"


def cargar_reporte(almacen: Path, reporte: Path, fecha: str, desde: str | None = None, verbose: bool = True):
    cfg = cargar_regla()
    estado_f = almacen / "estado.json"
    estado = json.loads(estado_f.read_text()) if estado_f.exists() else {}
    desde = desde or estado.get("ultima_fecha") or (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()
    tablas = leer_reporte(reporte)
    if not tablas:
        raise SystemExit(f"No hay archivos de reporte en {reporte}. Se esperan uno o más de: "
                         "eventos_clinicos.csv, mediciones.csv, citaciones.csv, indicaciones.csv, "
                         "lista_espera.csv, pacientes.csv")
    antes = Datos.cargar(almacen)
    try:
        agregadas = incorporar(almacen, tablas)
    except ValueError as e:
        raise SystemExit(str(e))
    despues = Datos.cargar(almacen)
    df, r = cambios(antes, despues, desde, fecha, cfg)
    salida = RAIZ / "salidas" / f"cambios_{fecha}.csv"
    salida.parent.mkdir(exist_ok=True)
    df.to_csv(salida, index=False)
    estado_f.write_text(json.dumps({"ultima_fecha": fecha}))
    texto, fuente = resumen_para_equipo(df, r)
    if verbose:
        print("Filas incorporadas: " + ", ".join(f"{k} {v}" for k, v in agregadas.items()))
        print(f"\nResumen ({fuente}):\n{texto}\n")
        print(f"Detalle en {salida}")
    return df, r, agregadas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reporte")
    ap.add_argument("--fecha")
    ap.add_argument("--desde", default=None)
    ap.add_argument("--almacen", default=str(RAIZ / "data" / "almacen"))
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()
    if a.demo:
        demo = RAIZ / "salidas" / "demo_ingesta"
        if demo.exists():
            shutil.rmtree(demo)
        separar_periodo(DATASET, "2026-09-13", "2026-09-20", demo / "almacen", demo / "reporte_2026-09-20")
        (demo / "almacen" / "estado.json").write_text(json.dumps({"ultima_fecha": "2026-09-13"}))
        print("Demo: almacén con datos hasta el 13-09-2026; reporte con lo ocurrido del 14 al 20 de septiembre.\n")
        cargar_reporte(demo / "almacen", demo / "reporte_2026-09-20", "2026-09-20")
        return
    if not (a.reporte and a.fecha):
        ap.error("indicar --reporte y --fecha, o usar --demo")
    almacen = preparar_almacen(a.almacen, DATASET)
    cargar_reporte(almacen, Path(a.reporte), a.fecha, a.desde)


if __name__ == "__main__":
    main()
