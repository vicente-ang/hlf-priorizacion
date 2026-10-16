"""¿Aguanta el tamaño real del HLF? Prueba de escala del motor.

El HLF tiene 26.356 consultas de especialidad en lista de espera (presentación del hospital) y unas
50 especialidades. Esta prueba replica los 500 pacientes sintéticos hasta ~26.500, repartidos en 49
especialidades, y mide:
  - cargar los datos,
  - priorizar la lista completa (todas las especialidades),
  - el camino de la Lambda: llega un evento y se reordena la especialidad de ese paciente.

Uso:  python sim/escala.py [--copias 53]   -> sim/resultados/escala.md
"""
from __future__ import annotations

import argparse
import copy
import statistics
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
from motor.priorizacion import cargar_regla, priorizar  # noqa: E402
from motor.puntaje import Datos  # noqa: E402

HOY = None   # fecha de referencia de los datos (se fija al correr)


def replicar(base: Datos, copias: int) -> Datos:
    pacientes = {}
    for k in range(copias):
        for pid, p in base.pacientes.items():
            q = copy.copy(p)
            q.id_paciente = f"{pid}-{k:02d}"
            q.especialidad = f"{p.especialidad} {k % 7 + 1}"      # 7 especialidades x 7 = 49
            pacientes[q.id_paciente] = q
    return Datos(pacientes, base.agenda)


def medir(fn, repeticiones=5):
    tiempos = []
    for _ in range(repeticiones):
        t0 = time.perf_counter()
        fn()
        tiempos.append(time.perf_counter() - t0)
    return statistics.median(tiempos)


def correr(copias=53):
    t0 = time.perf_counter()
    global HOY
    base = Datos.cargar()
    HOY = base.fecha_referencia().isoformat()
    cfg = cargar_regla()
    datos = replicar(base, copias)
    carga = time.perf_counter() - t0
    n = len(datos.pacientes)
    n_esp = len({p.especialidad for p in datos.pacientes.values()})

    t_lista = medir(lambda: priorizar(datos, HOY, cfg), repeticiones=3)
    pid = next(iter(datos.pacientes))
    esp = datos.pacientes[pid].especialidad
    evento = {"fecha_evento": HOY, "tipo_evento": "hospitalizacion", "subtipo": "ingreso hospitalario",
              "severidad": "grave"}
    t_evento = medir(lambda: priorizar(datos.con_evento(pid, evento), HOY, cfg, especialidad=esp))
    en_esp = sum(1 for p in datos.pacientes.values() if p.especialidad == esp)

    md = ["# Prueba de escala\n",
          f"Pacientes: **{n:,}** (el HLF tiene 26.356 en lista) · especialidades: **{n_esp}**\n".replace(",", "."),
          "| Operación | Tiempo |", "|---|---|",
          f"| Cargar datos y replicar | {carga:.1f} s |".replace(".", ","),
          f"| Priorizar la lista completa ({n_esp} especialidades) | {t_lista:.1f} s |".replace(".", ","),
          f"| Llega un evento y se reordena su especialidad (~{en_esp} pacientes) | {t_evento * 1000:.0f} ms |",
          "", "Medido en un solo núcleo, sin paralelizar ni cachear. Meta del hospital: reevaluar en < 72 horas."]
    texto = "\n".join(md) + "\n"
    salida = RAIZ / "sim" / "resultados"
    salida.mkdir(parents=True, exist_ok=True)
    (salida / "escala.md").write_text(texto, encoding="utf-8")
    return texto


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--copias", type=int, default=53)
    print(correr(ap.parse_args().copias))
