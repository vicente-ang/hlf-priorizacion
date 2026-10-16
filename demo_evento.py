"""Escena clave de la demo: llega un evento clínico y la lista se reordena en el acto.

Uso:
  python demo_evento.py                          # elige un paciente 'baja' sin señales, en la mitad de su lista
  python demo_evento.py --paciente PAC-HLF-00123 --subtipo "triage ESI 2"
  python demo_evento.py --modo puntaje           # misma escena con el puntaje v1
  BEDROCK_MODEL_ID=... AWS_REGION=... python demo_evento.py     # explicación redactada por Bedrock

Subtipos disponibles:
  ingreso hospitalario / ingreso UCI / triage ESI 2 / descompensación grave   (grave -> carril rápido)
  descompensación / resultado alterado / aumento dosis                        (moderado -> acorta su plazo)
"""
import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from motor import MODOS, Datos, cargar_regla, priorizar  # noqa: E402
from motor.explicar import explicar_con_bedrock  # noqa: E402

TIPO = {"ingreso hospitalario": ("hospitalizacion", "grave"), "ingreso UCI": ("hospitalizacion", "grave"),
        "triage ESI 2": ("visita_urgencia", "grave"), "descompensación grave": ("visita_urgencia", "grave"),
        "descompensación": ("visita_urgencia", "moderada"), "resultado alterado": ("examen_alterado", "moderada"),
        "aumento dosis": ("cambio_farmaco", "moderada")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--corte", default=None, help="fecha de la lista (por defecto, la más reciente de los datos)")
    ap.add_argument("--paciente", default=None)
    ap.add_argument("--subtipo", default="ingreso hospitalario", choices=list(TIPO))
    ap.add_argument("--modo", default=None, choices=MODOS)
    a = ap.parse_args()

    datos, cfg = Datos.cargar(), cargar_regla()
    a.corte = a.corte or datos.fecha_referencia().isoformat()
    modo = a.modo or cfg.get("modo_por_defecto", "carril_plazo")
    antes = priorizar(datos, a.corte, cfg, modo=modo)
    if a.paciente:
        pid = a.paciente
        if pid not in datos.pacientes:
            sys.exit(f"No existe el paciente {pid}.")
        if pid not in set(antes.id_paciente):
            from motor import evaluar_paciente
            motivo = evaluar_paciente(datos.pacientes[pid], a.corte, cfg)["motivo_fuera"]
            sys.exit(f"{pid} no está en la lista al {a.corte} ({motivo}). Elija otro paciente.")
    else:   # paciente 'baja' sin señales, lo más cerca posible de la mitad de su lista
        cand = antes[(antes.prioridad_inicial == "baja") & (~antes.carril_rapido)
                     & (antes.senales_deterioro.str.len() == 0) & (antes.motivo_puesto != "cupo por antigüedad")]
        pid = cand.iloc[(cand.puesto / cand.en_especialidad - 0.6).abs().argsort().iloc[0]]["id_paciente"]
    r_antes = antes[antes.id_paciente == pid].iloc[0].to_dict()

    tipo, sev = TIPO[a.subtipo]
    evento = {"fecha_evento": a.corte, "tipo_evento": tipo, "subtipo": a.subtipo, "severidad": sev}

    t0 = time.perf_counter()
    datos2 = datos.con_evento(pid, evento)                                         # 1) llega el evento
    despues = priorizar(datos2, a.corte, cfg, modo=modo, especialidad=r_antes["especialidad"])   # 2) se reordena
    ms = (time.perf_counter() - t0) * 1000
    r_despues = despues[despues.id_paciente == pid].iloc[0].to_dict()

    p = datos.pacientes[pid]
    print(f"\nPaciente {pid} · {p.especialidad} · {p.diagnostico} · prioridad médica '{p.prioridad_inicial}'"
          f" · {r_antes['dias_espera']} días en lista · modo {modo}")
    print(f"Evento nuevo ({a.corte}): {a.subtipo} ({sev})")
    print("-" * 78)
    print(f"ANTES   puesto {r_antes['puesto']:>3} de {r_antes['en_especialidad']} en {p.especialidad}  [{r_antes['motivo_puesto']}]")
    print(f"DESPUÉS puesto {r_despues['puesto']:>3} de {r_despues['en_especialidad']} en {p.especialidad}  [{r_despues['motivo_puesto']}]")
    print(f"Calculado en {ms:.0f} ms. Queda como ALERTA para el equipo (reporte de mañana, KPI < 72 h); la lista")
    print("vigente se reprioriza el lunes, salvo que el jefe o la gestora lo adelanten con un motivo.")
    print("-" * 78)
    texto, fuente = explicar_con_bedrock(r_despues, r_antes)
    print(f"Explicación ({fuente}):\n   {texto}\n")


if __name__ == "__main__":
    main()
