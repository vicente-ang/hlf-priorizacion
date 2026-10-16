"""Genera la lista de trabajo priorizada a una fecha de corte.

Uso:
  python priorizar.py                                     # fecha más reciente de los datos, regla MVP
  python priorizar.py --especialidad Cardiología --top 15
  python priorizar.py --modo puntaje                      # modo opcional con pesos a mano (v1)
  python priorizar.py --modo actual                       # la regla actual del hospital, para comparar
  python priorizar.py --agenda 2026-10-13                 # además: agenda propuesta y lista de llamadas del día

Escribe salidas/lista_priorizada_<corte>.csv (insumo para la interfaz). Con --agenda, también
salidas/agenda_<día>.csv y salidas/llamadas_<día>.csv (se abren en Excel).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from motor import MODOS, Datos, cargar_regla, priorizar  # noqa: E402
from motor.agenda import llamadas_del_dia, proponer_agenda  # noqa: E402
from motor.exportar import a_csv, agenda_para_exportar, llamadas_para_exportar  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", default=None, help="fecha de la lista (por defecto, la más reciente de los datos)")
    ap.add_argument("--especialidad", default=None)
    ap.add_argument("--modo", default=None, choices=MODOS, help="por defecto el de motor/config/regla.yaml")
    ap.add_argument("--top", type=int, default=None, help="cuántos mostrar por especialidad (por defecto 3, o 15 si filtra)")
    ap.add_argument("--datos", default=None, help="carpeta con los CSV (por defecto data/dataset_hlf_ambulatorio)")
    ap.add_argument("--regla", default=None, help="archivo de regla (por defecto motor/config/regla.yaml)")
    ap.add_argument("--agenda", default=None, metavar="DÍA",
                    help="día de agenda (AAAA-MM-DD): escribe la agenda propuesta y la lista de llamadas")
    ap.add_argument("--salida", default=None, help="carpeta donde escribir (por defecto salidas/)")
    a = ap.parse_args()
    if a.agenda:
        try:
            date.fromisoformat(a.agenda)
        except ValueError:
            sys.exit(f"--agenda debe ser una fecha AAAA-MM-DD (llegó '{a.agenda}').")

    datos, cfg = Datos.cargar(a.datos), cargar_regla(a.regla)
    a.corte = a.corte or datos.fecha_referencia().isoformat()
    modo = a.modo or cfg.get("modo_por_defecto", "carril_plazo")
    especialidades = sorted({p.especialidad for p in datos.pacientes.values()})
    if a.especialidad and a.especialidad not in especialidades:
        sys.exit(f"No existe la especialidad '{a.especialidad}'. Opciones: {', '.join(especialidades)}")
    df = priorizar(datos, a.corte, cfg, modo=modo, especialidad=a.especialidad)
    if df.empty:
        sys.exit(f"No hay pacientes en espera al {a.corte}" + (f" en {a.especialidad}" if a.especialidad else "") + ".")

    carpeta = Path(a.salida) if a.salida else Path(__file__).resolve().parent / "salidas"
    salida = carpeta / f"lista_priorizada_{a.corte}.csv"
    salida.parent.mkdir(parents=True, exist_ok=True)
    cols = ["especialidad", "puesto", "en_especialidad", "puesto_regla_actual", "cambio_puestos", "motivo_puesto",
            "id_paciente", "prioridad_inicial", "dias_espera", "carril_rapido", "motivo_carril",
            "fecha_objetivo", "plazo_dias", "motivo_plazo", "dias_atraso", "razon_atraso",
            "senales_deterioro", "senales_mejora", "alerta_contacto", "verificar_estado", "dias_sin_datos",
            "modo", "version_regla"]
    if modo == "puntaje":
        cols += ["puntaje", "base", "espera", "eventos", "mediciones", "top_razones"]
    out = df[cols].copy()
    for c in ("senales_deterioro", "senales_mejora", "top_razones"):
        if c in out:
            out[c] = out[c].apply(lambda xs: " | ".join(xs))
    out.to_csv(salida, index=False)

    print(f"Lista al {a.corte} · modo {modo}: {len(df)} pacientes en espera · "
          f"{int(df['carril_rapido'].sum())} en carril rápido · {int(df['alerta_contacto'].notna().sum())} con alerta de contacto")
    print(f"Guardada en {salida}\n")
    top = a.top or (15 if a.especialidad else 3)
    for esp, g in df.groupby("especialidad"):
        print(f"{esp} ({len(g)} en espera)")
        for r in g.head(top).itertuples():
            print(f"  {r.puesto:>3}. {r.id_paciente}  {r.prioridad_inicial:<5} {r.dias_espera:>3} d  "
                  f"[{r.motivo_puesto}]  (regla actual: #{r.puesto_regla_actual})")
            detalle = r.motivo_carril if r.carril_rapido else f"{r.motivo_plazo}; atraso {r.dias_atraso} d"
            print(f"       {detalle}")
        print()
    if a.agenda:
        agenda(datos, cfg, a.agenda, modo, a.especialidad, salida.parent)


def agenda(datos, cfg, dia, modo, especialidad, carpeta):
    if datos.agenda is None or not len(datos.agenda):
        sys.exit("Para proponer la agenda se necesita agenda_box.csv en la carpeta de datos.")
    lista = priorizar(datos, dia, cfg, modo=modo, especialidad=especialidad)
    prop = proponer_agenda(datos, dia, cfg, especialidad=especialidad, lista=lista)
    if not prop["resumen"]["bloques"]:
        sys.exit(f"No hay bloques de box el {dia}" + (f" en {especialidad}" if especialidad else "") + ".")
    llamadas = llamadas_del_dia(prop, lista)
    (carpeta / f"agenda_{dia}.csv").write_bytes(a_csv(agenda_para_exportar(prop)))
    (carpeta / f"llamadas_{dia}.csv").write_bytes(a_csv(llamadas_para_exportar(llamadas)))
    r = prop["resumen"]
    print(f"Agenda del {dia}: {r['bloques']} bloques, {r['cupos']} cupos, {r['citados']} citados "
          f"({r['sobrecupos']} en sobrecupo), {len(llamadas)} llamadas ({r['reserva']} de reserva)."
          + (f" La lista no alcanza para {r['cupos_sin_paciente']} cupos." if r["cupos_sin_paciente"] else ""))
    print(f"Guardadas en {carpeta / f'agenda_{dia}.csv'} y {carpeta / f'llamadas_{dia}.csv'}")


if __name__ == "__main__":
    main()
