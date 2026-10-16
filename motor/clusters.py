"""Clusters de información del paciente y el índice LACE (riesgo publicado, sin pesos propios).

El hospital pidió (entrevista 5) no priorizar por un signo vital suelto sino por "grandes clusters":
hospitalización (días, tipo de cama, UCI, cirugía), urgencias, diagnósticos de mayor gravedad, consultas
y la estratificación de riesgo de APS (ACG: G1, G2, G3). Este módulo arma esos clusters con lo que se sabe
a una fecha de corte y calcula el índice LACE, que resume varios de ellos con puntos ya publicados.

LACE (van Walraven et al., CMAJ 2010;182(6):551-7) predice muerte o reingreso no planificado a 30 días
del alta. Sus puntos están fijados por los autores; no los calibramos:
    L  días de estada del ingreso: <1 = 0, 1 = 1, 2 = 2, 3 = 3, 4-6 = 4, 7-13 = 5, >=14 = 7
    A  ingreso urgente = 3 (electivo = 0)
    C  índice de Charlson: 0-3 = mismo valor, >=4 = 5
    E  consultas de urgencia en los 6 meses previos: 1 por consulta, máximo 4
    Total 0-19. 10 o más = riesgo alto (punto de corte de los autores).

Charlson (Charlson et al., J Chronic Dis 1987) con códigos CIE-10 según Quan et al. (Med Care 2005),
simplificado a los primeros caracteres del código.

Nivel de cuidado: UCI > hospitalización en sala > urgencia sin hospitalización. Los sobrevivientes de UCI
tienen más mortalidad y más uso de hospital que otros hospitalizados comparables (Lone et al., AJRCCM 2016:
HR 1,33 de mortalidad a 5 años). Es un orden que viene del propio registro, no un peso.
"""
from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache

# --------------------------------------------------------------------------- Charlson (Quan 2005, simplificado)
# (nombre, peso, prefijos CIE-10). Si un código calza con un grupo "más grave" del mismo órgano, manda ese.
CHARLSON = [
    ("Infarto agudo al miocardio", 1, ("I21", "I22", "I252")),
    ("Insuficiencia cardíaca", 1, ("I50", "I110", "I130", "I132", "I42", "I43", "I255")),
    ("Enfermedad vascular periférica", 1, ("I70", "I71", "I731", "I738", "I739", "I771", "K551")),
    ("Enfermedad cerebrovascular", 1, ("G45", "G46", "I60", "I61", "I62", "I63", "I64", "I65", "I66", "I67",
                                       "I68", "I69")),
    ("Demencia", 1, ("F00", "F01", "F02", "F03", "F051", "G30", "G311")),
    ("Enfermedad pulmonar crónica", 1, ("J40", "J41", "J42", "J43", "J44", "J45", "J46", "J47", "J60", "J61",
                                        "J62", "J63", "J64", "J65", "J66", "J67", "I278", "I279")),
    ("Enfermedad reumatológica", 1, ("M05", "M06", "M315", "M32", "M33", "M34", "M351", "M353", "M360")),
    ("Úlcera péptica", 1, ("K25", "K26", "K27", "K28")),
    ("Daño hepático leve", 1, ("B18", "K70", "K700", "K701", "K702", "K703", "K709", "K713", "K714", "K715", "K717",
                               "K73", "K74", "K760", "K762", "K763", "K764", "K768", "K769")),
    ("Diabetes sin daño de órgano", 1, ("E100", "E101", "E106", "E108", "E109", "E110", "E111", "E116", "E118",
                                        "E119", "E10", "E11", "E13", "E14")),
    ("Diabetes con daño de órgano", 2, ("E102", "E103", "E104", "E105", "E107", "E112", "E113", "E114", "E115",
                                        "E117")),
    ("Hemiplejia o paraplejia", 2, ("G81", "G82", "G041", "G114", "G801", "G802", "G830", "G831", "G832",
                                    "G833", "G834", "G839")),
    ("Enfermedad renal moderada o grave", 2, ("N18", "N19", "N052", "N053", "N054", "N055", "N056", "N057",
                                              "N250", "I120", "I131", "Z49", "Z940", "Z992")),
    ("Cáncer (incluye leucemia y linfoma)", 2, tuple(f"C{i:02d}" for i in list(range(0, 27)) + list(range(30, 35))
                                                     + list(range(37, 42)) + [43] + list(range(45, 59))
                                                     + list(range(60, 77)) + list(range(81, 86)) + [88]
                                                     + list(range(90, 98)))),
    ("Daño hepático moderado o grave", 3, ("I850", "I859", "I864", "I982", "K704", "K711", "K721", "K729", "K765",
                                           "K766", "K767")),
    ("Cáncer con metástasis", 6, ("C77", "C78", "C79", "C80")),
    ("VIH/SIDA", 6, ("B20", "B21", "B22", "B24")),
]
# Si están ambos, cuenta solo el más grave
JERARQUIA = {"Diabetes sin daño de órgano": "Diabetes con daño de órgano",
             "Daño hepático leve": "Daño hepático moderado o grave",
             "Cáncer (incluye leucemia y linfoma)": "Cáncer con metástasis"}


