# Priorización dinámica de listas de espera — HLF

Prototipo para el desafío del Hospital Clínico Dra. Eloísa Díaz La Florida (AWS Breaking Barriers 2026).

La lista de espera hoy es una foto: alta → media → baja y, dentro de cada una, el más antiguo. Este MVP la
convierte en una película que se revisa **una vez por semana, un día fijo**, con alertas diarias entre medio, y
**sin pesos que un clínico tenga que calibrar**. La herramienta propone y explica; el equipo de gestión decide.

## Lo que pidió el hospital y cómo queda (entrevistas 4, 5 y 6)

| Lo que dijo el hospital | Cómo lo resuelve el prototipo |
|---|---|
| "Tienes que fijarme un día en que me vaya a repriorizar, para yo saber al día siguiente agendar". Las 72 h son para agendar, no para recalcular (E6) | **Corte semanal** (lunes, configurable): la lista vigente no cambia en la semana. Lo que llega en los reportes diarios aparece como **alerta** con el puesto que tendría. El jefe o la gestora pueden **adelantar** a alguien con un motivo (`motor/cortes.py`) |
| "Quiero ver por qué pasó del 7 al 3" y "cambió de media a alta por X cosa" (E5) | **Trazabilidad T1 → T2**: prioridad del especialista → prioridad de hoy con su motivo, y el **puesto en cada corte** con lo que llegó entre uno y otro. Cada decisión queda con usuario, rol y motivo ("¿por qué subiste a este?") |
| "Grandes clusters": hospitalización (días, tipo de cama, UCI, cirugía), urgencias, diagnósticos graves, ACG G1–G3; no un signo vital suelto (E5) | **Clusters por paciente** (`motor/clusters.py`) con el **índice LACE** (puntos publicados) y Charlson desde CIE-10. Las mediciones solo cuentan como tendencia sostenida en 3 tomas |
| "No por orden de llegada" dentro de la misma prioridad (E5) | Dentro del carril rápido se ordena por **nivel de cuidado** (UCI > sala > urgencia) y luego por **LACE**; ya no por antigüedad |
| Las fuentes no conversan: Tálamo, Rayen, alertas ECICEP, ACG, todo con RUT (E4, E5) | **Adaptadores por fuente** (`motor/fuentes.py`): completan o agregan eventos sin duplicar, unidos por RUT seudonimizado. Reportes sintéticos de ejemplo en `data/fuentes_sinteticas/` |
| Hay especialidades que no priorizan: si pasan ~3 semanas, "priorízala tú según criterio clínico" con la guía por diagnóstico (E6) | **Interconsultas sin priorizar** (`motor/guias.py`): esperan con plazo medio; al día 21 usan la prioridad que propone la guía al leer el texto (reglas → Bedrock solo para leer → revisar). El especialista la confirma |
| Usuario: el gestor de consultas; el jefe de especialidad mira y pide "verlo mañana" (E5) | **Dos perfiles** en la interfaz: gestora (confirma o cambia puestos) y jefe de especialidad (pide ver antes a alguien, con motivo) |
| La validación la tiene que hacer alguien distinto del médico que priorizó (E6) | **Muestra ciega** para un revisor independiente y κ ponderado (`validar_concordancia.py`) |
| La eficiencia del box "va por otro carril" (E5) | El módulo de agenda queda como complemento: convierte la lista vigente en **a quién llamar** con 72 h de anticipación |
| "Dos urgencias por esguince en alguien derivado por hipoacusia no impactan"; un cardiópata con descompensación respiratoria, sí (R7) | **Pertinencia** (`motor/pertinencia.py`): un evento con diagnóstico solo mueve al paciente si se relaciona con su derivación (tabla CIE-10 por especialidad, configurable). Los demás se muestran sin mover. La UCI siempre cuenta; sin diagnóstico, se asume relacionado |
| "Dentro del mismo alto hay muchos que pueden ir más arriba o más abajo"; "un segundo infarto en corto plazo va por sobre uno con comorbilidades" (R7) | **Recurrencia** en el carril: nivel de cuidado → episodios graves relacionados en 12 meses → LACE → prioridad → antigüedad |
| "Si está agendado, no debería estar en la lista" (R7) | **Agendados** salen del orden hasta su cita; si no llega, vuelven. Acción "Agendar" con registro |
| La gestión mira el P90 y busca grupos por diagnóstico para estrategias focalizadas (R7) | Pestaña **Gestión (P90)** (`motor/gestion.py`): P50 y P90 por especialidad, el grupo extremo por diagnóstico con su perfil de riesgo y sugerencias |
| El BIAU solo existe en el Servicio Sur Oriente y se consulta persona a persona; escalar con la reportería de cada ficha (R7) | **Formato de entrada común** (`FORMATO_ENTRADA.md`): reportes en tablas que cualquier ficha exporta; adaptadores por fuente; FHIR como paso siguiente (Ley 21.668) |
| El score anterior falló por pesos arbitrarios y sin validar; recomiendan modelos multicriterio (MCDA) (R7) | La regla es un **MCDA lexicográfico**: criterios en orden, cada uno con fuente publicada o del registro; validación ciega con un especialista distinto (`validar_concordancia.py`) |

