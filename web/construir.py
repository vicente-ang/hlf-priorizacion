"""Arma los datos del front web (`web/datos.js`) desde el motor y las propuestas del agente IA.

El front (web/index.html) es estático: no calcula nada, muestra la lista vigente que publica el motor y la
propuesta del agente en Bedrock. Este script corre el motor para los últimos cortes semanales y escribe un solo
archivo `datos.js` (window.HLF = {...}) que el navegador lee incluso abriendo el HTML con doble clic.

Uso:
  python -m web.construir                       # datos del desafío, "hoy" = fecha más reciente de los datos
  python -m web.construir --hoy 2026-10-13      # otra fecha (lista vigente = corte del lunes anterior)
  python -m web.construir --datos <carpeta>     # otra carpeta de CSV (mismo formato, ver FORMATO_ENTRADA.md)

En producción lo mismo lo haría la Lambda del lunes y dejaría datos.js (o datos.json) en S3.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import date, datetime
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor import Datos, cargar_regla, priorizar  # noqa: E402
from motor.clusters import texto_clusters  # noqa: E402
from motor.cortes import corte_vigente, cortes_anteriores, proximo_corte  # noqa: E402
from motor.explicar import explicacion_plantilla, hechos  # noqa: E402
from motor.pertinencia import es_pertinente  # noqa: E402
from motor.puntaje import DATOS_DEFECTO, ETIQUETAS_MEDICION, ETIQUETAS_SUBTIPO  # noqa: E402

IA_RES = RAIZ / "ia" / "resultados"
SALIDA = Path(__file__).resolve().parent / "datos.js"
HOSPITAL = "Hospital Clínico Dra. Eloísa Díaz La Florida"
RUTINA = ("control", "control crónico", "control de rutina")
NOMBRE_MODELO = {"us.anthropic.claude-haiku-4-5-20251001-v1:0": "Claude Haiku 4.5",
                 "us.anthropic.claude-sonnet-4-5-20250929-v1:0": "Claude Sonnet 4.5"}


def _limpio(v):
    """Valor serializable a JSON: fechas en ISO, NaN como null, numpy a Python."""
    if v is None:
        return None
    if isinstance(v, (date, datetime)):
        return v.isoformat()[:10]
    if hasattr(v, "item") and not isinstance(v, (list, dict, str)):
        v = v.item()
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return None
    if isinstance(v, dict):
        return {str(k): _limpio(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [_limpio(x) for x in v]
    return v


def _mayuscula(t: str) -> str:
    return t[:1].upper() + t[1:] if t else t


def _nombre(nombres: dict, pid: str) -> str:
    """Nombre de fantasía del dataset; las interconsultas sintéticas no lo traen."""
    return nombres.get(pid) or f"Paciente {pid[-3:]}"


def _nombres(carpeta: Path) -> dict:
    f = carpeta / "pacientes.csv"
    if not f.exists():
        return {}
    df = pd.read_csv(f)
    return dict(zip(df.id_paciente, df.nombre_fantasia)) if "nombre_fantasia" in df else {}


def _antecedentes(p, cfg: dict, hoy: date) -> list[dict]:
    """La historia del paciente como registros con fecha clínica, fuente y si tiene que ver con la derivación."""
    out = []
    for e in p.eventos:
        if e["fecha"] > hoy or e["subtipo"] in RUTINA:
            continue
        dx = e.get("diagnostico_cie10")
        dx = dx if isinstance(dx, str) and dx else None
        extra = []
        if e.get("dias_estadia") == e.get("dias_estadia") and e.get("dias_estadia"):
            extra.append(f"{int(e['dias_estadia'])} días de estada")
        if e.get("dias_uci") == e.get("dias_uci") and e.get("dias_uci"):
            extra.append(f"{int(e['dias_uci'])} en UCI")
        if e.get("cirugia") is True:
            extra.append("con cirugía")
        if e.get("esi") == e.get("esi") and e.get("esi"):
            extra.append(f"ESI {int(e['esi'])}")
        out.append({"fecha": e["fecha"], "tipo": "evento", "severidad": e.get("severidad"),
                    "titulo": _mayuscula(ETIQUETAS_SUBTIPO.get(e["subtipo"], e["subtipo"])),
                    "detalle": " · ".join(([f"dx {dx}"] if dx else []) + extra),
                    "fuente": e.get("fuente") or "Tálamo", "relacionado": bool(es_pertinente(p, e, cfg))})
    for m in p.mediciones:
        if m["fecha"] > hoy or not m.get("fuera_de_rango"):
            continue
        nombre = ETIQUETAS_MEDICION.get(m["tipo_medicion"], m["tipo_medicion"])
        out.append({"fecha": m["fecha"], "tipo": "medicion", "severidad": "moderada",
                    "titulo": f"{nombre} fuera de rango", "detalle": f"{m['valor']:g} {m['unidad']}",
                    "fuente": "Control ambulatorio", "relacionado": True})
    for c in p.comorbilidades:
        out.append({"fecha": c.get("fecha"), "tipo": "cronico", "severidad": "leve",
                    "titulo": f"Diagnóstico crónico en APS: {c.get('cie10')}", "detalle": "",
                    "fuente": "Rayen (APS)", "relacionado": True})
    for a in p.acg:
        out.append({"fecha": a.get("fecha"), "tipo": "acg", "severidad": "leve",
                    "titulo": f"Estratificación de riesgo ACG: {a.get('estrato')}", "detalle": "",
                    "fuente": "ECICEP / APS", "relacionado": True})
    out.append({"fecha": p.fecha_ingreso, "tipo": "derivacion", "severidad": None,
                "titulo": f"Derivación a {p.especialidad}: {p.diagnostico}",
                "detalle": p.texto_interconsulta or ("Sin prioridad del especialista" if p.sin_priorizar
                                                     else f"Prioridad del especialista: {p.prioridad_inicial}"),
                "fuente": f"Interconsulta · {p.origen}", "relacionado": True})
    out = [x for x in out if x["fecha"] is not None]
    out.sort(key=lambda x: str(x["fecha"]), reverse=True)
    return out[:30]


def _mediciones(p, hoy: date) -> dict:
    series: dict[str, list] = {}
    for m in p.mediciones:
        if m["fecha"] > hoy:
            continue
        nombre = ETIQUETAS_MEDICION.get(m["tipo_medicion"], m["tipo_medicion"])
        series.setdefault(nombre, []).append({"fecha": m["fecha"], "valor": m["valor"], "unidad": m["unidad"],
                                              "fuera": bool(m.get("fuera_de_rango"))})
    return {k: v[-12:] for k, v in series.items()}


def _ia() -> tuple[dict, dict]:
    """Propuestas del agente (por paciente) y el resumen de su evaluación."""
    arch = IA_RES / "propuestas_hlf.csv"
    if not arch.exists():
        return {}, {}
    prop = pd.read_csv(arch)
    por_id = {}
    for r in prop.to_dict("records"):
        def js(x):
            try:
                return json.loads(x) if isinstance(x, str) and x else []
            except ValueError:
                return []
        por_id[r["id_paciente"]] = {
            "categoria": r.get("categoria_ia"), "puntaje": r.get("puntaje_ia"), "confianza": r.get("confianza"),
            "resumen": r.get("resumen"), "evidencia": js(r.get("evidencia")), "ignorado": js(r.get("ignorado")),
            "sube": bool(r.get("propone_subir")), "baja": bool(r.get("propone_bajar")),
            "categoria_final": r.get("categoria_final"), "puesto_final": r.get("puesto_final"),
            "puesto_ia": r.get("puesto_ia"), "error": r.get("error")}
    modelo = prop.modelo.dropna().iloc[0] if "modelo" in prop and prop.modelo.notna().any() else None
    resumen = {"evaluados": len(prop), "errores": int(prop.error.notna().sum()) if "error" in prop else 0,
               "suben": int(prop.propone_subir.sum()) if "propone_subir" in prop else None,
               "bajan": int(prop.propone_bajar.sum()) if "propone_bajar" in prop else None,
               "bajan_confianza_alta": int((prop.propone_bajar & (prop.confianza == "alta")).sum())
               if "propone_bajar" in prop else None,
               "tokens_entrada": int(prop.tokens_entrada.fillna(0).sum()),
               "tokens_salida": int(prop.tokens_salida.fillna(0).sum()),
               "modo": str(prop.modo.iloc[0]), "modelo": modelo, "modelo_nombre": NOMBRE_MODELO.get(modelo, modelo),
               "rubrica": str(prop.version_rubrica.iloc[0]), "corte": str(prop.corte.iloc[0])}
    # costo estimado con el perfil de inferencia de EE. UU. de Claude Haiku 4.5 (US$ 1,10 y 5,50 por millón)
    if modelo and "haiku-4-5" in modelo:
        resumen["costo_usd"] = round(resumen["tokens_entrada"] * 1.10e-6 + resumen["tokens_salida"] * 5.50e-6, 2)
    for nombre, clave in (("test_conteos_bedrock.csv", "test"), ("ciclo_bedrock.csv", "ciclo"),
                          ("test_final_bedrock.csv", "test_metricas")):
        f = IA_RES / nombre
        if f.exists():
            resumen[clave] = pd.read_csv(f).to_dict("records")
    return por_id, resumen


def construir(carpeta: str | Path | None = None, hoy: str | date | None = None, salida: str | Path | None = None) -> dict:
    datos, cfg = Datos.cargar(carpeta), cargar_regla()
    hoy = date.fromisoformat(str(hoy)) if hoy else datos.fecha_referencia()
    corte = corte_vigente(hoy, cfg)
    cortes = cortes_anteriores(hoy, cfg)
    listas = {c: priorizar(datos, c, cfg, modo="carril_plazo") for c in cortes}
    vigente = listas[corte]
    p90 = int(round(vigente.dias_espera.quantile(0.9))) if len(vigente) else 0
    nombres = _nombres(Path(carpeta) if carpeta else DATOS_DEFECTO)
    ia, ia_resumen = _ia()
    if ia_resumen:
        from ia.decisiones import descartados
        prop = pd.read_csv(IA_RES / "propuestas_hlf.csv")
        ia_resumen["pertinencia"] = descartados(prop, datos, cfg)
    anterior = listas[cortes[-2]] if len(cortes) > 1 else vigente.iloc[0:0]
    previa = {r["id_paciente"]: r for r in anterior.to_dict("records")}
    puestos = {c: dict(zip(l.id_paciente, zip(l.puesto, l.prioridad_dinamica, l.carril_rapido))) for c, l in listas.items()}

    pacientes = []
    for r in vigente.to_dict("records"):
        p = datos.pacientes[r["id_paciente"]]
        ant = previa.get(r["id_paciente"])
        historial = []
        for c in cortes:
            x = puestos[c].get(r["id_paciente"])
            historial.append({"corte": c, "puesto": x[0] if x else None, "prioridad": x[1] if x else None,
                              "carril": bool(x[2]) if x else False})
        pacientes.append({
            "id": r["id_paciente"], "nombre": _nombre(nombres, r["id_paciente"]),
            "edad": p.edad, "sexo": p.sexo, "comuna": p.comuna, "prevision": p.prevision,
            "especialidad": p.especialidad, "sub": p.sub_especialidad, "diagnostico": p.diagnostico,
            "origen": p.origen, "fecha_ingreso": p.fecha_ingreso, "dias_espera": r["dias_espera"],
            "sobre_p90": bool(r["dias_espera"] > p90),
            "t1": r["prioridad_inicial"], "prioridad_origen": r["prioridad_origen"],
            "prioridad": r["prioridad_dinamica"], "motivo_prioridad": r["motivo_prioridad"],
            "carril": bool(r["carril_rapido"]), "motivo_carril": r.get("motivo_carril"),
            "plazo_dias": r.get("plazo_dias"), "motivo_plazo": r.get("motivo_plazo"),
            "fecha_objetivo": r.get("fecha_objetivo"), "dias_atraso": r.get("dias_atraso"),
            "puesto": r["puesto"], "de": r["en_especialidad"], "puesto_regla_actual": r.get("puesto_regla_actual"),
            "puesto_anterior": ant["puesto"] if ant else None, "motivo_puesto": r.get("motivo_puesto"),
            "lace": r.get("lace"), "verificar": r.get("verificar_estado"), "dias_sin_datos": r.get("dias_sin_datos"),
            "senales_deterioro": r.get("senales_deterioro") or [], "senales_mejora": r.get("senales_mejora") or [],
            "no_relacionados": r.get("eventos_no_relacionados") or [],
            "clusters": texto_clusters(r["clusters"]) if isinstance(r.get("clusters"), dict) else [],
            "hechos": hechos(r), "explicacion": explicacion_plantilla(r, ant),
            "sin_priorizar": bool(p.sin_priorizar), "propuesta_guia": p.propuesta,
            "historial": historial, "antecedentes": _antecedentes(p, cfg, hoy), "mediciones": _mediciones(p, hoy),
            "ia": ia.get(r["id_paciente"]),
        })

    # El contexto cambió: quienes tienen antecedentes nuevos entre el corte anterior y el vigente
    cambios = []
    desde = cortes[-2] if len(cortes) > 1 else corte
    for x in pacientes:
        p = datos.pacientes[x["id"]]
        nuevos = [e for e in p.eventos if desde < e["fecha"] <= corte and e["subtipo"] not in RUTINA]
        meds = [m for m in p.mediciones if desde < m["fecha"] <= corte and m.get("fuera_de_rango")]
        if not nuevos and not meds:
            continue
        a = previa.get(x["id"])
        textos = [_mayuscula(ETIQUETAS_SUBTIPO.get(e["subtipo"], e["subtipo"])) + f" ({e['fecha'].strftime('%d-%m')})"
                  + ("" if es_pertinente(p, e, cfg) else ", no relacionado") for e in nuevos]
        textos += [f"{ETIQUETAS_MEDICION.get(m['tipo_medicion'], m['tipo_medicion'])} fuera de rango "
                   f"({m['fecha'].strftime('%d-%m')})" for m in meds]
        grave = any(e["severidad"] == "grave" and es_pertinente(p, e, cfg) for e in nuevos)
        cambios.append({"id": x["id"], "nombre": x["nombre"], "especialidad": x["especialidad"], "nuevos": textos,
                        "antes": a["puesto"] if a else None, "ahora": x["puesto"], "prioridad": x["prioridad"],
                        "carril": x["carril"], "grave": grave})
    cambios.sort(key=lambda c: (not c["grave"], -((c["antes"] or c["ahora"]) - c["ahora"]), c["ahora"]))

    # Nuevos ingresos: interconsultas sin prioridad del especialista y quienes llegaron después del corte
    ingresos = []
    for p in datos.pacientes.values():
        nuevo = corte < p.fecha_ingreso <= hoy
        if not (p.sin_priorizar or nuevo) or p.fecha_ingreso > hoy:
            continue
        prop = p.propuesta or {}
        ingresos.append({"id": p.id_paciente, "nombre": _nombre(nombres, p.id_paciente), "edad": p.edad,
                         "especialidad": p.especialidad, "diagnostico": p.diagnostico, "origen": p.origen,
                         "fecha": p.fecha_ingreso, "texto": p.texto_interconsulta,
                         "tipo": "sin_priorizar" if p.sin_priorizar else "despues_del_corte",
                         "t1": None if p.sin_priorizar else p.prioridad_inicial,
                         "propuesta": prop.get("prioridad"), "criterios": prop.get("criterios") or [],
                         "estado_propuesta": prop.get("estado"), "fuente_propuesta": prop.get("fuente"),
                         "motivo_revision": prop.get("motivo"), "dias": (hoy - p.fecha_ingreso).days,
                         "limitada": len(p.texto_interconsulta or "") < 40,
                         "en_lista": any(x["id"] == p.id_paciente for x in pacientes)})
    ingresos.sort(key=lambda x: str(x["fecha"]), reverse=True)

    especialidades = []
    for esp, g in vigente.groupby("especialidad"):
        especialidades.append({"nombre": esp, "n": len(g), "p90": int(round(g.dias_espera.quantile(0.9))),
                               "sobre_umbral": int((g.dias_espera > p90).sum()),
                               "alta": int((g.prioridad_dinamica == "alta").sum()),
                               "carril": int(g.carril_rapido.sum())})
    especialidades.sort(key=lambda e: -e["n"])

    out = _limpio({
        "meta": {"hospital": HOSPITAL, "sigla": "HLF", "hoy": hoy, "corte": corte, "proximo_corte": proximo_corte(hoy, cfg),
                 "cortes": cortes, "p90": p90, "version_regla": cfg.get("version"),
                 "generado": datetime.now().isoformat(timespec="seconds"),
                 "fuentes": list((datos.fuentes or {}).keys())},
        "pacientes": pacientes, "cambios": cambios[:8], "n_cambios": len(cambios), "ingresos": ingresos,
        "especialidades": especialidades, "ia": ia_resumen,
    })
    destino = Path(salida) if salida else SALIDA
    destino.write_text("// Generado por python -m web.construir. No editar a mano.\nwindow.HLF = "
                       + json.dumps(out, ensure_ascii=False, separators=(",", ":")) + ";\n", encoding="utf-8")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--datos")
    ap.add_argument("--hoy")
    ap.add_argument("--salida")
    a = ap.parse_args()
    d = construir(a.datos, a.hoy, a.salida)
    m = d["meta"]
    print(f"{len(d['pacientes'])} pacientes en la lista vigente (corte {m['corte']}), {len(d['ingresos'])} ingresos, "
          f"P90 {m['p90']} días -> {a.salida or SALIDA}")


if __name__ == "__main__":
    main()