def _limpiar(codigo: str) -> str:
    return str(codigo or "").upper().replace(".", "").replace(" ", "").strip()


@lru_cache(maxsize=4096)
def _condicion(c: str) -> tuple[str, int] | None:
    """Condición de Charlson de un código (el prefijo más largo que calza es el más específico: E112 gana a E11)."""
    mejor = None
    for nombre, peso, prefijos in CHARLSON:
        largo = max((len(p) for p in prefijos if c.startswith(p)), default=0)
        if largo and (mejor is None or largo > mejor[2] or (largo == mejor[2] and peso > mejor[1])):
            mejor = (nombre, peso, largo)
    return (mejor[0], mejor[1]) if mejor else None


def charlson(codigos) -> tuple[int, list[str]]:
    """Índice de Charlson y la lista de condiciones encontradas, a partir de códigos CIE-10."""
    encontrados: dict[str, int] = {}
    for c in codigos or []:
        c = _limpiar(c)
        cond = _condicion(c) if c else None
        if cond:
            encontrados[cond[0]] = cond[1]
    for leve, grave in JERARQUIA.items():
        if leve in encontrados and grave in encontrados:
            del encontrados[leve]
    return sum(encontrados.values()), sorted(encontrados)


# --------------------------------------------------------------------------- LACE
def puntos_L(dias: float | None) -> int:
    if dias is None:
        return 0
    d = float(dias)
    return 0 if d < 1 else 1 if d < 2 else 2 if d < 3 else 3 if d < 4 else 4 if d < 7 else 5 if d < 14 else 7


def puntos_C(indice_charlson: int) -> int:
    return indice_charlson if indice_charlson <= 3 else 5


def _hay(x) -> bool:
    return x is not None and not (isinstance(x, float) and x != x) and x != ""


NIVEL_CUIDADO = {0: "UCI", 1: "hospitalización", 2: "urgencia", 3: "sin evento grave"}


def nivel_cuidado(e: dict) -> int:
    """0 = UCI, 1 = hospitalización en sala, 2 = urgencia sin hospitalizar, 3 = otro."""
    if e.get("tipo_evento") == "hospitalizacion":
        cama = str(e.get("tipo_cama") or "").upper()
        if e.get("subtipo") == "ingreso UCI" or cama in ("UCI", "UPC") or (_hay(e.get("dias_uci")) and float(e["dias_uci"]) > 0):
            return 0
        return 1
    if e.get("tipo_evento") == "visita_urgencia":
        return 2
    return 3


