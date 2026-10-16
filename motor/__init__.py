"""Motor de priorización dinámica HLF.

Regla por defecto (MVP, sin pesos): motor.priorizacion  -> carril rápido + plazo dinámico
Modo opcional con pesos a mano:      motor.puntaje       -> puntaje v1
"""
from .puntaje import Datos, cargar_config, puntuar_paciente, puntuar_lista, puesto_regla_actual
from .priorizacion import MODOS, cargar_regla, clave_orden, evaluar_paciente, ordenar, priorizar
from .auditoria import auditar
