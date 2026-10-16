"""Adaptadores de fuentes: cada reporte del hospital se convierte al modelo interno, unido por paciente.

El hospital tiene varios registros que no conversan entre sí (entrevistas 4 y 5):
  Tálamo        ficha del hospital: consulta, urgencia, pabellón, hospitalizado, agenda
  Rayen         ficha de APS. El BIAU (visualizador del Servicio Sur Oriente) se consulta persona a persona y
                solo existe en este Servicio (reunión 7): por eso la entrada es el REPORTE que exporta cada ficha,
                no el BIAU. Ver FORMATO_ENTRADA.md.
  ECICEP / ACG  estratificación de riesgo de APS (G0..G3) y alertas informáticas del Servicio
  Interconsultas (SIC) que llegan desde APS u otros especialistas

Cada uno sale como un reporte en tablas (Excel o CSV), "más o menos con la misma estructura" y siempre con el
RUT. Aquí cada reporte tiene su adaptador. Si un hecho ya está en `eventos_clinicos` (misma persona, mismo tipo,
misma fecha), el adaptador lo COMPLETA (días de estada, tipo de cama, cirugía, categoría ESI...). Si no está,
lo AGREGA. Así una hospitalización que llega por Tálamo y por una alerta del Servicio cuenta una sola vez.

Archivos que entiende (todos opcionales; columnas mínimas en ESQUEMAS):
  talamo_hospitalizaciones.csv     un egreso hospitalario
  talamo_urgencias.csv             una atención de urgencia
  acg_estratificacion.csv          estrato de riesgo de APS de una persona a una fecha
  rayen_diagnosticos_cronicos.csv  un diagnóstico crónico registrado en APS
  interconsultas.csv               interconsultas nuevas (con o sin prioridad) y su texto

Llave: `id_paciente` (RUT ya seudonimizado). Si el reporte trae `rut`, se seudonimiza con la misma sal en
todas las fuentes (motor.privacidad.seudonimo), así las fuentes se unen sin guardar el RUT.
"""
from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pandas as pd

from .puntaje import Paciente, RAIZ, _a_fecha, _texto

FUENTES_SINTETICAS = RAIZ / "data" / "fuentes_sinteticas"

ESQUEMAS = {
    "talamo_hospitalizaciones.csv": ["id_paciente", "fecha_ingreso", "dias_estada", "tipo_cama"],
    "talamo_urgencias.csv": ["id_paciente", "fecha_atencion", "categoria_esi"],
    "acg_estratificacion.csv": ["id_paciente", "fecha_estratificacion", "estrato"],
    "rayen_diagnosticos_cronicos.csv": ["id_paciente", "diagnostico_cie10"],
    "interconsultas.csv": ["id_paciente", "id_solicitud", "especialidad", "diagnostico_cie10", "fecha_ingreso_lista"],
}
NOMBRE_FUENTE = {
    "talamo_hospitalizaciones.csv": "Tálamo · hospitalizado",
    "talamo_urgencias.csv": "Tálamo · urgencia",
    "acg_estratificacion.csv": "ECICEP · estratificación ACG",
    "rayen_diagnosticos_cronicos.csv": "Rayen (APS), reporte del Servicio",
    "interconsultas.csv": "Interconsultas (SIC)",
}


def carpeta_fuentes(carpeta_datos: Path) -> Path | None:
    """Dónde buscar las otras fuentes. HLF_FUENTES manda (HLF_FUENTES=no las apaga)."""
    env = os.environ.get("HLF_FUENTES")
    if env:
        return None if env.lower() in ("no", "0", "false", "ninguna") else Path(env)
    if (Path(carpeta_datos) / "fuentes").is_dir():
        return Path(carpeta_datos) / "fuentes"
    from .puntaje import DATOS_DEFECTO
    if Path(carpeta_datos).resolve() == DATOS_DEFECTO.resolve() and FUENTES_SINTETICAS.is_dir():
        return FUENTES_SINTETICAS
    return None


def _ids(df: pd.DataFrame) -> pd.DataFrame:
    if "id_paciente" not in df.columns and "rut" in df.columns:
        from .privacidad import seudonimo
        df = df.assign(id_paciente=df["rut"].map(seudonimo)).drop(columns="rut")
    return df