def clusters(p, corte: date, cfg: dict) -> dict:
    """Clusters del paciente con información hasta `corte` (sin mirar el futuro).

    Devuelve un dict con un resumen por cluster, el índice LACE del episodio grave más reciente y el nivel de
    cuidado más alto en la ventana del carril rápido.
    """
    cc = cfg.get("clusters", {})
    v_hosp = cc.get("ventana_hospitalizaciones_dias", 365)
    v_urg = cc.get("ventana_urgencias_dias", 182)
    v_carril = cfg["carril_rapido"]["ventana_dias"]

    from .pertinencia import es_pertinente
    hosp, urg, otros, no_rel = [], [], [], []
    for e in p.eventos:
        if e["fecha"] > corte:
            break
        dd = (corte - e["fecha"]).days
        if not es_pertinente(p, e, cfg):
            if e["severidad"] != "leve" and dd <= v_urg:
                no_rel.append(e)
            continue
        if e["tipo_evento"] == "hospitalizacion" and dd <= v_hosp:
            hosp.append(e)
        elif e["tipo_evento"] == "visita_urgencia" and dd <= v_urg:
            urg.append(e)
        elif e["tipo_evento"] in ("examen_alterado", "cambio_farmaco") and dd <= 180 and e["severidad"] != "leve":
            otros.append(e)

    # --- Hospitalización
    dias_total = sum(float(e["dias_estadia"]) for e in hosp if _hay(e.get("dias_estadia")))
    sin_dias = sum(1 for e in hosp if not _hay(e.get("dias_estadia")))
    uci = [e for e in hosp if nivel_cuidado(e) == 0]
    cirugias = [e for e in hosp if str(e.get("cirugia", "")).lower() in ("true", "1", "si", "sí")]

    # --- Comorbilidad (diagnóstico de la interconsulta + crónicos de APS + egresos)
    codigos = [p.diagnostico.split(" ")[0]]
    codigos += [c["cie10"] for c in (getattr(p, "comorbilidades", None) or []) if not c.get("fecha") or c["fecha"] <= corte]
    codigos += [e.get("diagnostico_cie10") for e in hosp + urg if _hay(e.get("diagnostico_cie10"))]
    ch, condiciones = charlson(codigos)

    # --- Episodio grave más reciente en la ventana del carril (para ordenar dentro del carril)
    graves = [e for e in p.eventos if e["fecha"] <= corte and e["severidad"] == "grave"
              and (corte - e["fecha"]).days <= v_carril and es_pertinente(p, e, cfg)]
    # Recurrencia: episodios graves relacionados en 12 meses (eventos a menos de N días son el mismo episodio)
    fechas_g = sorted(e["fecha"] for e in p.eventos if e["fecha"] <= corte and e["severidad"] == "grave"
                      and (corte - e["fecha"]).days <= 365 and es_pertinente(p, e, cfg))
    gap = cfg["carril_rapido"].get("dias_mismo_episodio", 7)
    recurrencia = sum(1 for i, f in enumerate(fechas_g) if i == 0 or (f - fechas_g[i - 1]).days > gap)
    nivel = min((nivel_cuidado(e) for e in graves), default=3)
    indice = hosp_indice = None
    if graves:
        # el episodio índice: la hospitalización más reciente de la ventana o, si no hubo, la urgencia más reciente
        hosp_v = [e for e in graves if e["tipo_evento"] == "hospitalizacion"]
        hosp_indice = hosp_v[-1] if hosp_v else None
        ref = hosp_indice or graves[-1]
        inicio_e = ref["fecha"] - timedelta(days=182)
        n_urg_previas = sum(1 for e in p.eventos if e["tipo_evento"] == "visita_urgencia"
                            and inicio_e <= e["fecha"] < ref["fecha"])
        L = puntos_L(ref.get("dias_estadia")) if hosp_indice else 0
        ingreso = str(ref.get("tipo_ingreso") or "urgente").lower()
        A = 3 if (hosp_indice and ingreso != "electivo") else 0
        C = puntos_C(ch)
        E = min(n_urg_previas, 4)
        indice = {"L": L, "A": A, "C": C, "E": E, "total": L + A + C + E,
                  "parcial": bool(hosp_indice) and not _hay(ref.get("dias_estadia")),
                  "episodio": ref.get("subtipo"), "fecha": ref["fecha"]}

    return {
        "hospitalizacion": {"n": len(hosp), "dias_cama": int(dias_total), "sin_dias": sin_dias,
                            "uci": len(uci), "dias_uci": int(sum(float(e.get("dias_uci") or 0) for e in uci
                                                                 if _hay(e.get("dias_uci")))),
                            "cirugias": len(cirugias),
                            "ultima": hosp[-1]["fecha"] if hosp else None},
        "urgencias": {"n": len(urg), "graves": sum(1 for e in urg if e["severidad"] == "grave"),
                      "ultima": urg[-1]["fecha"] if urg else None},
        "comorbilidad": {"charlson": ch, "condiciones": condiciones},
        "riesgo_aps": {"acg": next((a["estrato"] for a in reversed(getattr(p, "acg", None) or [])
                                    if not a.get("fecha") or a["fecha"] <= corte), None)},
        "evolucion": {"examenes_alterados": sum(1 for e in otros if e["tipo_evento"] == "examen_alterado"),
                      "aumentos_dosis": sum(1 for e in otros if e["tipo_evento"] == "cambio_farmaco")},
        "nivel_cuidado": nivel,
        "recurrencia": recurrencia,
        "no_relacionados": [f"urgencia o evento por {e.get('diagnostico_texto') or e.get('diagnostico_cie10')} "
                            f"({e['fecha'].strftime('%d-%m')})" for e in no_rel],
        "lace": indice,
    }