## Agente con IA generativa (`ia/`, ver `PLAN_AGENTE_IA.md`)

- **Agente clínico** (Amazon Bedrock, Converse API con JSON validado): evalúa a **cada paciente por separado** con una
  rúbrica versionada (`ia/rubrica/`) y devuelve categoría propuesta, puntaje 0–100 con anclas, evidencia citada
  (fecha, fuente) y lo que ignoró por no ser pertinente. El orden sale de ordenar puntajes: escala, se paraleliza y
  no se ancla al orden anterior. **Híbrido**: la IA puede subir; bajar de T1 lo decide una persona; la regla pone el
  piso (evento grave relacionado ⇒ alta).
- **Mundo sintético con verdad conocida** (`ia/mundo.py`): gravedad latente que evoluciona y genera eventos,
  mediciones y notas del CESFAM en texto. train / dev / test con semillas distintas; TEST con otros parámetros y otra
  redacción. La verdad (riesgo a 90 días) nunca llega al agente.
- **Regulador y ciclo** (`ia/regulador.py`, `ia/ciclo.py`): propone reglas generales desde los errores de TRAIN,
  pasa un filtro de fuga (sin casos, fechas ni frases copiadas), se acepta solo si mejora en DEV y se mide una vez en TEST.
- **Métricas** (`ia/evaluar.py`): κ, detección de deterioro, falsas alarmas, subtriaje de "alta", NDCG@10, τ de Kendall,
  frente a la regla actual (FIFO) y la regla MVP.
- Pestaña **Agente IA** en la interfaz: propuesta con evidencia (fecha, fuente, cita) y lo descartado por no
  pertinente; **aceptar**, **rechazar** (con motivo), **prioridad absoluta** (con motivo, también sube en la lista
  vigente) y **revertir**; bajar de categoría solo lo confirma el perfil **Jefe de especialidad**; recorrido del
  paciente (regla → IA → decisiones), cambios de la sesión y aprendizaje por iteración con la medición en TEST.
- Sin Bedrock todo corre en **modo simulado** (palabras clave) para probar el circuito; ese modo no es la IA.

### Resultados reales con Amazon Bedrock (15-10-2026, cuenta del taller, us-east-1)

Agente: **Claude Haiku 4.5** (`us.anthropic.claude-haiku-4-5-20251001-v1:0`), regulador: **Claude Sonnet 4.5**.
Converse API con salida JSON validada (`json_schema`) en el 100% de las llamadas, 0 errores.

TEST (118 pacientes que el agente y el regulador nunca vieron; otros parámetros y otra redacción de notas;
**los mismos pacientes para todos los métodos**, `ia/resultados/resumen_ciclo_bedrock.md`):

| Método | Empeoraron y los subió | Subió sin que empeoraran | Debían ser alta y quedaron en baja | κ | NDCG@10 |
|---|---|---|---|---|---|
| Regla actual (FIFO) | 0 de 23 | 0 de 95 | 6 de 29 | 0,34 | 0,75 |
| Regla MVP | 19 de 23 | 36 de 95 | 1 de 29 | 0,31 | 0,78 |
| Palabras clave (sin LLM) | 11 de 23 | 6 de 95 | 9 de 29 | 0,57 | 0,87 |
| **IA (Bedrock)** | **22 de 23** | **25 de 95** | **0 de 29** | **0,54** | **0,93** |
| IA + piso de la regla | 22 de 23 | 25 de 95 | 0 de 29 | 0,44 | 0,92 |

- Otra muestra de TEST (K2, 117 pacientes): 20 de 21 deterioros, 0 de 26 "alta" en baja. Con n ≈ 20 deterioros,
  el intervalo de 95% de "22 de 23" va de 79% a 99%: es una señal fuerte, no una cifra precisa.
- **Regulador**: propuso 2 reglas clínicas generales; bajaban el objetivo en DEV (0,749 → 0,734) y se rechazaron.
  Sus otras propuestas eran demasiado largas y el filtro las descartó (corregido: ahora sabe el límite y recibe
  por qué se rechazó). La rúbrica final sigue siendo v0.
