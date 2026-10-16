# Formato de entrada: lo que cualquier ficha clínica tiene que exportar

La herramienta no se conecta a una ficha en particular. Lee **reportes en tablas** (CSV o Excel guardado como
CSV) que cualquier registro clínico puede exportar: Tálamo en el HLF, otro proveedor en otro hospital, Rayen u
otro sistema en APS. Así escala a cualquier servicio de salud del país sin depender del BIAU, que solo existe en
el Servicio Metropolitano Sur Oriente y se consulta persona a persona (reunión 7).

Cada reporte se deja en una carpeta por día (`reportes/AAAA-MM-DD/` en S3, o una carpeta local) y se carga con
`python ingesta.py --reporte <carpeta> --fecha <día>` o con la Lambda diaria. Las filas que ya estaban no se
duplican. `python validar_datos.py <carpeta>` revisa columnas, fechas y categorías antes de usarlos.

**Llave**: `id_paciente`, el RUT seudonimizado. Si el reporte trae `rut`, la herramienta lo reemplaza por un
seudónimo con una sal secreta (`HLF_SAL`), igual en todas las fuentes, y no lo guarda.
**Fechas**: AAAA-MM-DD. **Diagnósticos**: CIE-10 (con o sin punto).

## Mínimo para funcionar (hoy lo saca la reportería del hospital)

| Archivo | Una fila por | Columnas obligatorias | De dónde sale en el HLF |
|---|---|---|---|
| `lista_espera.csv` | interconsulta en espera | `id_paciente`, `especialidad`, `diagnostico_cie10`, `prioridad_inicial` (alta/media/baja o vacía si no se priorizó), `fecha_ingreso_lista`, `estado` | Reporte de interconsultas (SIC) |
| `pacientes.csv` | persona | `id_paciente`, `edad`, `sexo`, `comuna`, `fallecido`, `fecha_defuncion` | Ficha |
| `eventos_clinicos.csv` | evento | `id_paciente`, `fecha_evento`, `tipo_evento` (hospitalizacion, visita_urgencia, examen_alterado, cambio_farmaco, control_aps), `subtipo`, `severidad` (leve, moderada, grave); opcional `diagnostico_cie10` | Tálamo y APS |
| `citaciones.csv` | cita | `id_paciente`, `fecha_cita`, `estado_cita` (agendada, asistio, no_asistio, reprogramo, cancelo); opcional `fecha_agendamiento` | Agenda |

## Mejora la priorización (opcional)

| Archivo | Columnas | Para qué |
|---|---|---|
| `fuentes/talamo_hospitalizaciones.csv` | `id_paciente`, `fecha_ingreso`, `dias_estada`, `tipo_cama` (SALA, MEDIO, UCI), `dias_uci`, `cirugia` (si/no), `tipo_ingreso` (urgente/electivo), `diagnostico_egreso_cie10` | Cluster de hospitalización, nivel de cuidado e índice LACE |
| `fuentes/talamo_urgencias.csv` | `id_paciente`, `fecha_atencion`, `categoria_esi`, `horas_estadia`, `destino`, `diagnostico_cie10`, `diagnostico_texto` | Cluster de urgencias; el diagnóstico decide si el evento tiene que ver con la derivación |
| `fuentes/acg_estratificacion.csv` | `id_paciente`, `fecha_estratificacion`, `estrato` (G0..G3) | Riesgo en APS (ECICEP) |
| `fuentes/rayen_diagnosticos_cronicos.csv` | `id_paciente`, `diagnostico_cie10`, `fecha_registro` | Comorbilidad (índice de Charlson) |
| `fuentes/interconsultas.csv` | las de `lista_espera.csv` + `texto_interconsulta` | Proponer prioridad a las que nadie priorizó |
| `indicaciones.csv` | `id_paciente`, `fecha_indicacion`, `texto` y/o `continua_control`, `prioridad_control`, `plazo_dias`, `requiere_examen`, `examenes` | Lista de controles |
| `mediciones.csv` | `id_paciente`, `fecha_medicion`, `tipo_medicion`, `valor`, `unidad`, `fuera_de_rango` | Tendencias sostenidas (no un signo vital suelto) |
| `agenda_box.csv` | `id_box`, `fecha`, `especialidad`, `capacidad_cupos` | Agenda y llamadas (complementario) |

## Cada cuánto

Basta con un reporte por día hábil o cada pocos días. La lista oficial se reprioriza un día fijo a la semana
(lunes por defecto, `corte.dia_semana` en `motor/config/regla.yaml`); lo que llega entre cortes son alertas.
Con un reporte mensual también funciona: el corte se hace al llegar el reporte.

## A futuro: interoperabilidad

La Ley 21.668 (2024) obliga a que las fichas clínicas sean interoperables. Cuando los registros expongan los datos
en un estándar común (por ejemplo HL7 FHIR), basta con un adaptador más en
`motor/fuentes.py` que traduzca esos recursos a las mismas tablas: el motor no cambia.
