"""Punto de entrada para AWS Lambda: recálculo disparado por evento.

Flujo previsto:  evento nuevo -> EventBridge -> esta Lambda -> puesto proyectado + explicación -> DynamoDB / API.
Con el corte semanal (motor/cortes.py) el resultado es una ALERTA: el puesto que tendría si se repriorizara hoy.
La lista vigente no se mueve sola; se reprioriza el día de corte o se adelanta a mano con un motivo.
Para el prototipo los CSV van empaquetados junto al código (o en /tmp tras bajarlos de S3);
el equipo de AWS reemplaza `_datos()` por la lectura desde S3/DynamoDB.
Ojo al desplegar: pandas y pyyaml NO vienen en el runtime de Lambda (usar imagen de contenedor o una layer).

Evento de entrada (detail de EventBridge o body de API Gateway):
{
  "id_paciente": "PAC-HLF-00136",
  "corte": "2026-10-13",                         # opcional, por defecto la fecha del evento
  "modo": "carril_plazo",                        # opcional
  "evento": {"fecha_evento": "2026-10-13", "tipo_evento": "hospitalizacion",
             "subtipo": "ingreso hospitalario", "severidad": "grave"}
}
"""
import json
import os
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motor import Datos, cargar_regla, priorizar  # noqa: E402
from motor.explicar import explicar_con_bedrock  # noqa: E402

_CACHE = {}


def _datos():
    if "datos" not in _CACHE:   # se reutiliza entre invocaciones de la misma Lambda
        _CACHE["datos"] = Datos.cargar(os.environ.get("DATA_DIR"))
        _CACHE["cfg"] = cargar_regla(os.environ.get("REGLA_PATH"))
    return _CACHE["datos"], _CACHE["cfg"]


def _json(x):
    if isinstance(x, date):
        return x.isoformat()
    if hasattr(x, "item"):          # tipos numpy
        return x.item()
    raise TypeError(type(x))


def _fila(df, pid):
    fila = df[df.id_paciente == pid]
    return fila.iloc[0].to_dict() if len(fila) else None


def lambda_handler(event, context=None):
    payload = event.get("detail") or event
    if isinstance(payload.get("body"), str):
        payload = json.loads(payload["body"])
    pid, ev = payload["id_paciente"], payload.get("evento")
    datos, cfg = _datos()
    if pid not in datos.pacientes:
        return {"statusCode": 404, "body": json.dumps({"error": f"paciente {pid} no existe"})}
    corte = payload.get("corte") or (ev or {}).get("fecha_evento") or date.today().isoformat()
    try:
        date.fromisoformat(str(corte))
        if ev:
            date.fromisoformat(str(ev["fecha_evento"]))
            if ev.get("severidad") not in ("leve", "moderada", "grave"):
                raise ValueError("severidad debe ser leve, moderada o grave")
            for campo in ("tipo_evento", "subtipo"):
                if not ev.get(campo):
                    raise ValueError(f"falta {campo} en el evento")
    except (ValueError, KeyError, TypeError) as e:
        return {"statusCode": 400, "body": json.dumps({"error": f"evento inválido: {e}"}, ensure_ascii=False)}
    modo = payload.get("modo")
    esp = datos.pacientes[pid].especialidad

    antes = _fila(priorizar(datos, corte, cfg, modo=modo, especialidad=esp), pid)
    if ev:
        datos = datos.con_evento(pid, ev)
        _CACHE["datos"] = datos      # el evento queda registrado para los próximos cálculos
    despues = _fila(priorizar(datos, corte, cfg, modo=modo, especialidad=esp), pid)
    if despues is None:              # fallecido, atendido o aún no ingresa
        return {"statusCode": 200, "body": json.dumps({"en_lista": False, "id_paciente": pid})}
    texto, fuente = explicar_con_bedrock(despues, antes)
    cuerpo = {"antes": antes, "despues": despues, "explicacion": texto, "fuente_explicacion": fuente}
    return {"statusCode": 200, "body": json.dumps(cuerpo, ensure_ascii=False, default=_json)}


if __name__ == "__main__":   # prueba local
    ejemplo = {"id_paciente": "PAC-HLF-00136", "evento": {"fecha_evento": "2026-10-13", "tipo_evento": "hospitalizacion",
                                                          "subtipo": "ingreso hospitalario", "severidad": "grave"}}
    r = json.loads(lambda_handler(ejemplo)["body"])
    print(f"puesto {r['antes']['puesto']} -> {r['despues']['puesto']} de {r['despues']['en_especialidad']}"
          f" · {r['despues']['motivo_puesto']}")
    print(r["explicacion"])
