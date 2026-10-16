# Dataset – Atención Ambulatoria Dinámica HLF

Reto: Priorización Clínica Evolutiva y Uso del Recurso Box.
Datos 100% sintéticos. Semilla 20261013. Fecha de referencia 2026-10-13. 500 pacientes.

## Idea del reto
La prioridad de la lista de espera debe MOVERSE según cómo evoluciona el paciente mientras espera.
El dataset es una SERIE TEMPORAL de eventos: cada equipo diseña su propio algoritmo de priorización
dinámica y de uso de box. NO hay respuesta de referencia.

## Archivos (se unen por id_paciente; agenda_box es del hospital)
| Archivo | Filas | Grano |
|---|---|---|
| pacientes.csv | 500 | un paciente (tabla maestra) |
| lista_espera.csv | 500 | una solicitud en espera |
| eventos_clinicos.csv | 786 | un evento con fecha |
| mediciones.csv | 2487 | una medición con fecha |
| agenda_box.csv | 2188 | un bloque de agenda de un box |
| citaciones.csv | 257 | una cita ofrecida |
| perfiles.json | 500 | un objeto por paciente con sus series anidadas |

## Notas
- id_paciente ficticio (PAC-HLF-#####); sin RUT ni nombres reales.
- Comunas de la Red Sur Oriente (contexto Hospital La Florida); pacientes sintéticos.
- Diagnósticos con CIE-10 reales asignados sintéticamente.
- Para recalcular prioridad a una fecha de corte: usar solo eventos/mediciones con fecha <= corte.
- Control de exclusión: pacientes fallecidos deben salir de la lista (fallecido=true, fecha_defuncion).