- **Hospital** (`propuestas_hlf.csv`): 423 pacientes en lista evaluados, 0 errores, 927.417 tokens de entrada y
  130.587 de salida (≈ US$ 1,74; < medio centavo por paciente). Propone subir de grupo a 93 y bajar a 166 (bajar
  no se aplica sin el jefe). Los 8 del carril rápido: la IA también los puso en alta. De 21 eventos no
  relacionados con la derivación, la IA declaró como descartados los 21.
- La caché (`ia/cache/`) reproduce cada propuesta sin volver a llamar a Bedrock: misma ficha + misma rúbrica +
  mismo modelo ⇒ misma respuesta (auditable).
- **S3**: `python -m ia.s3 subir --bucket <bucket>` sube `ia/rubrica`, `ia/resultados` y `data/mundo` sin las
  carpetas `*_verdad` (bucket del taller: `hlf-priorizacion-ia-<cuenta>`).

## La regla (sin pesos)

0. **Pertinencia.** Solo cuentan los eventos relacionados con aquello por lo que el paciente espera (si el evento
   trae diagnóstico). Una urgencia por esguince no mueve a quien espera cardiología; una descompensación
   respiratoria, sí. La UCI cuenta siempre.
1. **Carril rápido.** Quien tuvo un evento grave relacionado en los últimos 30 días (según el registro: triage
   ESI 2, hospitalización, UCI) pasa adelante. Dentro del carril: **nivel de cuidado** más alto primero (UCI >
   hospitalización > urgencia), luego **recurrencia** (episodios graves en 12 meses), luego **índice LACE** (más
   riesgo de muerte o reingreso a 30 días primero), luego prioridad y antigüedad.
2. **Plazo dinámico.** El resto se ordena por cuánto se ha pasado de su plazo. El plazo parte en
   30 / 90 / 180 días según la prioridad, y cada señal nueva abre su propio plazo (14 días tras un evento grave,
   45 tras uno moderado, 60 tras una medición que empeora en 3 tomas). Manda el más atrasado: un evento nuevo
   nunca vuelve a nadie menos urgente. La **prioridad de hoy** (T2) es la categoría del plazo más exigente
   abierto: hasta 30 días = alta, hasta 90 = media.
3. **Cupo por antigüedad.** 1 de cada 10 puestos va a quien más tiempo lleva esperando.

Además: fallecidos, atendidos, altas y **agendados** salen del orden; las inasistencias generan alerta de contacto (sin
mover a nadie); quien lleva 180 días sin ningún dato queda para **verificar estado**; y cada puesto trae su
explicación.

**El ciclo semanal.** El lunes a las 7:00 la Lambda carga los reportes y publica la lista vigente
(`cortes/AAAA-MM-DD/lista_vigente.csv` en S3). Desde el martes se agenda con ella (cada persona, al menos 72 h
antes de su hora). De martes a viernes, el reporte de la mañana deja las **alertas** (eventos graves con su
puesto proyectado) sin mover la lista. El lunes siguiente, todo lo que llegó entra al nuevo orden.

**IA generativa, donde aporta y sin decidir el orden:**
- Lee las **indicaciones de control** en texto libre ("control en 3 meses con eco") y las convierte en un plazo.
- Lee las **interconsultas sin priorizar** y dice qué criterios de la guía aparecen; la tabla de la guía decide.
- Redacta la **explicación** de cada puesto y el **aviso** para el equipo a partir de los hechos.
En los tres casos: reglas primero, Bedrock solo si las reglas dudan, y si nadie está seguro queda para revisar.

### De dónde sale cada número (nada lo inventamos ni lo calibra un clínico)

| Número | Fuente |
|---|---|
| Gravedad de los eventos (leve / moderada / grave) | El propio registro clínico (ESI 2, hospitalización, UCI = grave) |
| Pertinencia de un evento a la derivación | Capítulos CIE-10 por especialidad + asociaciones de riesgo que nombró el hospital (cardiopatía y respiratorio, diabetes y cardiovascular/renal). Propuesta a validar con cada jefe |
| Recurrencia antes que LACE en el carril | Lo dijo el hospital (reunión 7); el puntaje HOSPITAL (Donzé 2013) también suma ingresos previos |
| Orden UCI > sala > urgencia dentro del carril | Nivel de cuidado del registro. Sobrevivientes de UCI: más mortalidad a 5 años que otros hospitalizados (HR 1,33; Lone et al., AJRCCM 2016) |
| Índice LACE: días de estada, ingreso urgente, Charlson, urgencias en 6 meses | Puntos publicados por van Walraven et al., CMAJ 2010 (muerte o reingreso a 30 días; ≥ 10 = riesgo alto) |
| Índice de Charlson desde CIE-10 | Charlson et al. 1987, codificación CIE-10 de Quan et al. 2005 |
| Ventana del carril rápido: 30 días | Lógica NEWS2: un solo hallazgo grave basta para actuar. La simulación da casi lo mismo con 14, 30 o 60 días |
| Plazos 30 / 180 días | Pauta del piloto BID en el Hospital San Juan de Dios (urgente 30 días, normal 6 meses); "media" en 90 |
| Cupo por antigüedad 10% | Sensibilidad de la simulación |
| Corte semanal, 3 semanas para proponer prioridad | Lo pidió el hospital (entrevista 6) |
| Criterios de la guía para interconsultas sin priorizar | **Ejemplo** armado por el equipo con signos de alarma comunes; se reemplaza por las guías por diagnóstico del HLF |

