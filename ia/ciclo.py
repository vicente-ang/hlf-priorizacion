"""Ciclo de mejora de la rúbrica ("entrenamiento" del agente) sin fuga de datos.

  rúbrica v0 ──► agente en TRAIN ──► regulador ve errores + verdad de TRAIN ──► propone ≤ 3 reglas generales
                                                                               │ filtro de fuga
                                       acepta solo si mejora en DEV ◄── agente en DEV con la rúbrica candidata
  ... N iteraciones ... ──► rúbrica final ──► se mide UNA vez en TEST (otros parámetros y otra redacción)

No se ajustan pesos del modelo: se ajustan sus instrucciones. Cada versión queda en ia/rubrica/ y la bitácora en
ia/resultados/ciclo.csv (lo que se grafica como "aprendizaje").

Uso:
  python -m ia.ciclo --modo simulado                        # circuito completo sin red (agente y regulador simulados)
  python -m ia.ciclo --modo bedrock --iteraciones 3 --muestra 120   # con Bedrock (BEDROCK_MODEL_ID, y opcional
                                                                    # BEDROCK_MODEL_ID_REGULADOR para el revisor)
  python -m ia.ciclo --modo bedrock --solo-informe                  # rehace la tabla de TEST sin llamar a Bedrock
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from ia import agente, evaluar, regulador  # noqa: E402

MUNDO = RAIZ / "data" / "mundo"
RUBRICAS = RAIZ / "ia" / "rubrica"
RESULTADOS = RAIZ / "ia" / "resultados"


def _verdad(conjunto: str) -> pd.DataFrame:
    return pd.read_csv(MUNDO / f"{conjunto}_verdad" / "verdad.csv")


def _ids(conjunto: str, muestra: int | None) -> list | None:
    if not muestra:
        return None
    le = pd.read_csv(MUNDO / conjunto / "lista_espera.csv")
    return list(le.sample(min(muestra, len(le)), random_state=7).id_paciente)


def _fichas(conjunto: str, ids) -> dict:
    datos = agente.Datos.cargar(MUNDO / conjunto)
    notas = agente.cargar_notas(MUNDO / conjunto)
    corte = datos.fecha_referencia()
    return {pid: agente.ficha(p, notas.get(pid, []), corte) for pid, p in datos.pacientes.items()
            if ids is None or pid in ids}


def correr(modo: str = "simulado", iteraciones: int = 3, muestra: int | None = None, eps: float = 0.005) -> pd.DataFrame:
    RESULTADOS.mkdir(parents=True, exist_ok=True)
    rubrica = (RUBRICAS / "v0.md").read_text(encoding="utf-8")
    ids = {c: _ids(c, muestra) for c in ("train", "dev", "test")}
    notas_train = pd.read_csv(MUNDO / "train" / "notas_clinicas.csv").texto.tolist()
    ngr = regulador.ngramas(notas_train)
    modelo_reg = os.environ.get("BEDROCK_MODEL_ID_REGULADOR")

    def medir(conjunto, rub):
        df = agente.evaluar(MUNDO / conjunto, rub, modo, ids=ids[conjunto])
        m = evaluar.metricas(evaluar.desde_agente(df)["ia"], _verdad(conjunto))
        return df, m

    _, m_dev = medir("dev", rubrica)
    bitacora = [{"iteracion": 0, "version": "v0", "aceptada": True, "cambios": "", "rechazos": "", **{f"dev_{k}": v
                 for k, v in m_dev.items()}}]
    version = 0
    probadas: list[str] = []
    rechazos_previos: list[str] = []
    for it in range(1, iteraciones + 1):
        df_tr, m_tr = medir("train", rubrica)
        errs = regulador.errores(df_tr, _verdad("train"))
        prop = regulador.proponer(errs, _fichas("train", set(errs.id_paciente)), rubrica, modo, model_id=modelo_reg,
                                  ya_probadas=probadas, rechazadas=rechazos_previos)
        cambios, rechazos = regulador.filtro_fuga(prop.get("cambios", []), ngr)
        rechazos_previos = rechazos
        if not cambios:
            bitacora.append({"iteracion": it, "version": f"v{version}", "aceptada": False, "cambios": "",
                             "rechazos": " | ".join(rechazos) or "sin propuestas", **{f"dev_{k}": v for k, v in m_dev.items()}})
            continue
        candidata = regulador.aplicar(rubrica, cambios, f"v{version + 1}")
        _, m_cand = medir("dev", candidata)
        acepta = m_cand["objetivo"] > m_dev["objetivo"] + eps
        bitacora.append({"iteracion": it, "version": f"v{version + 1}" if acepta else f"v{version}", "aceptada": acepta,
                         "cambios": " | ".join(c["regla"] for c in cambios), "rechazos": " | ".join(rechazos),
                         **{f"dev_{k}": v for k, v in (m_cand if acepta else m_dev).items()},
                         "dev_objetivo_candidata": m_cand["objetivo"]})
        if not acepta:
            probadas += [c["regla"] for c in cambios]
        if acepta:
            version += 1
            rubrica, m_dev = candidata, m_cand
            (RUBRICAS / f"v{version}.md").write_text(rubrica, encoding="utf-8")
    log = pd.DataFrame(bitacora)
    log.to_csv(RESULTADOS / f"ciclo_{modo}.csv", index=False)
    # Medición final, UNA vez, en TEST (también la regla y FIFO para comparar)
    df_test = agente.evaluar(MUNDO / "test", rubrica, modo, ids=ids["test"])
    df_test.to_csv(RESULTADOS / f"propuestas_test_{modo}_final.csv", index=False)
    informe(modo, log, df_test, f"v{version}")
    return log


def informe(modo: str, log: pd.DataFrame | None = None, df_test: pd.DataFrame | None = None,
            version: str | None = None) -> pd.DataFrame:
    """Escribe test_final_<modo>.csv y resumen_ciclo_<modo>.md. Sin argumentos los rehace desde los CSV ya guardados
    (no llama a Bedrock): sirve para recalcular la tabla si cambia la forma de medir."""
    log = log if log is not None else pd.read_csv(RESULTADOS / f"ciclo_{modo}.csv")
    df_test = df_test if df_test is not None else pd.read_csv(RESULTADOS / f"propuestas_test_{modo}_final.csv")
    version = version or str(log[log.aceptada.astype(bool)].version.iloc[-1])
    otros = {}
    kw = RESULTADOS / "propuestas_test_simulado_final.csv"      # el agente sin LLM (palabras clave), mismo TEST
    if modo != "simulado" and kw.exists():
        otros["palabras_clave"] = pd.read_csv(kw)
    comp = evaluar.comparar(MUNDO / "test", df_test, otros)   # todos los métodos sobre los mismos pacientes
    comp.to_csv(RESULTADOS / f"test_final_{modo}.csv", index=False)
    cnt = evaluar.conteos(MUNDO / "test", df_test, otros)
    cnt.to_csv(RESULTADOS / f"test_conteos_{modo}.csv", index=False)
    (RESULTADOS / f"resumen_ciclo_{modo}.md").write_text(
        f"# Ciclo de mejora de la rúbrica ({modo})\n\nVersión final: {version}.\n\n## Bitácora (DEV)\n\n"
        + log[["iteracion", "version", "aceptada", "dev_objetivo", "dev_sens_deterioro", "dev_ndcg10", "dev_kappa",
               "cambios", "rechazos"]].to_markdown(index=False)
        + f"\n\n## Medición final en TEST (una sola vez, los mismos {len(df_test)} pacientes para todos los métodos)\n\n"
        + comp.to_markdown(index=False)
        + "\n\nEn números absolutos:\n\n" + cnt.to_markdown(index=False) + "\n", encoding="utf-8")
    return comp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modo", choices=["simulado", "bedrock"], default="simulado")
    ap.add_argument("--iteraciones", type=int, default=3)
    ap.add_argument("--muestra", type=int, help="pacientes por conjunto (para acotar costo y tiempo)")
    ap.add_argument("--solo-informe", action="store_true",
                    help="rehace la tabla de TEST y el resumen desde los CSV guardados, sin llamar a Bedrock")
    a = ap.parse_args()
    if a.solo_informe:
        print(informe(a.modo).to_string(index=False))
        return
    log = correr(a.modo, a.iteraciones, a.muestra)
    print(log[["iteracion", "version", "aceptada", "dev_objetivo", "cambios", "rechazos"]].to_string(index=False))
    print((RESULTADOS / f"resumen_ciclo_{a.modo}.md").read_text(encoding="utf-8").split("## Medición final")[1])


if __name__ == "__main__":
    main()
