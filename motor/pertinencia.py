"""¿El evento tiene que ver con aquello por lo que el paciente espera al especialista? (reunión 7)

El hospital lo dijo con un ejemplo: alguien derivado por hipoacusia que fue dos veces a urgencia por un esguince
no tiene más riesgo de empeorar su hipoacusia; en cambio, un paciente cardíaco con descompensaciones
respiratorias, o un diabético, sí. "Depende mucho de la enfermedad".

Regla:
  - Si el evento trae diagnóstico (CIE-10), cuenta para la lista de una especialidad solo si el código está en
    los grupos relacionados con esa especialidad (motor/config/regla.yaml, `pertinencia.por_especialidad`).
    Para una especialidad que no está en la tabla, cuenta el mismo capítulo CIE-10 del diagnóstico de derivación.
  - Si el evento NO trae diagnóstico (como los del dataset del desafío), se asume relacionado: es lo conservador.
  - Algunos eventos cuentan siempre (por defecto, el ingreso a UCI: indica fragilidad general; Lone et al. 2016).
Los eventos no relacionados se muestran ("no relacionado con la derivación"), pero no mueven a nadie.

La tabla parte de los capítulos CIE-10 de cada especialidad más las asociaciones de riesgo que mencionó el
hospital (cardiopatía y descompensación respiratoria, diabetes y enfermedad cardiovascular o renal). Es
configuración: la valida cada jefe de especialidad.
"""
from __future__ import annotations

from functools import lru_cache


def _limpiar(c) -> str:
    return str(c or "").upper().replace(".", "").replace(" ", "").strip()


def _hay(x) -> bool:
    return x is not None and not (isinstance(x, float) and x != x) and str(x).strip() not in ("", "nan", "None")


@lru_cache(maxsize=8192)
def _relacionado(codigo: str, especialidad: str, dx_derivacion: str, tabla: tuple) -> bool:
    prefijos = dict(tabla).get(especialidad)
    if prefijos is None:                                   # especialidad sin tabla: mismo capítulo CIE-10
        return bool(dx_derivacion) and codigo[:1] == dx_derivacion[:1]
    return any(codigo.startswith(p) for p in prefijos)


def _tabla(cfg: dict) -> tuple:
    cp = cfg.get("pertinencia") or {}
    if "_tabla" not in cp:                     # se arma una vez por configuración
        t = cp.get("por_especialidad") or {}
        cp["_tabla"] = tuple((esp, tuple(_limpiar(p) for p in prefijos)) for esp, prefijos in t.items())
        cp["_siempre"] = frozenset(cp.get("siempre") or [])
    return cp["_tabla"]


def es_pertinente(p, e: dict, cfg: dict) -> bool:
    """True si el evento `e` cuenta para la lista de `p` (su especialidad y diagnóstico de derivación)."""
    dx = e.get("diagnostico_cie10")
    if not _hay(dx):
        return True                                         # sin diagnóstico: se asume relacionado
    cp = cfg.get("pertinencia") or {}
    if not cp:
        return True
    tabla = _tabla(cfg)
    if e.get("subtipo") in cp["_siempre"]:
        return True
    return _relacionado(_limpiar(dx), p.especialidad, _limpiar(p.diagnostico.split(" ")[0]), tabla)