Todo está en `motor/config/regla.yaml` y `motor/config/guias.yaml`. Es configuración, no código.

## Front «pulso.» (`web/`): hacia dónde va el producto

Interfaz web con el diseño del mockup del equipo (`pulso.`), alimentada con el motor y las propuestas reales del
agente en Bedrock. Es estática (HTML, CSS y JavaScript sin dependencias) y lee un solo archivo de datos:

```powershell
. .\entorno.ps1
python -m web.servidor          # regenera web/datos.js y abre en http://localhost:8000
# o, sin servidor: python -m web.construir  y doble clic en web\index.html
```

- **Resumen**: personas en la lista vigente, umbral del 90% (P90 del hospital), quienes lo superan, prioridad alta
  hoy; histograma de espera; por especialidad; "El contexto cambió" (antecedentes nuevos desde el corte anterior);
  bandeja de ingresos y resumen del agente IA.
- **Lista de espera**: lista vigente (corte del lunes) o propuesta IA; filtros por carril rápido, mayor espera,
  prioridad y "por revisar"; búsqueda, especialidad y exportación a CSV.
- **Ficha de paciente**: por qué está en esa posición (explicación de la regla), evolución corte a corte (prioridad,
  puesto, medición), propuesta del agente con evidencia y lo descartado, y las decisiones: aceptar, rechazar,
  prioridad absoluta y revertir (bajar solo con el perfil jefe de especialidad; el perfil se cambia abajo a la izquierda).
- **Nuevos ingresos**: interconsultas sin prioridad del especialista con la propuesta de la guía.
- **Agente IA**: evaluados, sube/baja, costo, medición en TEST, aprendizaje del regulador y decisiones de la sesión.
- Las decisiones quedan en el navegador y, con `python -m web.servidor`, en `salidas/registro_decisiones.csv` (el
  mismo registro de la consola Streamlit). El orden de la propuesta IA en el navegador reproduce exactamente el de
  `ia/agente.ordenar` (verificado con los 423 pacientes).
- En producción: la Lambda del lunes genera `datos.js` y el front se sirve desde S3 + CloudFront o App Runner.
- **Desplegado (15-10-2026, cuenta del taller):** bucket privado S3 `hlf-priorizacion-web-<cuenta>` + CloudFront con
  Origin Access Control. Despliegue idempotente con `python -m infra.desplegar_web` (sube los 4 archivos con su
  Content-Type e invalida la caché; fallback a Lambda Function URL si CloudFront no está permitido).
  URL del front (los 423 pacientes de la lista vigente): **https://da8n28k4fli3t.cloudfront.net/**

`app.py` (Streamlit) queda como **consola completa** del equipo: alertas del día con eventos de prueba,
indicaciones en texto libre, impacto, equidad, indicadores y agenda.

## Inicio rápido

Guion de la demo con cifras verificadas y respuestas a preguntas del jurado: [`DEMO.md`](DEMO.md).

En Windows (PowerShell), desde la carpeta del proyecto (la que tiene `app.py`):

```powershell
py -3 -m venv .venv                      # si "python" abre la Microsoft Store, usar "py"
.\.venv\Scripts\Activate.ps1             # si bloquea scripts: Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
pip install -r requirements.txt
python -m pytest -q
. .\entorno.ps1                          # modelos de Bedrock, región y bucket (sin claves)
streamlit run app.py
```

Notas de PowerShell: las variables se fijan con `$env:NOMBRE = "valor"` y duran lo que dura la ventana; `*>`
guarda la salida en UTF-16 (para leerla después mejor `| Out-File -Encoding utf8 salida.txt`). Los tests son
herméticos: pasan igual con o sin `entorno.ps1` cargado (no llaman a AWS).

Actualizar a un zip nuevo sin perder `.venv`, `ia/cache` ni resultados (robocopy fusiona carpetas; **no usar
`Copy-Item -Recurse` sobre una carpeta existente ni `robocopy /MIR`, que borra lo que no viene en el zip**):

