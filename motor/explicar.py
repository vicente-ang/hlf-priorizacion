"""Explicaciones de por qué un paciente está en su puesto.

Regla de diseño: el LLM NO decide la prioridad. El orden lo calcula la regla
(motor/priorizacion.py); el LLM solo redacta, en lenguaje claro, los hechos que la regla usó.

- explicacion_plantilla(): determinista, sin dependencias. Es el respaldo si Bedrock falla.
- explicar_con_bedrock(): usa Amazon Bedrock (Converse API) y cae a la plantilla ante cualquier error.
  Configurar con variables de entorno:
    BEDROCK_MODEL_ID   id del modelo o inference profile habilitado en su cuenta (ej. un modelo Claude)
    AWS_REGION         región donde lo habilitaron

Funciona con la regla MVP (evaluaciones de motor.priorizacion) y con el puntaje v1 (motor.puntaje).
`r` puede traer `puesto`, `en_especialidad` y `motivo_puesto` si viene de la lista priorizada.
"""
from __future__ import annotations

import os


def _fmt_fecha(f) -> str:
    return f.strftime("%d-%m-%Y") if _hay(f) else ""


def _hay(x) -> bool:
    """True si el valor existe (None y NaN de pandas cuentan como vacío)."""
    if x is None:
        return False
    try:
        return not (x != x)   # NaN != NaN
    except Exception:
        return True


