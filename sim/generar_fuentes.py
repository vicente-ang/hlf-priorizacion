"""Genera reportes SINTÉTICOS de las otras fuentes del hospital para los 500 pacientes del desafío.

El hospital pidió (entrevista 5): "invéntate unos pacientes que me muestren cómo te lo va a ir reordenando".
El dataset trae solo una muestra de Tálamo; aquí se fabrican, con semilla fija, los reportes que llegarían de
las otras fuentes, con columnas parecidas a las que describieron:

  talamo_hospitalizaciones.csv     días de estada, tipo de cama (sala / UCI), días en UCI, cirugía, tipo de ingreso
  talamo_urgencias.csv             categoría ESI, horas en urgencia, destino (más algunas consultas ESI 4-5 nuevas)
  acg_estratificacion.csv          estrato de riesgo ECICEP (G0..G3), marzo y septiembre de 2026
  rayen_diagnosticos_cronicos.csv  diagnósticos crónicos registrados en APS
  interconsultas.csv               14 interconsultas nuevas SIN priorizar, con el texto de quien derivó

Todo es inventado: sirve para mostrar el mecanismo, no para sacar conclusiones clínicas.
Uso:  python sim/generar_fuentes.py      (escribe data/fuentes_sinteticas/)
"""
from __future__ import annotations

import random
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parents[1]
DATASET = RAIZ / "data" / "dataset_hlf_ambulatorio"
SALIDA = RAIZ / "data" / "fuentes_sinteticas"
SEMILLA = 20261015

DX_EGRESO = {  # diagnóstico de egreso posible por especialidad (CIE-10)
    "Cardiología": ["I50.0", "I21.4", "I20.0", "I48.9"],
    "Broncopulmonar": ["J44.1", "J18.9", "J45.9"],
    "Endocrinología": ["E11.5", "E11.6", "E87.1"],
    "Gastroenterología": ["K92.2", "K70.4", "K85.9"],
    "Neurología": ["G40.9", "I63.9", "G43.9"],
    "Salud Mental": ["F32.2", "F41.1", "X84"],
    "Traumatología": ["S72.0", "M17.1", "S32.0"],
}
P_CIRUGIA = {"Traumatología": 0.5, "Gastroenterología": 0.3, "Cardiología": 0.2}
CRONICOS = [  # (cie10, prob base, sube con la edad)
    ("I10", 0.30, True), ("E11", 0.15, True), ("E11.2", 0.04, True), ("J44", 0.06, True), ("I50", 0.05, True),
    ("N18", 0.05, True), ("E66", 0.15, False), ("I63", 0.03, True), ("K70", 0.02, False), ("C50", 0.01, True),
]
INTERCONSULTAS = [  # (especialidad, sub, cie10, texto diagnóstico, texto de la interconsulta, días desde que se creó)
    ("Traumatología", "Columna", "M54", "Dorsalgia",
     "Lumbago de 3 meses, ahora con pérdida de fuerza en pierna derecha y parestesias. Sin fiebre.", 34),
    ("Traumatología", "Rodilla", "M17", "Gonartrosis",
     "Gonalgia leve bilateral, responde a analgesia. Solicito evaluación por especialista.", 40),
    ("Cardiología", "Cardiología adulto", "I20", "Angina de pecho",
     "Dolor torácico opresivo de esfuerzo, ahora angina de reposo en la última semana. ECG sin cambios agudos.", 27),
    ("Cardiología", "Cardiología adulto", "I10", "Hipertensión esencial",
     "HTA controlada con dos fármacos, se deriva para estudio de soplo funcional.", 45),
    ("Salud Mental", "Psiquiatría adulto", "F32", "Episodio depresivo",
     "Episodio depresivo moderado, refiere ideación suicida sin plan estructurado. Vive solo.", 23),
    ("Salud Mental", "Psicología", "F41", "Trastorno de ansiedad",
     "Ansiedad generalizada, niega ideación suicida, buena red de apoyo.", 52),
    ("Neurología", "Neurología adulto", "G40", "Epilepsia",
     "Epilepsia con crisis a repetición pese a ajuste de dosis, 3 crisis este mes.", 30),
    ("Neurología", "Neurología adulto", "G43", "Migraña",
     "Cefalea de larga data, consulta por evaluación.", 38),
    ("Broncopulmonar", "Broncopulmonar adulto", "J44", "EPOC",
     "EPOC con exacerbaciones frecuentes, 2 hospitalizaciones por exacerbación este año.", 29),
    ("Broncopulmonar", "Broncopulmonar adulto", "J45", "Asma",
     "Asma controlada, se deriva para espirometría y ajuste de tratamiento.", 15),
    ("Endocrinología", "Diabetes", "E11", "Diabetes mellitus tipo 2",
     "DM2 de difícil manejo, HbA1c mayor a 10 y lesión en pie diabético en curación en CESFAM.", 26),
    ("Endocrinología", "Tiroides", "E03", "Hipotiroidismo",
     "Hipotiroidismo compensado, derivo por solicitud del paciente.", 60),
    ("Gastroenterología", "Gastroenterología adulto", "K21", "Reflujo gastroesofágico",
     "Pirosis y disfagia progresiva a sólidos, baja de peso no explicada de 6 kilos.", 24),
    ("Gastroenterología", "Gastroenterología adulto", "K21", "Reflujo gastroesofágico",
     "Molestias digestivas, se solicita evaluación.", 10),
]