def texto_clusters(c: dict) -> list[str]:
    """Frases cortas para la ficha del paciente (una por cluster con datos)."""
    out = []
    h = c["hospitalizacion"]
    if h["n"]:
        partes = [f"{h['n']} {'ingreso' if h['n'] == 1 else 'ingresos'} en 12 meses"]
        if h["dias_cama"]:
            partes.append(f"{h['dias_cama']} días cama")
        if h["uci"]:
            partes.append(f"{h['uci']} en UCI" + (f" ({h['dias_uci']} días)" if h["dias_uci"] else ""))
        if h["cirugias"]:
            partes.append(f"{h['cirugias']} con cirugía")
        out.append("Hospitalización: " + ", ".join(partes))
    u = c["urgencias"]
    if u["n"]:
        out.append(f"Urgencias: {u['n']} {'consulta' if u['n'] == 1 else 'consultas'} en 6 meses"
                   + (f" ({u['graves']} {'grave' if u['graves'] == 1 else 'graves'})" if u["graves"] else ""))
    cm = c["comorbilidad"]
    if cm["charlson"]:
        out.append(f"Comorbilidad: Charlson {cm['charlson']} ({', '.join(cm['condiciones'])})")
    if c["riesgo_aps"]["acg"]:
        out.append(f"Riesgo en APS (ACG/ECICEP): {c['riesgo_aps']['acg']}")
    ev = c["evolucion"]
    if ev["examenes_alterados"] or ev["aumentos_dosis"]:
        out.append(f"Evolución ambulatoria (6 meses): {ev['examenes_alterados']} exámenes alterados, "
                   f"{ev['aumentos_dosis']} aumentos de dosis")
    if c.get("recurrencia", 0) > 1:
        out.append(f"Recurrencia: {c['recurrencia']} episodios graves relacionados en 12 meses")
    if c.get("no_relacionados"):
        out.append("No relacionado con la derivación (no mueve la lista): " + "; ".join(c["no_relacionados"]))
    if c["lace"]:
        x = c["lace"]
        out.append(f"Índice LACE {x['total']} (L{x['L']} + A{x['A']} + C{x['C']} + E{x['E']})"
                   + (": riesgo alto de muerte o reingreso a 30 días" if x["total"] >= 10 else "")
                   + (" · sin días de estada en el reporte" if x["parcial"] else ""))
    return out