```powershell
Remove-Item -Recurse -Force "$HOME\Downloads\nuevo" -ErrorAction SilentlyContinue
Expand-Archive "$HOME\Downloads\hlf-priorizacion.zip" "$HOME\Downloads\nuevo"
robocopy "$HOME\Downloads\nuevo\hlf-priorizacion" "$HOME\Downloads\hlf-priorizacion\hlf-priorizacion" /E /NFL /NDL /NJH /NP
# robocopy termina con código 0 a 7 cuando todo salió bien
```

```bash
pip install -r requirements.txt
streamlit run app.py                     # interfaz para el equipo de gestión (abre en el navegador)
python -m pytest -q                      # todos los tests (sin red)
python ingesta.py --demo                 # carga una semana como "reporte diario" (incluye las otras fuentes)
python validar_datos.py [carpeta]        # revisa un archivo nuevo (p. ej. el real del hospital) antes de usarlo
python validar_concordancia.py muestra --n 50     # muestra ciega para un revisor independiente (KPI κ)
python validar_concordancia.py comparar salidas/validacion/muestra_<fecha>.csv
python priorizar.py                      # lista de hoy -> salidas/lista_priorizada_<fecha>.csv
python priorizar.py --agenda 2026-10-13  # además: agenda propuesta y lista de llamadas del día (CSV para Excel)
python demo_evento.py                    # escena en la terminal: llega una hospitalización
python sim/generar_fuentes.py            # vuelve a fabricar los reportes sintéticos de las otras fuentes
python sim/simulador.py                  # reglas y cadencias (diaria vs. semanal) -> sim/resultados/
python sim/robustez.py                   # 30 submuestras del 80%
python sim/escala.py                     # tamaño real del HLF (~27.000 pacientes, 49 especialidades)
python sim/agenda_sim.py                 # políticas de uso del box sobre los 2.188 bloques
python sim/graficos.py                   # gráficos para el pitch -> salidas/graficos/
```

### La interfaz (`app.py`): 12 pestañas (incluye Agente IA)

Barra lateral: **Hoy** (la lista vigente es la del último corte, que se muestra junto al próximo), especialidad,
modo, **perfil** (gestora de demanda o jefe de especialidad), nombre, las fuentes cargadas y "Quitar cambios de
la demo".

1. **Lista vigente**: puesto, cambio desde el corte anterior, prioridad "media → alta", por qué está ahí,
   atraso, avisos (alerta desde el corte, sin datos, inasistencias) y cambio frente a la regla actual. En el
   detalle: la explicación (T1 → T2), **cómo ha cambiado corte a corte**, los **clusters** (hospitalización,
   urgencias, comorbilidad, ACG, LACE), la línea de tiempo y la decisión según el perfil.
2. **Alertas del día**: lo que llegó desde el corte con el puesto que tendría si se repriorizara hoy. Aquí se
   prueba la escena de la demo (llega un evento) y se **adelanta** a alguien con motivo.
3. **Qué cambió en el corte**: la revisión del lunes frente al corte anterior, con resumen (plantilla o Bedrock).
4. **Sin priorizar**: interconsultas sin prioridad del especialista, lo que escribió quien derivó, la propuesta
   de la guía y su estado; se confirma o se cambia.
5. **Gestión (P90)**: percentiles de espera por especialidad y el grupo extremo (sobre el P90 o más de N días)
   agrupado por diagnóstico, con sugerencias de estrategia focalizada y descarga.
6. **Indicaciones**: se pega una indicación de control; la herramienta la lee y muestra su efecto en el próximo corte.
7. **Impacto**: simulación de reglas y cadencias.
8. **Equidad**: auditoría por grupo y pacientes por verificar.
9. **Indicadores**: los 4 KPIs del hospital.
10. **Decisiones**: registro de confirmaciones, cambios, adelantos, agendados y prioridades confirmadas.
11. **Agenda y llamadas** (complementario): a quién llamar, agenda propuesta por box, reserva y descargas.

Modos (`--modo` en `priorizar.py` y `demo_evento.py`): `carril_plazo` (MVP, por defecto) · `carril` (regla
actual + carril rápido) · `actual` (regla del hospital) · `puntaje` (puntaje v1 con pesos a mano, opcional).

## Estructura

