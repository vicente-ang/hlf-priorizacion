"""Revisa una carpeta de datos ANTES de usarla con el motor (por ejemplo, el archivo real del hospital).

Uso:  python validar_datos.py [carpeta]        (por defecto data/dataset_hlf_ambulatorio)

Revisa archivos, columnas, fechas, valores de las categorías e integridad entre tablas, y dice qué
corregir. Termina con código 1 si hay errores que impiden usar los datos.
Qué es error y qué es advertencia:
  ERROR        el motor no puede funcionar o ordenaría mal (falta una columna, fechas ilegibles,
               prioridad desconocida).
  ADVERTENCIA  funciona, pero algo se pierde (un subtipo de evento desconocido no abre un plazo
               moderado; una medición sin reglas de tendencia solo cuenta si está fuera de rango).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

RAIZ = Path(__file__).resolve().parent
ESQUEMA = {
    "pacientes.csv": ["id_paciente", "edad", "sexo", "comuna", "prevision", "nivel_socioeconomico",
                      "fallecido", "fecha_defuncion"],
    "lista_espera.csv": ["id_paciente", "especialidad", "sub_especialidad", "diagnostico_cie10", "diagnostico_texto",
                         "prioridad_inicial", "fecha_ingreso_lista", "origen_derivacion", "estado"],
    "eventos_clinicos.csv": ["id_paciente", "fecha_evento", "tipo_evento", "subtipo", "severidad"],
    "mediciones.csv": ["id_paciente", "fecha_medicion", "tipo_medicion", "valor", "unidad", "fuera_de_rango"],
    "citaciones.csv": ["id_paciente", "fecha_cita", "estado_cita"],
}
OPCIONALES = {"agenda_box.csv": ["id_box", "fecha", "especialidad", "capacidad_cupos"],
              "indicaciones.csv": ["id_paciente", "fecha_indicacion", "texto"]}
FECHAS = {"pacientes.csv": ["fecha_defuncion"], "lista_espera.csv": ["fecha_ingreso_lista"],
          "eventos_clinicos.csv": ["fecha_evento"], "mediciones.csv": ["fecha_medicion"],
          "citaciones.csv": ["fecha_cita"], "agenda_box.csv": ["fecha"], "indicaciones.csv": ["fecha_indicacion"]}


def validar(carpeta: str | Path) -> tuple[list[str], list[str]]:
    d = Path(carpeta)
    errores, avisos = [], []
    regla = yaml.safe_load(open(RAIZ / "motor" / "config" / "regla.yaml", encoding="utf-8"))
    tablas = {}

    for nombre, cols in {**ESQUEMA, **OPCIONALES}.items():
        ruta = d / nombre
        if not ruta.exists():
            if nombre in ESQUEMA:
                errores.append(f"Falta el archivo {nombre}.")
            elif nombre == "agenda_box.csv":
                avisos.append("No hay agenda_box.csv: la lista funciona, pero la simulación no.")
            continue
        try:
            df = pd.read_csv(ruta, dtype=str)
        except Exception as e:
            errores.append(f"No se pudo leer {nombre}: {e}")
            continue
        faltan = [c for c in cols if c not in df.columns]
        if faltan:
            errores.append(f"{nombre}: faltan columnas {faltan}. Columnas encontradas: {list(df.columns)}. "
                           "Si existen con otro nombre, renombrarlas.")
        for c in FECHAS.get(nombre, []):
            if c in df.columns:
                v = df[c].dropna()
                malas = pd.to_datetime(v, errors="coerce", format="mixed").isna().sum()
                if malas:
                    errores.append(f"{nombre}: {malas} valores de {c} no son fechas (formato esperado AAAA-MM-DD). "
                                   f"Ejemplos: {v[pd.to_datetime(v, errors='coerce', format='mixed').isna()].head(3).tolist()}")
        tablas[nombre] = df

    le, ev, me = tablas.get("lista_espera.csv"), tablas.get("eventos_clinicos.csv"), tablas.get("mediciones.csv")
    pa = tablas.get("pacientes.csv")
    if le is not None and "prioridad_inicial" in le:
        raras = sorted(set(le.prioridad_inicial.dropna().str.strip().str.lower()) - set(regla["plazo"]["base_dias"]))
        if raras:
            errores.append(f"lista_espera.csv: prioridades desconocidas {raras}. Se esperan alta, media o baja "
                           "(si el hospital usa 'normal/prioritario', mapear prioritario→alta y normal→media o baja).")
        if "id_paciente" in le and le.id_paciente.duplicated().any():
            avisos.append(f"lista_espera.csv: {int(le.id_paciente.duplicated().sum())} pacientes aparecen más de una vez; "
                          "el motor usa una solicitud por paciente (la última leída).")
    if ev is not None and "severidad" in ev:
        raras = sorted(set(ev.severidad.dropna().str.strip().str.lower()) - {"leve", "moderada", "grave"})
        if raras:
            errores.append(f"eventos_clinicos.csv: severidades desconocidas {raras}. Se esperan leve, moderada o grave.")
        conocidos = set(regla["senales"]["subtipos_mejora"]) | set(regla["senales"]["subtipos_rutina"]) | {
            "ingreso UCI", "ingreso hospitalario", "triage ESI 2", "descompensación grave", "descompensación",
            "resultado alterado", "aumento dosis"}
        nuevos = sorted(set(ev.subtipo.dropna()) - conocidos) if "subtipo" in ev else []
        if nuevos:
            avisos.append(f"eventos_clinicos.csv: subtipos nuevos {nuevos[:8]}{'…' if len(nuevos) > 8 else ''}. "
                          "Igual cuentan por su severidad; si alguno es una MEJORA, agregarlo a "
                          "senales.subtipos_mejora en motor/config/regla.yaml.")
    if me is not None and "tipo_medicion" in me:
        sin_regla = sorted(set(me.tipo_medicion.dropna()) - set(regla["mediciones"]["tipos"]))
        if sin_regla:
            avisos.append(f"mediciones.csv: tipos sin regla de tendencia {sin_regla}. Cuentan si están fuera de "
                          "rango; para detectar empeoramiento, agregarlos en mediciones.tipos de regla.yaml.")
        if "valor" in me:
            no_num = pd.to_numeric(me.valor, errors="coerce").isna().sum()
            if no_num:
                errores.append(f"mediciones.csv: {no_num} valores no numéricos en 'valor'.")
    if le is not None and pa is not None and "id_paciente" in le and "id_paciente" in pa:
        sin_ficha = set(le.id_paciente) - set(pa.id_paciente)
        if sin_ficha:
            errores.append(f"{len(sin_ficha)} pacientes de lista_espera.csv no están en pacientes.csv.")
        for nombre in ("eventos_clinicos.csv", "mediciones.csv", "citaciones.csv"):
            t = tablas.get(nombre)
            if t is not None and "id_paciente" in t:
                huerf = int((~t.id_paciente.isin(le.id_paciente)).sum())
                if huerf:
                    avisos.append(f"{nombre}: {huerf} filas de pacientes que no están en la lista de espera (se ignoran).")
    if le is not None and ev is not None and {"id_paciente", "fecha_ingreso_lista"} <= set(le) and \
            {"id_paciente", "fecha_evento"} <= set(ev):
        m = ev.merge(le[["id_paciente", "fecha_ingreso_lista"]], on="id_paciente")
        antes = int((pd.to_datetime(m.fecha_evento, errors="coerce") < pd.to_datetime(m.fecha_ingreso_lista, errors="coerce")).sum())
        if antes:
            avisos.append(f"eventos_clinicos.csv: {antes} eventos son anteriores al ingreso a la lista. Se usan igual "
                          "(un evento grave reciente cuenta aunque sea previo al ingreso).")
    if le is not None and "prioridad_inicial" in le:
        sin = int((~le.prioridad_inicial.astype(str).str.strip().str.lower().isin(["alta", "media", "baja"])).sum())
        if sin:
            avisos.append(f"lista_espera.csv: {sin} interconsultas sin prioridad del especialista. Esperan con plazo "
                          "medio y a las 3 semanas usan la prioridad que propone la guía (motor/guias.py), a confirmar.")
    # Otras fuentes (Tálamo hospitalizado/urgencia, ACG, Rayen, interconsultas), si vienen en fuentes/
    from motor.fuentes import ESQUEMAS
    cf = Path(carpeta) / "fuentes"
    if cf.is_dir():
        for nombre, cols in ESQUEMAS.items():
            f = cf / nombre
            if not f.exists():
                continue
            t = pd.read_csv(f, dtype=str, nrows=5)
            faltan = [c for c in cols if c not in t.columns and not (c == "id_paciente" and "rut" in t.columns)]
            if faltan:
                errores.append(f"fuentes/{nombre}: faltan columnas {faltan}")
    return errores, avisos


def main():
    carpeta = sys.argv[1] if len(sys.argv) > 1 else RAIZ / "data" / "dataset_hlf_ambulatorio"
    errores, avisos = validar(carpeta)
    print(f"Revisión de {carpeta}\n")
    for e in errores:
        print(f"ERROR        {e}")
    for a in avisos:
        print(f"ADVERTENCIA  {a}")
    if not errores and not avisos:
        print("Todo en orden: los datos se pueden usar con el motor.")
    elif not errores:
        print("\nSin errores: los datos se pueden usar. Revisar las advertencias.")
    else:
        print(f"\n{len(errores)} error(es): corregir antes de usar los datos.")
    sys.exit(1 if errores else 0)


if __name__ == "__main__":
    main()