def _buscar(p: Paciente, tipo: str, fecha, tolerancia: int = 1):
    for e in p.eventos:
        if e["tipo_evento"] == tipo and abs((e["fecha"] - fecha).days) <= tolerancia:
            return e
    return None


def _si(x) -> bool:
    return str(x).strip().lower() in ("true", "1", "si", "sí", "s", "yes")


def _num(x):
    try:
        v = float(x)
        return None if v != v else v
    except (TypeError, ValueError):
        return None


def enriquecer(datos, carpeta: str | Path) -> dict[str, dict]:
    """Incorpora las fuentes de `carpeta` a `datos` (en el mismo objeto). Devuelve un resumen por archivo:
    filas leídas, eventos completados, eventos agregados y filas sin paciente en la lista."""
    carpeta = Path(carpeta)
    res: dict[str, dict] = {}
    pac = datos.pacientes

    # --- Interconsultas primero: pueden traer pacientes nuevos
    f = carpeta / "interconsultas.csv"
    if f.exists():
        df = _ids(pd.read_csv(f))
        nuevos = 0
        for r in df.to_dict("records"):
            if r["id_paciente"] in pac:
                continue
            prio = _texto(r.get("prioridad_inicial")).strip().lower()
            sin = prio not in ("alta", "media", "baja")
            pac[r["id_paciente"]] = Paciente(
                id_paciente=r["id_paciente"], especialidad=r["especialidad"],
                sub_especialidad=_texto(r.get("sub_especialidad")) or r["especialidad"],
                diagnostico=f"{r['diagnostico_cie10']} {_texto(r.get('diagnostico_texto'))}".strip(),
                prioridad_inicial="media" if sin else prio, sin_priorizar=sin,
                texto_interconsulta=_texto(r.get("texto_interconsulta")),
                fecha_ingreso=_a_fecha(r["fecha_ingreso_lista"]), estado=_texto(r.get("estado")) or "en_espera",
                origen=_texto(r.get("origen_derivacion")) or "CESFAM/APS", edad=int(_num(r.get("edad")) or 0),
                sexo=_texto(r.get("sexo")), comuna=_texto(r.get("comuna")), prevision=_texto(r.get("prevision")),
                nivel_socioeconomico=_texto(r.get("nivel_socioeconomico")), fecha_defuncion=None)
            nuevos += 1
        res["interconsultas.csv"] = {"filas": len(df), "pacientes_nuevos": nuevos}

    # --- Hospitalizaciones (Tálamo hospitalizado)
    f = carpeta / "talamo_hospitalizaciones.csv"
    if f.exists():
        df = _ids(pd.read_csv(f))
        comp = agr = fuera = 0
        for r in df.to_dict("records"):
            p = pac.get(r["id_paciente"])
            if p is None:
                fuera += 1
                continue
            fecha = _a_fecha(r["fecha_ingreso"])
            cama = _texto(r.get("tipo_cama")).upper() or "SALA"
            detalle = {"dias_estadia": _num(r.get("dias_estada")), "tipo_cama": cama,
                       "dias_uci": _num(r.get("dias_uci")), "cirugia": _si(r.get("cirugia")),
                       "tipo_ingreso": _texto(r.get("tipo_ingreso")).lower() or "urgente",
                       "diagnostico_cie10": _texto(r.get("diagnostico_egreso_cie10")),
                       "fuente": NOMBRE_FUENTE["talamo_hospitalizaciones.csv"]}
            e = _buscar(p, "hospitalizacion", fecha)
            if e is not None:
                e.update({k: v for k, v in detalle.items() if v not in (None, "")})
                comp += 1
            else:
                uci = cama in ("UCI", "UPC") or (detalle["dias_uci"] or 0) > 0
                p.eventos.append({"id_paciente": p.id_paciente, "id_evento": f"TAL-H-{p.id_paciente}-{fecha}",
                                  "fecha_evento": str(fecha), "fecha": fecha, "tipo_evento": "hospitalizacion",
                                  "subtipo": "ingreso UCI" if uci else "ingreso hospitalario", "severidad": "grave",
                                  "detalle": f"egreso hospitalario ({p.especialidad})", **detalle})
                agr += 1
        res["talamo_hospitalizaciones.csv"] = {"filas": len(df), "completados": comp, "agregados": agr,
                                               "sin_paciente": fuera}

    # --- Urgencias (Tálamo urgencia)
    f = carpeta / "talamo_urgencias.csv"
    if f.exists():
        df = _ids(pd.read_csv(f))
        comp = agr = fuera = 0
        for r in df.to_dict("records"):
            p = pac.get(r["id_paciente"])
            if p is None:
                fuera += 1
                continue
            fecha = _a_fecha(r["fecha_atencion"])
            esi = int(_num(r.get("categoria_esi")) or 3)
            detalle = {"esi": esi, "horas_estadia": _num(r.get("horas_estadia")),
                       "destino": _texto(r.get("destino")), "diagnostico_cie10": _texto(r.get("diagnostico_cie10")),
                       "diagnostico_texto": _texto(r.get("diagnostico_texto")),
                       "fuente": NOMBRE_FUENTE["talamo_urgencias.csv"]}
            e = _buscar(p, "visita_urgencia", fecha, tolerancia=0)
            if e is not None:
                e.update({k: v for k, v in detalle.items() if v not in (None, "")})
                comp += 1
            else:
                sub, sev = (("triage ESI 2", "grave") if esi <= 2 else ("triage ESI 3", "moderada") if esi == 3
                            else ("consulta de urgencia", "leve"))
                p.eventos.append({"id_paciente": p.id_paciente, "id_evento": f"TAL-U-{p.id_paciente}-{fecha}",
                                  "fecha_evento": str(fecha), "fecha": fecha, "tipo_evento": "visita_urgencia",
                                  "subtipo": sub, "severidad": sev, "detalle": f"urgencia ESI {esi}", **detalle})
                agr += 1
        res["talamo_urgencias.csv"] = {"filas": len(df), "completados": comp, "agregados": agr, "sin_paciente": fuera}

    # --- ACG / ECICEP
    f = carpeta / "acg_estratificacion.csv"
    if f.exists():
        df = _ids(pd.read_csv(f)).sort_values("fecha_estratificacion")
        fuera = 0
        for r in df.to_dict("records"):
            p = pac.get(r["id_paciente"])
            if p is None:
                fuera += 1
                continue
            p.acg = list(p.acg or []) + [{"fecha": _a_fecha(r["fecha_estratificacion"]),
                                          "estrato": str(r["estrato"]).upper().strip()}]
        res["acg_estratificacion.csv"] = {"filas": len(df), "sin_paciente": fuera}

    # --- Diagnósticos crónicos de APS (Rayen)
    f = carpeta / "rayen_diagnosticos_cronicos.csv"
    if f.exists():
        df = _ids(pd.read_csv(f))
        fuera = 0
        for r in df.to_dict("records"):
            p = pac.get(r["id_paciente"])
            if p is None:
                fuera += 1
                continue
            p.comorbilidades = list(p.comorbilidades or []) + [
                {"cie10": str(r["diagnostico_cie10"]), "fecha": _a_fecha(r.get("fecha_registro"))}]
        res["rayen_diagnosticos_cronicos.csv"] = {"filas": len(df), "sin_paciente": fuera}

    for p in pac.values():
        p.eventos.sort(key=lambda x: x["fecha"])
    datos.fuentes = res
    datos._fecha_ref = None
    return res


def resumen_fuentes(res: dict) -> list[str]:
    """Una línea por fuente cargada, para mostrar en la interfaz."""
    out = []
    for archivo, r in res.items():
        partes = [f"{r['filas']} filas"]
        if r.get("completados"):
            partes.append(f"{r['completados']} completan un evento que ya estaba")
        if r.get("agregados"):
            partes.append(f"{r['agregados']} eventos nuevos")
        if r.get("pacientes_nuevos"):
            partes.append(f"{r['pacientes_nuevos']} interconsultas nuevas")
        if r.get("sin_paciente"):
            partes.append(f"{r['sin_paciente']} sin paciente en lista")
        out.append(f"{NOMBRE_FUENTE.get(archivo, archivo)}: " + ", ".join(partes))
    return out