```
motor/priorizacion.py          Regla MVP: evaluar_paciente (T1, T2, carril, plazo), clave_orden, priorizar
motor/clusters.py              Clusters por paciente, índice LACE, Charlson desde CIE-10, nivel de cuidado, recurrencia
motor/pertinencia.py           ¿El evento tiene que ver con la derivación? (tabla CIE-10 por especialidad)
motor/gestion.py               Percentiles de espera, grupo extremo por diagnóstico y sugerencias para la gestión
motor/cortes.py                Corte semanal, alertas desde el corte, adelantos con motivo, historial por corte
motor/fuentes.py               Adaptadores: Tálamo hospitalizado y urgencia, ACG/ECICEP, Rayen, interconsultas
motor/guias.py                 Prioridad propuesta para interconsultas sin priorizar (reglas + Bedrock + revisar)
motor/config/regla.yaml        Parámetros del MVP (sin pesos)
motor/config/guias.yaml        Guía de EJEMPLO por especialidad (reemplazar por las del HLF)
motor/puntaje.py               Carga de datos + puntaje v1 (modo opcional)
motor/explicar.py              Explicación: plantilla determinista + Amazon Bedrock con respaldo
motor/auditoria.py             Auditoría de equidad
motor/indicaciones.py          Lectura de indicaciones de control en texto libre
motor/privacidad.py            Borra RUT, teléfonos y correos antes de Bedrock; seudónimo del RUT para unir fuentes
motor/agenda.py                Agenda del box, riesgo de no llegar, sobrecupo con tope, reserva, llamadas del día
motor/cambios.py               Qué cambió entre dos fechas + resumen
motor/ingesta.py               Incorpora el reporte diario (y los de otras fuentes) al almacén sin duplicar
motor/exportar.py              CSV para Excel (es-CL), con prioridad de partida, de hoy y su motivo
ia/agente.py, ia/bedrock.py    Agente clínico en Bedrock (ficha observable, rúbrica, JSON validado, caché, híbrido)
ia/rubrica/v0.md               Rúbrica versionada del agente (solo la cambia el ciclo o una persona)
ia/regulador.py, ia/ciclo.py   Regulador (propone reglas desde TRAIN, filtro de fuga) y ciclo DEV/TEST
ia/evaluar.py, ia/mundo.py     Métricas sobre los mismos pacientes y mundo sintético con verdad conocida
ia/decisiones.py               Aceptar, rechazar, prioridad absoluta, revertir; pertinencia IA vs regla
ia/s3.py                       Subir y bajar rúbricas, resultados y mundo (sin la verdad) a S3
ia/resultados/, ia/cache/      Corridas reales en Bedrock (15-10-2026) y caché que las reproduce sin llamar
web/                           Front «pulso.»: index.html, estilos.css (del mockup), app.js, construir.py, servidor.py
credenciales_aws.ps1           Claves temporales del taller (ignorado por git y Docker; lo carga entorno.ps1)
entorno.ps1                    PowerShell: región, modelos y bucket (sin claves)
app.py                         Interfaz Streamlit
validar_concordancia.py        Muestra ciega para un revisor independiente y κ ponderado
validar_datos.py               Revisa una carpeta de datos (también fuentes/)
priorizar.py, demo_evento.py, ingesta.py                     Línea de comandos
api/handler.py, api/diario.py  Lambdas (la diaria publica el corte del lunes y las alertas de los otros días)
infra/                         SAM, Dockerfiles, README de despliegue
sim/                           simulador (reglas y cadencias), robustez, agenda_sim, escala, graficos, generar_fuentes
data/dataset_hlf_ambulatorio/  Dataset del desafío
data/fuentes_sinteticas/       Reportes INVENTADOS de las otras fuentes, con semilla fija
tests/                         14 archivos, 134 tests (test_entrevistas.py: lo pedido en las entrevistas 5, 6 y la reunión 7)
FORMATO_ENTRADA.md             Qué reportes y columnas tiene que exportar cualquier ficha para usar la herramienta
```

## Resultados de la simulación (datos sintéticos)

Capacidad escalada para que cada especialidad atienda al 25% de sus pacientes en 6 meses. Cohorte: 61
pacientes con un evento grave mientras esperaban. Incluye las fuentes sintéticas y las 14 interconsultas nuevas.

| Métrica | Regla actual | **MVP** | Puntaje v1 |
|---|---|---|---|
| % atendidos ≤ 30 días tras su primer evento grave | 3,3% | **90,2%** | 72,1% |
| Mediana de días entre evento grave y atención | 67 | **8** | 17 |
| Eventos graves ocurridos estando todavía en lista | 99 | **69** | 92 |
| Pacientes "baja" atendidos | 0 | 25 | 15 |
| Pacientes que siguen esperando > 365 días | 128 | **124** | 126 |
| % atendido, NSE bajo | 25,6% | 26,2% | 25,6% |
| % atendido, comunas rurales | 30,2% | 25,6% | 20,9% |

### ¿Cada día o una vez por semana? (`sim/resultados/cadencia.md`)

