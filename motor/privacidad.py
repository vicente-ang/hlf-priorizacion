"""Minimización de datos antes de enviar texto a la IA generativa.

Lo único que sale con texto libre hacia Bedrock son las indicaciones de control escritas por el médico.
Ahí puede aparecer un RUT, un teléfono o un correo. Se reemplazan antes de enviar; el resto de lo que va
a Bedrock (explicaciones, resumen del día) ya usa solo el identificador seudonimizado y hechos clínicos
codificados.

Los nombres propios no se detectan de forma confiable con reglas: en producción, conviene sumar Amazon
Comprehend Medical (detección de datos de salud protegidos) o pedir que el reporte no traiga nombres.
"""
import re

PATRONES = [
    (re.compile(r"\b\d{1,2}\.?\d{3}\.?\d{3}\s*-\s*[\dkK]\b"), "[RUT]"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[CORREO]"),
    (re.compile(r"(?:\+?56\s?)?(?:9\s?\d{4}\s?\d{4}|2\s?\d{4}\s?\d{4})\b"), "[TELÉFONO]"),
]


def anonimizar_texto(texto: str) -> str:
    for patron, reemplazo in PATRONES:
        texto = patron.sub(reemplazo, texto)
    return texto


def seudonimo(rut, sal: str | None = None) -> str:
    """Identificador estable para unir fuentes sin guardar el RUT: el mismo RUT da el mismo id en todos los
    reportes (Tálamo, Rayen, ACG...). La sal se define en HLF_SAL y no se publica."""
    import hashlib
    import os
    limpio = re.sub(r"[^0-9kK]", "", str(rut)).upper()
    sal = sal if sal is not None else os.environ.get("HLF_SAL", "")
    return "PAC-" + hashlib.sha256((sal + limpio).encode()).hexdigest()[:10].upper()
