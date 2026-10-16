"""Carga del reporte diario: incorpora filas nuevas al almacén de datos sin duplicar.

El hospital no tiene APIs hacia la ficha clínica; trabaja con reportes diarios en la carpeta Polo. Este
módulo toma una carpeta de reporte con cualquiera de estos archivos (solo las filas nuevas) y los suma al
almacén:

  eventos_clinicos.csv   urgencias, hospitalizaciones, exámenes alterados, cambios de fármaco
  mediciones.csv         presión, glicemia, PHQ-9, etc.
  citaciones.csv         resultado de las citas (asistió, no asistió, reprogramó, canceló)
  indicaciones.csv       lo que indicó el médico en el control (texto y/o columnas estructuradas)
  lista_espera.csv       interconsultas nuevas o cambios de estado (se actualiza por id_paciente)
  pacientes.csv          pacientes nuevos o defunciones (se actualiza por id_paciente)

Además puede traer los reportes de las otras fuentes (motor/fuentes.py): talamo_hospitalizaciones.csv,
talamo_urgencias.csv, acg_estratificacion.csv, rayen_diagnosticos_cronicos.csv e interconsultas.csv. Esos se
guardan en almacen/fuentes/ y se unen al cargar los datos.

Las columnas mínimas son las de validar_datos.py y motor/fuentes.py. Una fila que ya está en el almacén no se
duplica, así que cargar dos veces el mismo reporte no cambia nada.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

# archivo: (columnas que identifican una fila, ¿actualizar si ya existe?)
CLAVES = {
    "eventos_clinicos.csv": (["id_paciente", "fecha_evento", "tipo_evento", "subtipo"], False),
    "mediciones.csv": (["id_paciente", "fecha_medicion", "tipo_medicion", "valor"], False),
    "citaciones.csv": (["id_paciente", "fecha_cita", "especialidad"], True),
    "indicaciones.csv": (["id_paciente", "fecha_indicacion"], True),
    "lista_espera.csv": (["id_paciente"], True),
    "pacientes.csv": (["id_paciente"], True),
}
# Reportes de otras fuentes: se guardan en almacen/fuentes/
CLAVES_FUENTES = {
    "talamo_hospitalizaciones.csv": (["id_paciente", "fecha_ingreso"], True),
    "talamo_urgencias.csv": (["id_paciente", "fecha_atencion", "categoria_esi"], False),
    "acg_estratificacion.csv": (["id_paciente", "fecha_estratificacion"], True),
    "rayen_diagnosticos_cronicos.csv": (["id_paciente", "diagnostico_cie10"], False),
    "interconsultas.csv": (["id_paciente"], True),
}
FECHA_FUENTES = {"talamo_hospitalizaciones.csv": "fecha_ingreso", "talamo_urgencias.csv": "fecha_atencion",
                 "acg_estratificacion.csv": "fecha_estratificacion", "rayen_diagnosticos_cronicos.csv": "fecha_registro",
                 "interconsultas.csv": "fecha_ingreso_lista"}
TODAS = {**CLAVES, **CLAVES_FUENTES}


def preparar_almacen(almacen: str | Path, origen: str | Path) -> Path:
    """Crea el almacén copiando la carpeta de origen, si aún no existe."""
    almacen = Path(almacen)
    if not almacen.exists():
        shutil.copytree(origen, almacen, ignore=shutil.ignore_patterns("*.md", "*.json"))
        from .fuentes import carpeta_fuentes
        cf = carpeta_fuentes(Path(origen))
        if cf is not None and not (almacen / "fuentes").exists():
            shutil.copytree(cf, almacen / "fuentes", ignore=shutil.ignore_patterns("*.md"))
    return almacen


def leer_reporte(carpeta: str | Path) -> dict[str, pd.DataFrame]:
    carpeta = Path(carpeta)
    return {n: pd.read_csv(carpeta / n, dtype=str) for n in TODAS if (carpeta / n).exists()}


def revisar_reporte(tablas: dict[str, pd.DataFrame]) -> list[str]:
    """Errores de columnas que impiden incorporar el reporte."""
    from validar_datos import ESQUEMA, OPCIONALES
    from .fuentes import ESQUEMAS
    errores = []
    for nombre, df in tablas.items():
        cols = {**ESQUEMA, **OPCIONALES, **ESQUEMAS}.get(nombre, [])
        if nombre in ESQUEMAS and "id_paciente" not in df.columns and "rut" in df.columns:
            cols = [c for c in cols if c != "id_paciente"]
        faltan = [c for c in cols if c not in df.columns]
        if nombre == "indicaciones.csv":   # el texto es opcional si vienen columnas estructuradas
            faltan = [c for c in faltan if c != "texto"]
        if faltan:
            errores.append(f"{nombre}: faltan columnas {faltan}")
    return errores


def incorporar(almacen: str | Path, tablas: dict[str, pd.DataFrame]) -> dict[str, int]:
    """Suma las filas del reporte al almacén. Devuelve cuántas filas nuevas o actualizadas hubo por archivo."""
    almacen = Path(almacen)
    errores = revisar_reporte(tablas)
    if errores:
        raise ValueError("El reporte no se puede incorporar: " + "; ".join(errores))
    resultado = {}
    for nombre, nuevo in tablas.items():
        claves, actualizar = TODAS[nombre]
        if nombre in CLAVES_FUENTES:
            from .fuentes import _ids
            nuevo = _ids(nuevo)
            (almacen / "fuentes").mkdir(exist_ok=True)
        ruta = almacen / "fuentes" / nombre if nombre in CLAVES_FUENTES else almacen / nombre
        actual = pd.read_csv(ruta, dtype=str) if ruta.exists() else pd.DataFrame(columns=nuevo.columns)
        clave = lambda df: df[claves].astype(str).agg("|".join, axis=1)  # noqa: E731
        ya = set(clave(actual)) if len(actual) else set()
        k_nuevo = clave(nuevo)
        nuevas = nuevo[~k_nuevo.isin(ya)]
        if actualizar:
            existentes = nuevo[k_nuevo.isin(ya)]
            comunes = [c for c in nuevo.columns if c in actual.columns]
            filas_actuales = set(actual[comunes].fillna("").astype(str).agg("|".join, axis=1)) if len(actual) else set()
            distintas = existentes[~existentes[comunes].fillna("").astype(str).agg("|".join, axis=1).isin(filas_actuales)]
            if len(existentes):
                actual = actual[~clave(actual).isin(set(clave(existentes)))]
            combinado = pd.concat([actual, nuevo.drop_duplicates(subset=claves, keep="last")], ignore_index=True)
            resultado[nombre] = len(nuevas) + len(distintas)
        else:
            combinado = pd.concat([actual, nuevas.drop_duplicates(subset=claves)], ignore_index=True)
            resultado[nombre] = len(nuevas.drop_duplicates(subset=claves))
        combinado.to_csv(ruta, index=False)
    return resultado


def separar_periodo(origen: str | Path, desde: str, hasta: str, base: str | Path, reporte: str | Path) -> None:
    """Para la demo: parte un dataset en una base (hasta `desde`) y un reporte con lo ocurrido entre
    `desde` (excluido) y `hasta` (incluido). Así se puede mostrar la carga de un reporte con datos reales."""
    origen, base, reporte = Path(origen), Path(base), Path(reporte)
    base.mkdir(parents=True, exist_ok=True)
    reporte.mkdir(parents=True, exist_ok=True)
    fechas = {"eventos_clinicos.csv": "fecha_evento", "mediciones.csv": "fecha_medicion", "citaciones.csv": "fecha_cita"}
    for f in origen.glob("*.csv"):
        df = pd.read_csv(f, dtype=str)
        col = fechas.get(f.name)
        if col:
            en = (df[col] > desde) & (df[col] <= hasta)
            df[~en].to_csv(base / f.name, index=False)
            df[en].to_csv(reporte / f.name, index=False)
        else:
            df.to_csv(base / f.name, index=False)
    # Las otras fuentes también se parten por fecha: lo nuevo llega en el reporte
    from .fuentes import carpeta_fuentes
    cf = carpeta_fuentes(origen)
    if cf is not None:
        (base / "fuentes").mkdir(exist_ok=True)
        for f in cf.glob("*.csv"):
            df = pd.read_csv(f, dtype=str)
            col = FECHA_FUENTES.get(f.name)
            en = ((df[col] > desde) & (df[col] <= hasta)) if col in df.columns else pd.Series(False, index=df.index)
            df[~en].to_csv(base / "fuentes" / f.name, index=False)
            if en.any():
                df[en].to_csv(reporte / f.name, index=False)