| Cadencia (MVP) | % ≤ 30 d tras evento grave | Mediana días evento → atención | Eventos graves en lista | Días hábiles en que cambia el orden de los 20 primeros |
|---|---|---|---|---|
| Recalcular cada día | 90,2% | 8 | 69 | 35,1% |
| Corte semanal (lunes) | 90,2% | 9,5 | 77 | 17,5% |
| Corte semanal + alertas que se adelantan | 88,5% | 9 | 77 | 17,5% |

Repriorizar los lunes deja quieta la lista con que se agenda (cambia la mitad de los días, y solo los lunes) a
cambio de 1 a 1,5 días más de mediana. En la simulación los cupos de cada especialidad caen en pocos días, por
eso adelantar las alertas casi no cambia el resultado; en operación, el adelanto es la vía para el caso que no
puede esperar.

### Robustez, escala y box

- **30 submuestras del 80%**: el MVP gana en 30 de 30 en reacción ante eventos graves (mediana 86% vs 4%) y en
  eventos graves en lista (61 vs 80,5). En atención rural queda peor en 25 de 30: la brecha es sistemática.
- **Escala** (`sim/resultados/escala.md`): con ~27.000 pacientes en 49 especialidades, priorizar todo toma
  1,7 s y reordenar una especialidad cuando llega un evento, 35 ms, en un solo núcleo.
- **Box** (`sim/resultados/agenda.md`, complementario): llamar antes + lista de reserva sube de 73,8 a 79,6
  atenciones por 100 cupos (+1.268 en 6 meses); con sobrecupo solo donde cabe, 82,8 (+1.968). Los bloques de 12
  cupos de 25 minutos están sobreagendados para atenciones de 33 a 43 minutos.

### Para contar con honestidad

- **El 90% es en parte la definición del carril**: mide que se cumple el KPI de reacción, no un beneficio clínico.
- **Equidad**: en el corte del 12-10-2026 las personas de 65 años o más quedan en 0,79, justo bajo el umbral de
  0,8 (el 13-10 están en 0,82: oscilan en el borde). La auditoría las marca para revisar. Las comunas rurales se
  atienden algo menos en la simulación (25,6% vs 30,2%). Respuesta: auditoría por grupo + verificar estado a
  quien lleva 180 días sin datos (36 personas hoy).
- **Las otras fuentes son inventadas** (`data/fuentes_sinteticas/`): muestran cómo se unen, no qué dicen.
- **La guía para interconsultas sin priorizar es un ejemplo**: falta la del hospital.
- **Datos sintéticos**: las cifras muestran el mecanismo, no el impacto real.

## Indicadores del desafío

| KPI del hospital | Meta | Prototipo |
|---|---|---|
| Tiempo entre un evento clínico y la reevaluación | < 72 h | < 24 h: el reporte de la mañana deja el evento grave como alerta, con su puesto proyectado. La lista oficial se reprioriza cada lunes |
| Lista revisada con criterio común | 100% | 100%: todas las personas en espera se evalúan con la misma regla en cada corte |
| Indicaciones de control en texto libre visibles en la lista | ≥ 90% | 100% en 30 notas de ejemplo: 90% se resuelve solo y el resto queda para revisar |
| Concordancia con la priorización clínica | κ ≥ 0,70 | Pendiente. `validar_concordancia.py` arma la muestra ciega para un médico distinto del que priorizó y calcula κ ponderado |

## Por qué esto no es el score que no funcionó

El hospital ya probó un score de priorización y no se usó: tenía poca correlación clínica, pesos arbitrarios y
nadie lo validó con especialistas (reunión 7). Aquí:

- Es un **modelo multicriterio (MCDA) lexicográfico**: los criterios van en orden (evento grave relacionado, nivel
  de cuidado, recurrencia, riesgo LACE, atraso del plazo) y cada uno sale de una fuente publicada o del registro.
  No hay pesos inventados. Si el hospital quiere sumar juicios cualitativos (impacto social), el modo `puntaje` es un
  MCDA aditivo cuyos pesos fijaría su propio panel.
- Lo que depende de la enfermedad (qué evento es pertinente a qué derivación) está en una tabla que valida cada
  jefe de especialidad.
- La validación la hace un especialista distinto del que priorizó, con una muestra ciega (`validar_concordancia.py`).
- Cada puesto queda trazado (motivo, fuente, usuario): sirve para la trazabilidad médico-legal que pidieron.

## Uso diario y semanal

El hospital no tiene APIs hacia la ficha; trabaja con reportes. Cada mañana:

1. Se dejan en una carpeta las filas nuevas del día: eventos, mediciones, citas, indicaciones y, si las hay, los
   reportes de otras fuentes (`talamo_hospitalizaciones.csv`, `talamo_urgencias.csv`, `acg_estratificacion.csv`,
   `rayen_diagnosticos_cronicos.csv`, `interconsultas.csv`).