def _num(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _fuera(r: dict) -> str | None:
    if r.get("en_lista", True):
        return None
    motivo = {"fallecido": "falleció", "atendido": "ya fue atendido", "aun_no_ingresa": "aún no ingresa a la lista",
              "alta_indicada": "el médico indicó alta o contrarreferencia"}
    return f"{r['id_paciente']} no está en la lista: {motivo.get(r['motivo_fuera'], r['motivo_fuera'])}."


def _hechos_mvp(r: dict) -> list[str]:
    h = []
    if r.get("puesto"):
        h.append(f"Puesto {r['puesto']} de {r['en_especialidad']} en {r['especialidad']}"
                 + (f" (con la regla actual sería el {r['puesto_regla_actual']})" if r.get("puesto_regla_actual") else "")
                 + ".")
    if _hay(r.get("prioridad_dinamica")):
        origen = r.get("prioridad_origen") or "especialista"
        t1 = f"Prioridad de partida {r['prioridad_inicial']}" + (
            f" (la dio el especialista; espera desde el {_fmt_fecha(r['fecha_ingreso'])})" if origen == "especialista"
            else f" ({origen})")
        if r["prioridad_dinamica"] != r["prioridad_inicial"]:
            h.append(f"{t1}. Hoy es {r['prioridad_dinamica']} por {r['motivo_prioridad']}.")
        else:
            h.append(f"{t1}; hoy sigue {r['prioridad_dinamica']}.")
    if str(r.get("motivo_puesto", "")).startswith("adelantado"):
        h.append(f"{str(r['motivo_puesto']).capitalize()}.")
    if r["carril_rapido"]:
        extra = ""
        nivel = r.get("nivel_cuidado")
        if _hay(nivel) and int(nivel) < 3:
            from .clusters import NIVEL_CUIDADO
            extra = f" Dentro del carril se ordena por nivel de cuidado ({NIVEL_CUIDADO[int(nivel)]})"
            if (r.get("recurrencia") or 0) > 1:
                extra += f", {int(r['recurrencia'])} episodios graves en 12 meses"
            extra += f" y riesgo LACE {int(r['lace'])}." if _hay(r.get("lace")) else "."
        h.append(f"Está en el carril rápido por: {r['motivo_carril']}.{extra}")
    elif r.get("motivo_puesto") == "cupo por antigüedad":
        h.append(f"Ocupa un cupo reservado por antigüedad: lleva {r['dias_espera']} días esperando.")
    if r["dias_atraso"] > 0:
        h.append(f"Plazo vigente: {r['motivo_plazo']}; vencía el {_fmt_fecha(r['fecha_objetivo'])} y lleva "
                 f"{r['dias_atraso']} días de atraso ({_num(r['razon_atraso'])} veces su plazo).")
    else:
        h.append(f"Plazo vigente: {r['motivo_plazo']}; vence el {_fmt_fecha(r['fecha_objetivo'])} "
                 f"(faltan {-r['dias_atraso']} días).")
    if _hay(r.get("indicacion_revisar")):
        h.append(f"Indicación de control por revisar: {r['indicacion_revisar']}.")
    if r["senales_deterioro"]:
        h.append("Señales de deterioro: " + "; ".join(r["senales_deterioro"]) + ".")
    if r["senales_mejora"]:
        h.append("Señales de mejora: " + "; ".join(r["senales_mejora"]) + ".")
    if r.get("eventos_no_relacionados"):
        h.append("No relacionado con la derivación, no lo mueve: " + "; ".join(r["eventos_no_relacionados"]) + ".")
    if _hay(r.get("alerta_contacto")):
        h.append(f"Agenda: {r['alerta_contacto']} (no cambia su lugar en la lista).")
    return h


def _hechos_v1(r: dict) -> list[str]:
    h = [f"Puntaje {r['puntaje']:g}: prioridad médica {r['prioridad_inicial']} y {r['dias_espera']} días en lista."]
    if r.get("top_razones"):
        h.append("Principales razones: " + "; ".join(r["top_razones"]) + ".")
    if r.get("bandera_revision") is True:
        h.append(f"Requiere revisión clínica: {r['motivo_bandera']}.")
    if _hay(r.get("alerta_contacto")):
        h.append(f"Agenda: {r['alerta_contacto']} (no afecta la prioridad clínica).")
    return h


def _es_v1(r: dict) -> bool:
    return r.get("modo") == "puntaje" or "carril_rapido" not in r


def hechos(r: dict) -> list[str]:
    """Las frases de la explicación, por separado (para mostrarlas en líneas en la interfaz)."""
    fuera = _fuera(r)
    if fuera:
        return [fuera]
    return _hechos_v1(r) if _es_v1(r) else _hechos_mvp(r)


def explicacion_plantilla(r: dict, anterior: dict | None = None) -> str:
    fuera = _fuera(r)
    if fuera:
        return fuera
    partes = []
    if anterior and anterior.get("en_lista") and anterior.get("puesto") and r.get("puesto"):
        if r["puesto"] < anterior["puesto"]:
            partes.append(f"Subió del puesto {anterior['puesto']} al {r['puesto']}.")
        elif r["puesto"] > anterior["puesto"]:
            partes.append(f"Bajó del puesto {anterior['puesto']} al {r['puesto']}.")
    partes += _hechos_v1(r) if _es_v1(r) else _hechos_mvp(r)
    partes.append("Es una propuesta: el equipo de gestión la valida antes de citar.")
    return " ".join(partes)


def construir_prompt(r: dict, anterior: dict | None = None) -> str:
    hechos = _hechos_v1(r) if _es_v1(r) else _hechos_mvp(r)
    if anterior and anterior.get("puesto") and r.get("puesto"):
        hechos.insert(0, f"Antes estaba en el puesto {anterior['puesto']}.")
    return (
        "Eres un asistente para el equipo de gestión de listas de espera de un hospital público chileno.\n"
        "Redacta en español de Chile, en máximo 3 oraciones, por qué este paciente está en este puesto "
        "(y por qué cambió, si se indica el puesto anterior).\n"
        "Reglas estrictas:\n"
        "1. Usa SOLO los hechos listados. No inventes diagnósticos, causas ni recomendaciones clínicas.\n"
        "2. Si está en el carril rápido, dilo primero y nombra el evento.\n"
        "3. Menciona el plazo y el atraso con sus números.\n"
        "4. Termina indicando que es una propuesta que valida el equipo de gestión.\n\n"
        f"Paciente {r['id_paciente']}, {r['especialidad']}, prioridad médica inicial {r['prioridad_inicial']}, "
        f"{r['dias_espera']} días en lista.\nHechos:\n- " + "\n- ".join(hechos)
    )


def explicar_con_bedrock(r: dict, anterior: dict | None = None, model_id: str | None = None,
                         region: str | None = None) -> tuple[str, str]:
    """Devuelve (texto, fuente) con fuente = 'bedrock' o 'plantilla'."""
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    if not model_id or not r.get("en_lista", True):
        return explicacion_plantilla(r, anterior), "plantilla"
    try:
        import boto3  # viene en AWS Lambda; localmente: pip install boto3

        cliente = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))
        resp = cliente.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": construir_prompt(r, anterior)}]}],
            inferenceConfig={"maxTokens": 300, "temperature": 0},
        )
        return resp["output"]["message"]["content"][0]["text"].strip(), "bedrock"
    except Exception:  # sin credenciales, sin red, modelo no habilitado, etc.
        return explicacion_plantilla(r, anterior), "plantilla"


def redactar_con_bedrock(prompt: str, respaldo: str, max_tokens: int = 400, model_id: str | None = None,
                         region: str | None = None) -> tuple[str, str]:
    """Llamada genérica a Bedrock (Converse). Ante cualquier problema devuelve el texto de respaldo."""
    model_id = model_id or os.environ.get("BEDROCK_MODEL_ID")
    if not model_id:
        return respaldo, "plantilla"
    try:
        import boto3

        cliente = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION"))
        resp = cliente.converse(modelId=model_id, messages=[{"role": "user", "content": [{"text": prompt}]}],
                                inferenceConfig={"maxTokens": max_tokens, "temperature": 0})
        return resp["output"]["message"]["content"][0]["text"].strip(), "bedrock"
    except Exception:
        return respaldo, "plantilla"
