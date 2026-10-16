"""Validación ciega: ¿está de acuerdo un revisor independiente con la prioridad que propone la regla? (KPI 4)

El hospital lo dijo así (entrevista 6): "el médico te prioriza en tiempo 1, ustedes repriorizan y el otro gallo
puede verlo": quien valida tiene que ser distinto de quien priorizó al derivar. Este script arma la muestra y
calcula la concordancia, sin que el revisor vea lo que propuso la regla.

  1) python validar_concordancia.py muestra --n 50 [--especialidad Cardiología] [--fecha 2026-10-12]
       -> salidas/validacion/muestra_<fecha>.csv   (para el revisor: casos en orden aleatorio, con un código,
                                                    un resumen clínico y una columna vacía prioridad_revisor)
       -> salidas/validacion/clave_<fecha>.csv     (código -> paciente y prioridad propuesta; NO se entrega)
     El revisor puede ser un médico de otra especialidad o del equipo de gestión clínica. Mientras no lo haya,
     un agente con las guías del hospital (otro modelo, otras fuentes) puede llenar la columna para probar el flujo,
     pero eso no reemplaza la validación clínica.
  2) python validar_concordancia.py comparar salidas/validacion/muestra_<fecha>.csv
       -> κ de Cohen ponderado (alta/media/baja), % de acuerdo, matriz y los casos en desacuerdo para revisar.
Meta del hospital: κ ≥ 0,70.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent
sys.path.insert(0, str(RAIZ))
from motor import Datos, cargar_regla, priorizar  # noqa: E402
from motor.clusters import clusters, texto_clusters  # noqa: E402
from motor.puntaje import ETIQUETAS_SUBTIPO  # noqa: E402

CATS = ["alta", "media", "baja"]
SALIDA = RAIZ / "salidas" / "validacion"


def kappa_ponderado(a: list[str], b: list[str], cats=CATS) -> float:
    """κ de Cohen con pesos lineales (las categorías son ordenadas: alta > media > baja)."""
    k = len(cats)
    idx = {c: i for i, c in enumerate(cats)}
    pares = [(idx[x], idx[y]) for x, y in zip(a, b) if x in idx and y in idx]
    n = len(pares)
    if n == 0:
        return float("nan")
    w = [[1 - abs(i - j) / (k - 1) for j in range(k)] for i in range(k)]
    obs = [[0.0] * k for _ in range(k)]
    for i, j in pares:
        obs[i][j] += 1 / n
    fa = [sum(obs[i][j] for j in range(k)) for i in range(k)]
    fb = [sum(obs[i][j] for i in range(k)) for j in range(k)]
    po = sum(w[i][j] * obs[i][j] for i in range(k) for j in range(k))
    pe = sum(w[i][j] * fa[i] * fb[j] for i in range(k) for j in range(k))
    return 1.0 if pe == 1 else (po - pe) / (1 - pe)


def resumen_clinico(p, r: dict, corte) -> str:
    """Lo que vería un médico revisor: sin puesto ni prioridad propuesta."""
    evs = [f"{ETIQUETAS_SUBTIPO.get(e['subtipo'], e['subtipo'])} ({e['fecha'].strftime('%d-%m-%Y')})"
           for e in p.eventos if e["fecha"] <= corte and e["severidad"] in ("moderada", "grave")][-6:]
    partes = [f"{p.edad} años. {p.diagnostico}. Derivado desde {p.origen} hace {r['dias_espera']} días."]
    if p.texto_interconsulta:
        partes.append(f"Interconsulta: «{p.texto_interconsulta}».")
    if evs:
        partes.append("Mientras espera: " + "; ".join(evs) + ".")
    cl = r["clusters"] if isinstance(r.get("clusters"), dict) else clusters(p, corte, cargar_regla())
    partes += [x + "." for x in texto_clusters(cl) if not x.startswith("Índice LACE")]
    return " ".join(partes)


def muestra(n: int, fecha: str | None, especialidad: str | None, semilla: int = 7) -> tuple[Path, Path]:
    datos, cfg = Datos.cargar(), cargar_regla()
    fecha = fecha or datos.fecha_referencia().isoformat()
    lista = priorizar(datos, fecha, cfg, especialidad=especialidad)
    rnd = random.Random(semilla)
    # muestra estratificada por prioridad propuesta, para que haya casos de las tres
    filas = []
    for cat in CATS:
        g = lista[lista.prioridad_dinamica == cat]
        filas += g.sample(min(len(g), max(1, n // 3)), random_state=semilla).to_dict("records")
    rnd.shuffle(filas)
    corte = pd.Timestamp(fecha).date()
    casos, clave = [], []
    for i, r in enumerate(filas[:n], start=1):
        cod = f"C{i:03d}"
        casos.append({"codigo": cod, "especialidad": r["especialidad"],
                      "resumen": resumen_clinico(datos.pacientes[r["id_paciente"]], r, corte),
                      "prioridad_revisor": "", "comentario": ""})
        clave.append({"codigo": cod, "id_paciente": r["id_paciente"], "prioridad_propuesta": r["prioridad_dinamica"],
                      "prioridad_inicial": r["prioridad_inicial"], "puesto": r["puesto"], "fecha": fecha,
                      "version_regla": cfg.get("version")})
    SALIDA.mkdir(parents=True, exist_ok=True)
    fm, fc = SALIDA / f"muestra_{fecha}.csv", SALIDA / f"clave_{fecha}.csv"
    pd.DataFrame(casos).to_csv(fm, index=False, encoding="utf-8-sig")
    pd.DataFrame(clave).to_csv(fc, index=False, encoding="utf-8-sig")
    return fm, fc


def comparar(archivo_muestra: str | Path, archivo_clave: str | Path | None = None) -> dict:
    fm = Path(archivo_muestra)
    fc = Path(archivo_clave) if archivo_clave else fm.with_name(fm.name.replace("muestra_", "clave_"))
    m = pd.read_csv(fm, dtype=str).merge(pd.read_csv(fc, dtype=str), on="codigo")
    m["prioridad_revisor"] = m["prioridad_revisor"].fillna("").str.strip().str.lower()
    m = m[m.prioridad_revisor.isin(CATS)]
    if m.empty:
        raise SystemExit("La muestra no tiene la columna prioridad_revisor llena (alta, media o baja).")
    k = kappa_ponderado(list(m.prioridad_propuesta), list(m.prioridad_revisor))
    k_t1 = kappa_ponderado(list(m.prioridad_inicial), list(m.prioridad_revisor))
    matriz = pd.crosstab(m.prioridad_propuesta, m.prioridad_revisor).reindex(index=CATS, columns=CATS, fill_value=0)
    desacuerdo = m[m.prioridad_propuesta != m.prioridad_revisor][["codigo", "id_paciente", "prioridad_propuesta",
                                                                  "prioridad_revisor", "comentario"]]
    return {"n": len(m), "kappa": k, "kappa_prioridad_inicial": k_t1,
            "acuerdo": float((m.prioridad_propuesta == m.prioridad_revisor).mean()), "matriz": matriz,
            "desacuerdo": desacuerdo}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("muestra")
    a.add_argument("--n", type=int, default=50)
    a.add_argument("--fecha")
    a.add_argument("--especialidad")
    b = sub.add_parser("comparar")
    b.add_argument("archivo")
    b.add_argument("--clave")
    x = ap.parse_args()
    if x.cmd == "muestra":
        fm, fc = muestra(x.n, x.fecha, x.especialidad)
        print(f"Muestra para el revisor: {fm}\nClave (no entregar): {fc}")
        return
    r = comparar(x.archivo, x.clave)
    print(f"{r['n']} casos. κ ponderado = {r['kappa']:.2f} (meta ≥ 0,70) · acuerdo exacto "
          f"{100 * r['acuerdo']:.0f}% · κ de la prioridad inicial = {r['kappa_prioridad_inicial']:.2f}".replace(".", ","))
    print("\nPropuesta (filas) vs revisor (columnas):\n" + r["matriz"].to_string())
    if len(r["desacuerdo"]):
        print("\nCasos en desacuerdo (revisarlos ajusta la regla o la guía):\n" + r["desacuerdo"].to_string(index=False))


if __name__ == "__main__":
    main()