2. `python ingesta.py --reporte <carpeta> --fecha <día>` (o la Lambda diaria con S3) las suma al almacén sin
   duplicar. Las otras fuentes van a `almacen/fuentes/`.
3. **Lunes**: se publica la lista vigente. **Otros días**: se dejan las alertas desde el corte.
4. Para agendar: `python priorizar.py --agenda <día>` o la pestaña "Agenda y llamadas".

Prueba de consistencia: separar la semana del 14 al 20 de septiembre (con sus fuentes) y cargarla como reporte
da exactamente los mismos cambios que calcular la lista directamente (`tests/test_diario.py`).

## Escalar a otros servicios (sin BIAU)

El BIAU solo existe en el Servicio Metropolitano Sur Oriente y se abre persona a persona desde la ficha, así que
no sirve para extraer en masa ni para otros servicios. La herramienta lee **reportes en tablas** que cualquier
ficha exporta (`FORMATO_ENTRADA.md`). Cada fuente nueva es un adaptador en `motor/fuentes.py`. Con la Ley 21.668
de interoperabilidad, el paso siguiente es un adaptador HL7 FHIR que produzca las mismas tablas.

## Cuando lleguen los datos reales

1. `python validar_datos.py <carpeta>` (revisa también `fuentes/`).
2. Corregir lo que indique. Los reportes de otras fuentes van en `<carpeta>/fuentes/` (o en `HLF_FUENTES`); si
   traen `rut` en vez de `id_paciente`, se seudonimiza con la sal de `HLF_SAL`.
3. `export HLF_DATOS=<carpeta>` y correr la app, `priorizar.py` y las simulaciones.

Variables: `HLF_DATOS`, `HLF_FUENTES` (`no` las apaga), `HLF_HOY`, `HLF_REGISTRO`, `HLF_CLAVE`, `HLF_SAL`,
`BEDROCK_MODEL_ID`, `AWS_REGION`.

## AWS

Ver `infra/README.md`: dos Lambdas en imagen de contenedor, EventBridge Scheduler (7:00 de lunes a viernes, hora
de Chile; el lunes publica el corte), HTTP API, S3 cifrado y la interfaz en App Runner. Bedrock se llama con la
Converse API; sin modelo configurado o ante cualquier error se usa la plantilla. **Bedrock y S3 ya corrieron contra
la cuenta del taller** (15-10-2026: 1.000+ llamadas a Claude Haiku 4.5 y Sonnet 4.5 en us-east-1, bucket
`hlf-priorizacion-ia-<cuenta>`).

**Desplegado sin Docker (16-10-2026):** la Lambda del corte del lunes `hlf-priorizacion-corte` (Python 3.12, capa
administrada AWSSDKPandas + PyYAML en el zip) regenera `datos.js` y lo publica en el bucket del front, invalidando
CloudFront. La dispara EventBridge Scheduler `hlf-priorizacion-corte-lunes` con `cron(0 7 ? * MON *)` en zona
America/Santiago. Despliegue idempotente: `python -m infra.desplegar_lambda_corte`. Verificada en AWS: 423
pacientes, 0 errores. La App Runner de la interfaz Streamlit sigue en la plantilla sin desplegar.

## Privacidad y seguridad

Datos de salud: categoría especial en la Ley 21.719 (vigente desde el 01-12-2026).

- Los datos quedan en la cuenta de AWS del hospital; el bucket va cifrado y con acceso público bloqueado.
- A Bedrock va solo el ID seudonimizado y hechos codificados. El texto libre (indicaciones e interconsultas) va
  sin RUT, teléfonos ni correos. Los nombres propios no se detectan con reglas: en producción, Comprehend Medical.
- Las fuentes se unen por un seudónimo del RUT (`motor/privacidad.seudonimo`, con sal secreta).
- Retención de Bedrock en `none`. Interfaz con clave (`HLF_CLAVE`); en producción, Cognito.
- Trazabilidad: cada decisión queda con usuario, rol, fecha, motivo y versión de la regla.

## Datos que conviene pedir al hospital (mejoran el MVP, no lo bloquean)

- Las **guías de priorización por diagnóstico** (como la de cataratas) para reemplazar `guias.yaml`.
- Los reportes reales de Tálamo hospitalizado (días, tipo de cama, pabellón) y urgencia, la estratificación ACG y
  los diagnósticos crónicos de APS, con las columnas de `motor/fuentes.py`.
- Las indicaciones de control en texto y el archivo con datos reales anonimizados.
- Un médico distinto del que priorizó para la muestra ciega de concordancia.
