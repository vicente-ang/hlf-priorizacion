"""Mundo sintético con VERDAD CONOCIDA para entrenar y evaluar al agente sin médicos (todavía).

Por qué existe: para saber si un ordenamiento es bueno hace falta saber cuál es el bueno. Sin especialistas, la
alternativa de usar otro LLM como "médico" es circular (dos LLM de acuerdo no prueban que estén en lo correcto).
Aquí cada paciente tiene una GRAVEDAD LATENTE S(t) entre 0 y 1 que evoluciona semana a semana mientras espera,
y de ella salen los datos que el hospital sí ve: eventos, mediciones y NOTAS CLÍNICAS en texto (controles del
CESFAM, epicrisis). La verdad es el riesgo de un desenlace grave en los próximos 90 días, que se calcula con el
modelo y el agente NUNCA ve.

Trayectorias (los patrones del documento de pacientes de ejemplo del hospital): estable, deterioro progresivo,
deterioro agudo (crisis), mejora y fluctuante. Hay además distractores: urgencias que no tienen que ver con la
derivación (reunión 7) y notas vagas o engañosas.

Conjuntos (semillas distintas; TEST además con otros parámetros y otra redacción de las notas):
  train   para que el regulador analice errores y proponga cambios a la rúbrica (ve la verdad)
  dev     para aceptar o rechazar cada cambio (solo métricas agregadas, sin casos)
  test    se usa UNA vez al final. Otra mezcla de trayectorias, más ruido y frases nuevas.

Salida por conjunto (mismo esquema que el dataset del hospital, así corren la regla, el agente y la app):
  data/mundo/<conjunto>/      pacientes, lista_espera, eventos_clinicos (con diagnóstico), mediciones,
                              citaciones, notas_clinicas.csv
  data/mundo/<conjunto>_verdad/verdad.csv   riesgo_90d, categoria_ideal, gravedad, trayectoria (NO dárselo al agente)

Los parámetros son supuestos del equipo para tener un banco de pruebas objetivo; la verdad del mundo real la dan
los especialistas (muestra ciega, κ). Uso:  python -m ia.mundo   (escribe train, dev y test)
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
SALIDA = RAIZ / "data" / "mundo"
CORTE = date(2026, 10, 12)

# especialidad -> [(sub_especialidad, cie10, texto, gravedad_base)]  (mezcla del dataset del hospital)
CATALOGO = {
    "Cardiología": [("Cardiología adulto", "I10", "Hipertensión esencial", .25), ("Cardiología adulto", "I20", "Angina de pecho", .45),
                    ("Insuficiencia cardíaca", "I50", "Insuficiencia cardíaca", .50)],
    "Broncopulmonar": [("Asma", "J45", "Asma", .30), ("EPOC", "J44", "EPOC", .45)],
    "Endocrinología": [("Diabetes", "E11", "Diabetes mellitus tipo 2", .35), ("Diabetes", "E66", "Obesidad", .15),
                       ("Tiroides", "E03", "Hipotiroidismo", .15)],
    "Gastroenterología": [("Digestivo alto", "K21", "Enfermedad por reflujo", .15), ("Hígado", "K70", "Enfermedad hepática", .45)],
    "Neurología": [("Cefaleas", "G43", "Migraña", .20), ("Epilepsia", "G40", "Epilepsia", .40)],
    "Salud Mental": [("Psicología", "F41", "Trastorno de ansiedad", .25), ("Psiquiatría adulto", "F32", "Episodio depresivo", .40)],
    "Traumatología": [("Columna", "M54", "Lumbago", .20), ("Hombro", "M75", "Lesión del hombro", .15), ("Rodilla", "M17", "Artrosis de rodilla", .20)],
}
PESO_ESP = {"Cardiología": 101, "Traumatología": 104, "Endocrinología": 85, "Salud Mental": 79, "Broncopulmonar": 54,
            "Neurología": 41, "Gastroenterología": 36}
# medición por especialidad: (tipo, unidad, normal, cambio con gravedad 1, ruido, fuera_de_rango(valor)->bool)
MEDICION = {
    "Cardiología": ("presion_sistolica", "mmHg", 120, 45, 9, lambda v: v > 139 or v < 90),
    "Broncopulmonar": ("saturacion_o2", "%", 98, -8, 1.2, lambda v: v < 95),
    "Endocrinología": ("HbA1c", "%", 6.0, 4.0, .4, lambda v: v > 6.4),
    "Gastroenterología": ("glicemia", "mg/dL", 100, 60, 12, lambda v: v > 140),
    "Neurología": ("escala_dolor_eva", "puntos", 2, 7, 1.0, lambda v: v > 3),
    "Salud Mental": ("PHQ9", "puntos", 4, 18, 2.0, lambda v: v > 9),
    "Traumatología": ("escala_dolor_eva", "puntos", 2, 7, 1.0, lambda v: v > 3),
}
# código relacionado para hospitalizaciones/urgencias de cada especialidad, y distractores no relacionados
RELACIONADO = {"Cardiología": ["I20.0", "I50.0", "I21.4"], "Broncopulmonar": ["J44.1", "J45.9", "J18.9"],
               "Endocrinología": ["E11.6", "E87.1", "E10.1"], "Gastroenterología": ["K92.2", "K70.4", "K85.9"],
               "Neurología": ["G40.9", "G43.9", "I63.9"], "Salud Mental": ["F32.2", "X84", "F41.0"],
               "Traumatología": ["M54.5", "S72.0", "M17.1"]}
DISTRACTOR = {"Traumatología": [("N20.0", "cólico renal"), ("J06.9", "infección respiratoria alta")],
              "_otro": [("S93.4", "esguince de tobillo"), ("S52.5", "fractura de radio"), ("N39.0", "infección urinaria")]}
COMUNAS = {"Puente Alto": .38, "La Florida": .20, "La Pintana": .13, "La Granja": .11, "San Ramón": .10,
           "San José de Maipo": .05, "Pirque": .03}
PREVISION = {"FONASA B": .35, "FONASA A": .29, "FONASA C": .21, "FONASA D": .12, "ISAPRE": .04}
ORIGEN = {"CESFAM/APS": .61, "Urgencia": .20, "Hospitalización": .10, "Otro hospital red": .09}
CHARLSON_APS = [("I10", .30), ("E11", .15), ("E11.2", .04), ("J44", .06), ("I50", .05), ("N18", .05), ("I63", .03)]

# ------------------------------------------------------------------------------------------------ notas en texto
# Dos juegos de frases: A (train y dev) y B (test). Así TEST mide si el agente entiende, no si memorizó frases.
SINTOMAS = {  # especialidad -> {nivel: ([frases A], [frases B])}
    "Cardiología": {
        "bajo": (["asintomático cardiovascular, sin dolor torácico", "sin angina, tolera actividad habitual"],
                 ["niega molestias precordiales, camina sin problemas", "capacidad funcional conservada, sin dolor"]),
        "medio": (["dolor torácico ocasional de esfuerzo, CF II", "disnea a medianos esfuerzos, edema leve"],
                  ["opresión en el pecho al subir escaleras", "se cansa más que antes, tobillos algo hinchados"]),
        "alto": (["angina de reposo en la última semana, CF III", "disnea de pequeños esfuerzos y ortopnea"],
                 ["dolor de pecho estando sentado varias veces esta semana", "no puede dormir acostado por falta de aire"])},
    "Broncopulmonar": {
        "bajo": (["sin exacerbaciones, buena adherencia a inhaladores", "auscultación sin sibilancias"],
                 ["respira bien, usa sus inhaladores", "pulmones limpios al examen"]),
        "medio": (["aumento de uso de rescate, sibilancias ocasionales", "tos y disnea en las mañanas"],
                  ["ocupa más el inhalador de rescate", "le falta el aire al despertar"]),
        "alto": (["exacerbación con disnea de reposo y saturación 89%", "tercera exacerbación en el trimestre"],
                 ["ahogo en reposo, oxímetro marca 88%", "vuelve a descompensarse por tercera vez en pocos meses"])},
    "Endocrinología": {
        "bajo": (["metas glicémicas cumplidas", "sin hipoglicemias, buena adherencia"],
                 ["exámenes en rango, bien controlado", "no ha tenido bajones de azúcar"]),
        "medio": (["glicemias elevadas pese a ajuste de dosis", "mala adherencia a la dieta, sube HbA1c"],
                  ["azúcar alta aunque se subió el medicamento", "no logra seguir la dieta, exámenes empeoran"]),
        "alto": (["hipoglicemias severas con pérdida de conciencia", "lesión en pie diabético que no cicatriza"],
                 ["se desmayó por azúcar baja dos veces", "herida en el pie que se está infectando"])},
    "Gastroenterología": {
        "bajo": (["sin síntomas digestivos de alarma", "pirosis controlada con tratamiento"],
                 ["digestión normal, sin molestias", "acidez controlada"]),
        "medio": (["dispepsia persistente pese a tratamiento", "dolor abdominal recurrente"],
                  ["sigue con molestias al estómago", "dolor de guata que va y viene"]),
        "alto": (["melena y anemia en exámenes", "ictericia y aumento de volumen abdominal"],
                 ["deposiciones negras y está pálido", "piel amarilla y abdomen hinchado"])},
    "Neurología": {
        "bajo": (["sin crisis desde último control", "cefalea controlada con tratamiento"],
                 ["no ha vuelto a convulsionar", "dolores de cabeza bien manejados"]),
        "medio": (["crisis ocasionales pese a tratamiento", "cefalea más frecuente, interfiere con trabajo"],
                  ["volvió a tener alguna crisis", "dolor de cabeza casi a diario"]),
        "alto": (["crisis a repetición esta semana", "cefalea con focalidad neurológica"],
                 ["varias convulsiones en pocos días", "dolor de cabeza con pérdida de fuerza en un brazo"])},
    "Salud Mental": {
        "bajo": (["ánimo eutímico, buena red de apoyo", "síntomas ansiosos leves y controlados"],
                 ["se siente bien, apoyado por su familia", "ansiedad leve que maneja"]),
        "medio": (["ánimo bajo persistente, insomnio", "crisis de pánico semanales"],
                  ["triste la mayor parte del tiempo, duerme mal", "ataques de angustia cada semana"]),
        "alto": (["ideación suicida con plan", "síntomas psicóticos y desorganización"],
                 ["dice que ha pensado cómo quitarse la vida", "escucha voces y está muy desorganizado"])},
    "Traumatología": {
        "bajo": (["dolor leve, responde a analgesia", "movilidad conservada"],
                 ["poco dolor, toma paracetamol", "se mueve sin limitación"]),
        "medio": (["dolor moderado que limita actividades", "dolor nocturno ocasional"],
                  ["el dolor no lo deja trabajar bien", "a veces lo despierta el dolor"]),
        "alto": (["pérdida de fuerza en extremidad y parestesias", "imposibilidad de marcha"],
                 ["se le duerme la pierna y no tiene fuerza", "no puede caminar por el dolor"])},
}
TENDENCIA = {"empeora": (["en progresión respecto al control anterior", "peor que en el control previo"],
                         ["ha ido empeorando desde la última vez", "más complicado que antes"]),
             "estable": (["sin cambios respecto al control anterior", "evolución estable"],
                         ["igual que la última vez", "se mantiene parecido"]),
             "mejora": (["mejoría respecto al control anterior", "buena respuesta al tratamiento"],
                        ["mejor que la última vez", "responde bien a lo indicado"])}
EXPLICITA = (["Se sugiere adelantar evaluación por especialista.", "Se solicita priorizar interconsulta."],
             ["Pedimos que lo vea el especialista lo antes posible.", "Reevaluado en CESFAM: requiere atención pronta."])


@dataclass
class Parametros:
    semilla: int
    n: int
    mezcla: dict = field(default_factory=lambda: {"estable": .45, "progresivo": .20, "agudo": .15, "mejora": .15,
                                                  "fluctuante": .05})
    ruido_notas: float = .15          # prob. de que una nota describa un nivel equivocado (nota vaga o engañosa)
    prob_explicita: float = .55       # prob. de que una nota de nivel alto y empeorando pida adelantar
    prob_distractor: float = .004     # prob. semanal de una urgencia no relacionada
    ruido_triage: float = .12         # error del especialista al priorizar en T1
    juego_frases: int = 0             # 0 = A, 1 = B


CONJUNTOS = {
    "train": Parametros(semilla=101, n=420),
    "dev": Parametros(semilla=202, n=300),
    "test": Parametros(semilla=303, n=300, mezcla={"estable": .38, "progresivo": .25, "agudo": .20, "mejora": .12,
                                                   "fluctuante": .05},
                       ruido_notas=.25, prob_explicita=.35, prob_distractor=.008, ruido_triage=.15, juego_frases=1),
}


# ------------------------------------------------------------------------------------------------ modelo latente
def p_grave_semana(s: float, charlson: int) -> float:
    """Probabilidad semanal de un desenlace grave (urgencia grave, hospitalización, UCI o muerte)."""
    return min(.9, (.0015 + .06 * s ** 3) * (1 + .12 * charlson))


def riesgo_90d(s: float, deriva: float, charlson: int) -> float:
    """Verdad: prob. de al menos un desenlace grave en 13 semanas si la tendencia sigue (sin atención)."""
    sobrevive = 1.0
    for k in range(13):
        sk = min(.98, max(.02, s + deriva * k))
        sobrevive *= 1 - p_grave_semana(sk, charlson)
    return 1 - sobrevive


UMBRAL_ALTA, UMBRAL_MEDIA = .30, .12   # categoría ideal por riesgo absoluto a 90 días


def _elegir(rnd, pesos: dict):
    return rnd.choices(list(pesos), weights=list(pesos.values()))[0]


def _frase(rnd, par, opciones):
    return rnd.choice(opciones[par.juego_frases])


def generar(nombre: str, par: Parametros, salida: Path = SALIDA) -> dict:
    rnd = random.Random(par.semilla)
    pac, le, ev, me, notas, verdad = [], [], [], [], [], []
    n_ev = 0
    for i in range(1, par.n + 1):
        pid = f"SIN-{nombre[:2].upper()}-{i:05d}"
        esp = _elegir(rnd, PESO_ESP)
        sub, cie, dx_txt, base = rnd.choice(CATALOGO[esp])
        edad = max(19, min(90, int(rnd.gauss(59, 16.8))))
        cron = [c for c, pr in CHARLSON_APS if rnd.random() < pr * (1.6 if edad >= 65 else 1)]
        from motor.clusters import charlson
        ch, _ = charlson(cron + [cie])
        ingreso = date(2025, 4, 21) + timedelta(days=rnd.randint(0, (date(2026, 9, 30) - date(2025, 4, 21)).days))
        tray = _elegir(rnd, par.mezcla)
        s = min(.95, max(.03, base + (.08 if edad >= 70 else 0) + rnd.gauss(0, .10)))
        s0 = s
        # Prioridad del especialista en T1: foto ruidosa de la gravedad al derivar (colador de 3 celdas)
        visto = s0 + rnd.gauss(0, par.ruido_triage)
        prio = "alta" if visto >= .52 else "media" if visto >= .28 else "baja"
        pendiente = {"progresivo": rnd.uniform(.006, .016), "mejora": -rnd.uniform(.004, .012)}.get(tray, 0.0)
        semanas = max(1, (CORTE - ingreso).days // 7)
        crisis = rnd.randint(int(semanas * .3), semanas) if tray == "agudo" else None
        fallece = None
        tipo_m, unidad, normal, delta, sd, fuera = MEDICION[esp]
        historial_s = []
        prox_control = rnd.randint(2, 8)
        prox_medicion = rnd.randint(1, 5)
        for t in range(semanas + 1):
            f = ingreso + timedelta(days=7 * t + rnd.randint(0, 6))
            if f > CORTE:
                f = CORTE
            # evolución de la gravedad latente
            if t > 0:
                if tray == "estable":
                    s += .25 * (s0 - s) + rnd.gauss(0, .015)
                elif tray == "fluctuante":
                    s = s0 + .15 * math.sin(t / 3.0) + rnd.gauss(0, .02)
                else:
                    s += pendiente + rnd.gauss(0, .012)
                if crisis is not None and t == crisis:
                    s += rnd.uniform(.30, .45)
                elif crisis is not None and t > crisis:
                    s -= .004
                s = min(.98, max(.02, s))
            historial_s.append(s)
            # eventos relacionados (salen de la gravedad)
            pg = p_grave_semana(s, ch)
            if rnd.random() < pg or (crisis is not None and t == crisis):
                n_ev += 1
                grave = s > .55 or (crisis is not None and t == crisis)
                ev.append({"id_paciente": pid, "id_evento": f"EV-{n_ev:06d}", "fecha_evento": f, "tipo_evento": "visita_urgencia",
                           "subtipo": "triage ESI 2" if grave else "descompensación", "severidad": "grave" if grave else "moderada",
                           "detalle": f"urgencia ({esp})", "diagnostico_cie10": rnd.choice(RELACIONADO[esp]), "diagnostico_texto": ""})
                if grave and rnd.random() < min(.9, s):
                    n_ev += 1
                    uci = s > .85 and rnd.random() < .4
                    fh = f + timedelta(days=rnd.randint(0, 1))
                    ev.append({"id_paciente": pid, "id_evento": f"EV-{n_ev:06d}", "fecha_evento": min(fh, CORTE),
                               "tipo_evento": "hospitalizacion", "subtipo": "ingreso UCI" if uci else "ingreso hospitalario",
                               "severidad": "grave", "detalle": f"hospitalización ({esp})",
                               "diagnostico_cie10": rnd.choice(RELACIONADO[esp]), "diagnostico_texto": ""})
                    notas.append({"id_paciente": pid, "fecha": min(fh + timedelta(days=rnd.randint(3, 9)), CORTE),
                                  "fuente": "epicrisis", "texto": _nota(rnd, par, esp, s, historial_s, epicrisis=True)})
            for tipo, sub_t, p in (("cambio_farmaco", "aumento dosis", .008 + .035 * s),
                                   ("examen_alterado", "resultado alterado", .008 + .035 * s)):
                if rnd.random() < p:
                    n_ev += 1
                    ev.append({"id_paciente": pid, "id_evento": f"EV-{n_ev:06d}", "fecha_evento": f, "tipo_evento": tipo,
                               "subtipo": sub_t, "severidad": "moderada", "detalle": f"{sub_t} ({esp})",
                               "diagnostico_cie10": "", "diagnostico_texto": ""})
            # distractor: urgencia que no tiene que ver con la derivación
            if rnd.random() < par.prob_distractor:
                n_ev += 1
                dcod, dtxt = rnd.choice(DISTRACTOR.get(esp, DISTRACTOR["_otro"]))
                g = rnd.random() < .35
                ev.append({"id_paciente": pid, "id_evento": f"EV-{n_ev:06d}", "fecha_evento": f, "tipo_evento": "visita_urgencia",
                           "subtipo": "triage ESI 2" if g else "triage ESI 3", "severidad": "grave" if g else "moderada",
                           "detalle": f"urgencia por {dtxt}", "diagnostico_cie10": dcod, "diagnostico_texto": dtxt})
                notas.append({"id_paciente": pid, "fecha": f, "fuente": "urgencia",
                              "texto": f"Consulta en urgencia por {dtxt}. Se trata y se da de alta. Sin relación con su "
                                       "patología de base."})
            # controles en APS con nota (aquí aparece lo que la regla no ve)
            if t == prox_control:
                n_ev += 1
                mejora = tray == "mejora" and len(historial_s) > 4 and s < historial_s[-5] - .03
                ev.append({"id_paciente": pid, "id_evento": f"EV-{n_ev:06d}", "fecha_evento": f, "tipo_evento": "control_aps",
                           "subtipo": "buena respuesta" if mejora else "control crónico", "severidad": "leve",
                           "detalle": f"control ({esp})", "diagnostico_cie10": "", "diagnostico_texto": ""})
                notas.append({"id_paciente": pid, "fecha": f, "fuente": "CESFAM", "texto": _nota(rnd, par, esp, s, historial_s)})
                prox_control = t + rnd.randint(5, 10)
            if t == prox_medicion:
                v = normal + delta * s + rnd.gauss(0, sd)
                v = round(v, 1) if unidad == "%" else round(v)
                if tipo_m in ("escala_dolor_eva",):
                    v = max(0, min(10, v))
                if tipo_m == "PHQ9":
                    v = max(0, min(27, v))
                me.append({"id_paciente": pid, "fecha_medicion": f, "tipo_medicion": tipo_m, "valor": v, "unidad": unidad,
                           "fuera_de_rango": str(bool(fuera(v))).lower()})
                prox_medicion = t + rnd.randint(3, 6)
            if s > .92 and rnd.random() < .01:
                fallece = f
                break
        deriva = pendiente if tray in ("progresivo", "mejora") else (-.004 if tray == "agudo" and crisis is not None else 0)
        r = riesgo_90d(s, deriva, ch) if fallece is None else None
        cat = None if r is None else "alta" if r >= UMBRAL_ALTA else "media" if r >= UMBRAL_MEDIA else "baja"
        pac.append({"id_paciente": pid, "nombre_fantasia": f"Sintético {i:03d}", "edad": edad, "sexo": rnd.choice("FM"),
                    "comuna": _elegir(rnd, COMUNAS), "prevision": _elegir(rnd, PREVISION),
                    "nivel_socioeconomico": rnd.choice(["bajo", "medio-bajo", "medio"]),
                    "fallecido": str(fallece is not None).lower(), "fecha_defuncion": fallece or ""})
        le.append({"id_paciente": pid, "id_solicitud": f"IC-{pid}", "especialidad": esp, "sub_especialidad": sub,
                   "diagnostico_cie10": cie, "diagnostico_texto": dx_txt, "prioridad_inicial": prio,
                   "fecha_ingreso_lista": ingreso, "origen_derivacion": _elegir(rnd, ORIGEN),
                   "estado": "fallecido" if fallece else "en_espera"})
        verdad.append({"id_paciente": pid, "especialidad": esp, "trayectoria": tray, "gravedad_inicial": round(s0, 3),
                       "gravedad_corte": round(s, 3), "charlson": ch, "riesgo_90d": None if r is None else round(r, 4),
                       "categoria_ideal": cat, "prioridad_inicial": prio,
                       "empeoro": cat is not None and {"baja": 0, "media": 1, "alta": 2}[cat] > {"baja": 0, "media": 1, "alta": 2}[prio]})
        for c in cron:
            notas.append({"id_paciente": pid, "fecha": ingreso - timedelta(days=rnd.randint(30, 600)), "fuente": "APS crónicos",
                          "texto": f"Diagnóstico crónico registrado en APS: {c}."})
    carpeta, carpeta_v = salida / nombre, salida / f"{nombre}_verdad"
    carpeta.mkdir(parents=True, exist_ok=True)
    carpeta_v.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(pac).to_csv(carpeta / "pacientes.csv", index=False)
    pd.DataFrame(le).to_csv(carpeta / "lista_espera.csv", index=False)
    pd.DataFrame(ev).to_csv(carpeta / "eventos_clinicos.csv", index=False)
    pd.DataFrame(me).to_csv(carpeta / "mediciones.csv", index=False)
    pd.DataFrame(columns=["id_paciente", "id_cita", "id_box", "fecha_cita", "especialidad", "estado_cita",
                          "minutos_atencion_real"]).to_csv(carpeta / "citaciones.csv", index=False)
    pd.DataFrame(notas).sort_values(["id_paciente", "fecha"]).to_csv(carpeta / "notas_clinicas.csv", index=False)
    v = pd.DataFrame(verdad)
    v.to_csv(carpeta_v / "verdad.csv", index=False)
    return {"conjunto": nombre, "pacientes": len(pac), "eventos": len(ev), "notas": len(notas),
            "fallecidos": int(v.riesgo_90d.isna().sum()),
            "categorias_ideales": v.categoria_ideal.value_counts().to_dict(),
            "empeoraron_vs_T1": int(v.empeoro.sum())}


def _nivel(s: float) -> str:
    return "alto" if s >= .58 else "medio" if s >= .33 else "bajo"


def _nota(rnd, par, esp, s, historial, epicrisis=False) -> str:
    nivel = _nivel(s)
    if rnd.random() < par.ruido_notas:   # nota vaga o engañosa: describe un nivel vecino
        orden = ["bajo", "medio", "alto"]
        nivel = orden[max(0, min(2, orden.index(nivel) + rnd.choice([-1, 1])))]
    previo = historial[-6] if len(historial) > 5 else historial[0]
    tend = "empeora" if s > previo + .06 else "mejora" if s < previo - .06 else "estable"
    partes = [("Epicrisis: " if epicrisis else "Control en CESFAM: ") + _frase(rnd, par, SINTOMAS[esp][nivel]) + ".",
              _frase(rnd, par, TENDENCIA[tend]).capitalize() + "."]
    if nivel == "alto" and tend == "empeora" and rnd.random() < par.prob_explicita:
        partes.append(_frase(rnd, par, EXPLICITA))
    return " ".join(partes)


def main():
    for nombre, par in CONJUNTOS.items():
        print(generar(nombre, par))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(RAIZ))
    main()
