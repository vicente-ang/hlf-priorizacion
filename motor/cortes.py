"""Corte semanal: la lista oficial se reprioriza un día fijo; lo que llega entre cortes son alertas.

Lo pidió el hospital (entrevista 6): "tienes que fijarme un día en que me vaya a repriorizar, para yo saber al
día siguiente de esa repriorización agendar". Las 72 horas son el plazo para agendar a cada persona, no la
frecuencia del recálculo: si la lista se moviera todos los días "nunca vas a tener una posición fija".

Entonces:
  - Lista VIGENTE: la que se calculó en el último corte (por defecto, el lunes) con los datos hasta ese día.
    Con ella se agenda toda la semana.
  - ALERTAS: cada reporte diario se compara con el corte vigente. Quien tuvo un evento grave aparece como alerta
    al día siguiente, con el puesto que tendría en el próximo corte. No se mueve solo.
  - ADELANTAR: el jefe de especialidad o la gestora pueden subir a alguien antes del próximo corte ("lo vi ayer en
    la urgencia, lo tengo que ver"). Exige motivo y queda en el registro.
  - HISTORIAL: el puesto de cada persona en cada corte, con lo que llegó entre uno y otro (trazabilidad T1 -> T2).
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from .cambios import _llegado, cambios
from .priorizacion import priorizar
from .puntaje import _a_fecha

DIAS_SEMANA = {"lunes": 0, "martes": 1, "miercoles": 2, "miércoles": 2, "jueves": 3, "viernes": 4,
               "sabado": 5, "sábado": 5, "domingo": 6}
NOMBRE_DIA = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]


def dia_corte(cfg: dict) -> int:
    return DIAS_SEMANA[str(cfg.get("corte", {}).get("dia_semana", "lunes")).lower()]


def corte_vigente(hoy, cfg: dict) -> date:
    """El último día de corte que no pasa de `hoy` (si hoy es día de corte, es hoy)."""
    hoy = _a_fecha(hoy)
    return hoy - timedelta(days=(hoy.weekday() - dia_corte(cfg)) % 7)


def proximo_corte(hoy, cfg: dict) -> date:
    return corte_vigente(hoy, cfg) + timedelta(days=7)


def es_dia_de_corte(hoy, cfg: dict) -> bool:
    return _a_fecha(hoy).weekday() == dia_corte(cfg)


def cortes_anteriores(hoy, cfg: dict, n: int | None = None) -> list[date]:
    """Los últimos `n` cortes hasta el vigente, del más antiguo al más reciente."""
    n = n or cfg.get("corte", {}).get("semanas_historial", 8)
    ult = corte_vigente(hoy, cfg)
    return [ult - timedelta(days=7 * k) for k in range(n - 1, -1, -1)]


def fecha_larga(f: date) -> str:
    return f"{NOMBRE_DIA[f.weekday()]} {f.strftime('%d-%m-%Y')}"


# --------------------------------------------------------------------------- alertas entre cortes
TIPOS_ALERTA = ["Entró al carril rápido", "Salió de la lista", "Subió", "Nueva señal de deterioro", "Entró a la lista"]


def alertas_desde_corte(datos, hoy, cfg: dict, modo: str | None = None, especialidad: str | None = None,
                        umbral: int = 5) -> tuple[pd.DataFrame, dict]:
    """Lo que llegó desde el corte vigente hasta `hoy`, con el puesto vigente y el que tendría en el próximo
    corte (proyección). No cambia la lista vigente."""
    c = corte_vigente(hoy, cfg)
    if _a_fecha(hoy) <= c:
        return pd.DataFrame(), {"desde": c, "hasta": _a_fecha(hoy), "en_lista_antes": 0, "en_lista_ahora": 0,
                                **{t: 0 for t in TIPOS_ALERTA}}
    df, res = cambios(datos, None, c, hoy, cfg, modo=modo, especialidad=especialidad, umbral=umbral)
    if len(df):
        df = df[df.tipo.isin(TIPOS_ALERTA)].reset_index(drop=True)
        df = df.rename(columns={"puesto_antes": "puesto_vigente", "puesto_ahora": "puesto_proyectado"})
    return df, res


# --------------------------------------------------------------------------- adelantos manuales
def aplicar_adelantos(lista: pd.DataFrame, adelantos: list[dict]) -> pd.DataFrame:
    """Sube al principio de la lista vigente a quienes el jefe o la gestora adelantaron (en el orden en que se
    pidió). Cada adelanto: {"id_paciente", "motivo", "usuario", "rol"}. El resto conserva su orden."""
    if lista is None or lista.empty or not adelantos:
        return lista
    ids = [a["id_paciente"] for a in adelantos if a["id_paciente"] in set(lista.id_paciente)]
    if not ids:
        return lista
    info = {a["id_paciente"]: a for a in adelantos}
    salida = []
    for esp, g in lista.groupby("especialidad", sort=False):
        arriba = [i for i in ids if i in set(g.id_paciente)]
        if not arriba:
            salida.append(g)
            continue
        g = g.copy()
        g["puesto_corte"] = g["puesto"]
        orden = pd.concat([g.set_index("id_paciente").loc[arriba].reset_index(),
                           g[~g.id_paciente.isin(arriba)]], ignore_index=True)
        orden["puesto"] = range(1, len(orden) + 1)
        for i in arriba:
            a = info[i]
            orden.loc[orden.id_paciente == i, "motivo_puesto"] = (
                f"adelantado por {a.get('rol', 'gestión')} ({a.get('usuario', '')}): {a['motivo']}")
        salida.append(orden)
    out = pd.concat(salida, ignore_index=True)
    out["cambio_puestos"] = out["puesto_regla_actual"] - out["puesto"]
    return out


# --------------------------------------------------------------------------- agendados
def quitar_agendados(lista: pd.DataFrame, agendados: dict) -> pd.DataFrame:
    """Reunión 7: quien ya tiene hora agendada sale del orden (formalmente sale de la lista cuando la cita se
    hace). `agendados` = {id_paciente: fecha_cita}. Renumera los puestos de cada especialidad."""
    if lista is None or lista.empty or not agendados:
        return lista
    out = lista[~lista.id_paciente.isin(set(agendados))].copy()
    out["puesto"] = out.groupby("especialidad").cumcount() + 1
    out["en_especialidad"] = out.groupby("especialidad")["puesto"].transform("max")
    out["cambio_puestos"] = out["puesto_regla_actual"] - out["puesto"]
    return out.reset_index(drop=True)


# --------------------------------------------------------------------------- historial por corte
def historial_desde_listas(listas: dict, datos, pid: str) -> pd.DataFrame:
    """Puesto de `pid` en cada corte. `listas` = {fecha_corte: lista priorizada de su especialidad}."""
    p = datos.pacientes[pid]
    filas, previa = [], None
    for c in sorted(listas):
        df = listas[c]
        f = df[df.id_paciente == pid] if len(df) else df
        llego = _llegado(p, previa, c) if previa else []
        if len(f):
            r = f.iloc[0]
            filas.append({"corte": c, "puesto": int(r["puesto"]), "de": int(r["en_especialidad"]),
                          "prioridad": r["prioridad_dinamica"], "por_que": r["motivo_puesto"],
                          "llego": "; ".join(llego)})
        else:
            fuera = "aún no ingresaba" if p.fecha_ingreso > c else "fuera de la lista"
            filas.append({"corte": c, "puesto": None, "de": None, "prioridad": None, "por_que": fuera,
                          "llego": "; ".join(llego)})
        previa = c
    return pd.DataFrame(filas)


def historial_paciente(datos, pid: str, hoy, cfg: dict, modo: str | None = None, n: int | None = None) -> pd.DataFrame:
    esp = datos.pacientes[pid].especialidad
    listas = {c: priorizar(datos, c, cfg, modo=modo, especialidad=esp) for c in cortes_anteriores(hoy, cfg, n)}
    return historial_desde_listas(listas, datos, pid)


def frase_cambio(h: pd.DataFrame) -> str | None:
    """Resumen del historial: el cambio desde el corte anterior y, si fue mayor, el recorrido completo.
    Ej.: 'Sigue en el puesto 1 desde el corte del 05-10. En 7 semanas pasó del puesto 85 (24-08) al 1: Urgencia
    (triage ESI 2) (14-09); Hospitalización (20-09).'"""
    validos = h.dropna(subset=["puesto"]).reset_index(drop=True)
    if len(validos) < 2:
        return None
    a, b = validos.iloc[-2], validos.iloc[-1]
    pa, pb = int(a["puesto"]), int(b["puesto"])
    if pa == pb:
        frase = f"Sigue en el puesto {pb} desde el corte del {a['corte'].strftime('%d-%m')}."
    else:
        verbo = "Subió" if pb < pa else "Bajó"
        motivo = b["llego"] or ("otros pacientes pasaron adelante" if pb > pa else "otros salieron de la lista o bajaron")
        frase = f"{verbo} del puesto {pa} al {pb} desde el corte del {a['corte'].strftime('%d-%m')}: {motivo}."
    p0 = validos.iloc[0]
    if abs(int(p0["puesto"]) - pb) >= 5 and len(validos) > 2:
        subidas = [validos.iloc[k]["llego"] for k in range(1, len(validos))
                   if validos.iloc[k]["llego"] and int(validos.iloc[k]["puesto"]) < int(validos.iloc[k - 1]["puesto"])]
        semanas = (b["corte"] - p0["corte"]).days // 7
        frase += (f" En {semanas} semanas pasó del puesto {int(p0['puesto'])} ({p0['corte'].strftime('%d-%m')}) al {pb}"
                  + (": " + "; ".join(subidas) + "." if subidas and pb < int(p0["puesto"]) else "."))
    return frase