def main(hoy: date = date(2026, 10, 13)) -> None:
    rnd = random.Random(SEMILLA)
    SALIDA.mkdir(parents=True, exist_ok=True)
    pa = pd.read_csv(DATASET / "pacientes.csv").set_index("id_paciente")
    le = pd.read_csv(DATASET / "lista_espera.csv").set_index("id_paciente")
    ev = pd.read_csv(DATASET / "eventos_clinicos.csv")
    ev["fecha"] = pd.to_datetime(ev.fecha_evento).dt.date

    # --- Tálamo hospitalizado: completa cada hospitalización del dataset
    filas = []
    for r in ev[ev.tipo_evento == "hospitalizacion"].itertuples():
        esp = le.loc[r.id_paciente, "especialidad"]
        uci = r.subtipo == "ingreso UCI"
        dias = rnd.randint(4, 16) if uci else min(1 + int(rnd.expovariate(1 / 4)), 21)
        dias_uci = min(rnd.randint(2, 7), dias - 1) if uci else 0
        filas.append({"id_paciente": r.id_paciente, "fecha_ingreso": r.fecha, "fecha_egreso": r.fecha + timedelta(days=dias),
                      "dias_estada": dias, "tipo_cama": "UCI" if uci else rnd.choice(["SALA", "SALA", "MEDIO"]),
                      "dias_uci": dias_uci, "cirugia": "si" if rnd.random() < P_CIRUGIA.get(esp, 0.1) else "no",
                      "tipo_ingreso": "electivo" if rnd.random() < 0.08 else "urgente",
                      "diagnostico_egreso_cie10": rnd.choice(DX_EGRESO[esp]), "servicio": esp})
    pd.DataFrame(filas).to_csv(SALIDA / "talamo_hospitalizaciones.csv", index=False)

    # --- Tálamo urgencia: completa cada urgencia y agrega consultas de baja complejidad (ESI 4-5)
    hosp = {(r.id_paciente, r.fecha) for r in ev[ev.tipo_evento == "hospitalizacion"].itertuples()}
    filas = []
    for r in ev[ev.tipo_evento == "visita_urgencia"].itertuples():
        esp = le.loc[r.id_paciente, "especialidad"]
        esi = 2 if r.severidad == "grave" else 3
        hospitalizado = any((r.id_paciente, r.fecha + timedelta(days=k)) in hosp for k in range(0, 3))
        filas.append({"id_paciente": r.id_paciente, "fecha_atencion": r.fecha, "categoria_esi": esi,
                      "horas_estadia": round(rnd.uniform(4, 30 if esi == 2 else 12), 1),
                      "destino": "hospitalización" if hospitalizado else "alta a domicilio",
                      "diagnostico_cie10": rnd.choice(DX_EGRESO[esp])})
    con_lista = [pid for pid in le.index if le.loc[pid, "estado"] == "en_espera"]
    for pid in rnd.sample(con_lista, 30):
        ini = pd.Timestamp(le.loc[pid, "fecha_ingreso_lista"]).date()
        if (hoy - ini).days < 10:
            continue
        f = ini + timedelta(days=rnd.randint(5, (hoy - ini).days))
        filas.append({"id_paciente": pid, "fecha_atencion": f, "categoria_esi": rnd.choice([4, 4, 5]),
                      "horas_estadia": round(rnd.uniform(1.5, 5), 1), "destino": "alta a domicilio",
                      "diagnostico_cie10": le.loc[pid, "diagnostico_cie10"]})
    # Urgencias NO relacionadas con la derivación (reunión 7: "dos urgencias por esguince en alguien derivado por
    # hipoacusia no impactan"): se muestran, pero no deben mover la lista.
    no_rel = {"Traumatología": [("N20.0", "cólico renal"), ("J18.9", "neumonía")]}
    rnd2 = random.Random(SEMILLA + 7)          # generador aparte: no cambia el resto de las fuentes
    for esp in sorted(le.especialidad.unique()):
        pids = sorted(pid for pid in con_lista if le.loc[pid, "especialidad"] == esp)
        for k, pid in enumerate(rnd2.sample(pids, 3)):
            dx, dx_txt = (no_rel.get(esp) or [("S93.4", "esguince de tobillo"), ("S52.5", "fractura de radio")])[k % 2]
            filas.append({"id_paciente": pid, "fecha_atencion": hoy - timedelta(days=rnd2.randint(4, 25) if k == 0 else
                                                                                   rnd2.randint(30, 150)),
                          "categoria_esi": 2 if k == 0 else 3, "horas_estadia": round(rnd2.uniform(3, 10), 1),
                          "destino": "alta a domicilio", "diagnostico_cie10": dx, "diagnostico_texto": dx_txt})
    pd.DataFrame(filas).sort_values(["fecha_atencion", "id_paciente"]).to_csv(SALIDA / "talamo_urgencias.csv", index=False)

    # --- Rayen: diagnósticos crónicos en APS
    filas = []
    for pid, p in pa.iterrows():
        factor = 1.6 if p.edad >= 65 else 1.0 if p.edad >= 45 else 0.5
        for cie, prob, edad in CRONICOS:
            if rnd.random() < prob * (factor if edad else 1):
                filas.append({"id_paciente": pid, "diagnostico_cie10": cie,
                              "fecha_registro": date(2024, 1, 1) + timedelta(days=rnd.randint(0, 900))})
    cronicos = pd.DataFrame(filas)
    cronicos.to_csv(SALIDA / "rayen_diagnosticos_cronicos.csv", index=False)

    # --- ECICEP / ACG: estrato según edad, crónicos y eventos graves (aproximación para la demo)
    n_cron = cronicos.groupby("id_paciente").size()
    n_grav = ev[ev.severidad == "grave"].groupby("id_paciente").size()
    filas = []
    for pid, p in pa.iterrows():
        carga = n_cron.get(pid, 0) + (1 if p.edad >= 65 else 0) + 0.5 * n_grav.get(pid, 0) + rnd.uniform(-0.6, 0.6)
        estrato = "G3" if carga >= 3 else "G2" if carga >= 1.8 else "G1" if carga >= 0.6 else "G0"
        filas.append({"id_paciente": pid, "fecha_estratificacion": date(2026, 3, 31), "estrato": estrato})
        if n_grav.get(pid, 0) and estrato != "G3" and rnd.random() < 0.5:
            filas.append({"id_paciente": pid, "fecha_estratificacion": date(2026, 9, 30),
                          "estrato": {"G0": "G1", "G1": "G2", "G2": "G3"}[estrato]})
    pd.DataFrame(filas).to_csv(SALIDA / "acg_estratificacion.csv", index=False)

    # --- Interconsultas nuevas sin priorizar (con su texto)
    filas = []
    comunas = ["La Florida", "Puente Alto", "La Pintana", "La Granja", "San Ramón", "Pirque", "San José de Maipo"]
    for i, (esp, sub, cie, dx, texto, dias) in enumerate(INTERCONSULTAS, start=501):
        filas.append({"id_paciente": f"PAC-HLF-{i:05d}", "id_solicitud": f"IC-HLF-{i:05d}", "especialidad": esp,
                      "sub_especialidad": sub, "diagnostico_cie10": cie, "diagnostico_texto": dx,
                      "prioridad_inicial": "", "fecha_ingreso_lista": hoy - timedelta(days=dias),
                      "origen_derivacion": "CESFAM/APS", "estado": "en_espera", "texto_interconsulta": texto,
                      "edad": rnd.randint(25, 82), "sexo": rnd.choice("FM"), "comuna": rnd.choice(comunas),
                      "prevision": rnd.choice(["FONASA A", "FONASA B", "FONASA C"]),
                      "nivel_socioeconomico": rnd.choice(["bajo", "medio-bajo", "medio"])})
    pd.DataFrame(filas).to_csv(SALIDA / "interconsultas.csv", index=False)

    (SALIDA / "LEEME.md").write_text(
        "# Fuentes sintéticas\n\nReportes INVENTADOS con semilla fija (`python sim/generar_fuentes.py`) para mostrar "
        "cómo se unen las fuentes del hospital (Tálamo hospitalizado y urgencia, Rayen (APS), ECICEP/ACG e "
        "interconsultas). No son datos del hospital. Con datos reales, cada reporte se deja en la carpeta "
        "`fuentes/` junto a los datos (o en `HLF_FUENTES`) con las columnas de `motor/fuentes.py`.\n",
        encoding="utf-8")
    print(f"Fuentes sintéticas en {SALIDA}")


if __name__ == "__main__":
    sys.exit(main())
