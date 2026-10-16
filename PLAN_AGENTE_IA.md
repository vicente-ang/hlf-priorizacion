# Plan: agente clínico con IA generativa en AWS (para el equipo y para Kiro CLI)

Estado al 15-10-2026, 23:30. **K1 a K6 están hechas con Bedrock real** (Kiro CLI, cuenta del taller, us-east-1) y
revisadas: ver la sección 4. Lo pendiente es opcional (K3b, K7) y la sección 6 trae el prompt para Kiro.

## 1. La idea en una frase
Un agente en Amazon Bedrock lee la historia de cada paciente que ya está en la lista (eventos, mediciones y
**notas del CESFAM o epicrisis en texto**) y propone si hay que subirlo de grupo y qué puntaje de riesgo tiene para
ordenarlo dentro de su grupo, con la evidencia citada. Un segundo agente (regulador) mejora las instrucciones del
primero comparando con una verdad conocida. La regla actual queda como piso de seguridad y línea base.

## 2. Qué cambiamos del plan original y por qué
| Plan original | Cambio | Por qué |
|---|---|---|
| El LLM recibe la lista completa y la ordena | Evalúa **a cada paciente por separado** (puntaje 0–100 con anclas + categoría + evidencia) y el orden sale de ordenar | 26.000 pacientes no caben en un pedido; el orden de un LLM sobre listas largas es inestable y sesgado por posición; así se paraleliza, se recalcula solo a quien tuvo datos nuevos y no se "ancla" al orden anterior |
| "Entrenar" el modelo | **Optimizar la rúbrica** (instrucciones) con un regulador: propone reglas generales, se aceptan solo si mejoran en DEV, se mide una vez en TEST | Sin etiquetas reales, ajustar pesos (fine-tuning) no es viable ni honesto esta noche; esto es medible y se puede graficar por iteración |
| La verdad la da otro LLM que imita a un médico | **Mundo sintético con riesgo latente conocido**; el LLM-médico queda como segunda opinión | Dos LLM de acuerdo no prueban que estén en lo correcto (circular). Con verdad conocida se mide sensibilidad, κ y NDCG |
| Fuentes médicas distintas para evitar fuga | Además: semillas distintas, TEST con otros parámetros y **otra redacción** de notas, el regulador solo ve TRAIN, filtro de fuga en cada regla | La fuga más probable no es la literatura: es copiar casos o frases a la rúbrica |
| El LLM decide | La IA **propone subir**; bajar requiere una persona; la regla pone el piso | Lo exige el hospital (trazabilidad médico-legal, validación por especialista) |

## 3. Lo que ya está hecho (carpeta `ia/`)
- `ia/mundo.py`: train (420), dev (300) y test (300), mismo esquema que el dataset del hospital + `notas_clinicas.csv`.
  Gravedad latente semanal con trayectorias (estable, progresivo, agudo, mejora, fluctuante), distractores (urgencias
  no relacionadas), notas vagas o engañosas. Verdad: riesgo de desenlace grave a 90 días y categoría ideal.
- `ia/agente.py` + `ia/bedrock.py` + `ia/rubrica/v0.md`: ficha observable, llamada a Bedrock con JSON validado
  (probada con el Stubber de boto3), caché, paralelo, modo simulado (palabras clave) y combinación híbrida con la regla.
- `ia/evaluar.py`: FIFO vs regla vs IA vs híbrido. `ia/regulador.py` + `ia/ciclo.py`: ciclo con filtro de fuga.

Línea base **sin Bedrock** (agente simulado por palabras clave; NO es la IA):

| Método | DEV: detecta deterioro | DEV: NDCG@10 | TEST: detecta deterioro | TEST: subtriaje de "alta" |
|---|---|---|---|---|
| Regla actual (FIFO) | 0% | 0,47 | 0% | 19% |
| Regla MVP | 83% | 0,63 | 80% (35% falsas alarmas) | 3% |
| Palabras clave | 91% | 0,81 | **44%** | **39%** |

Las palabras clave se caen cuando cambia la redacción (TEST): es el argumento para un LLM, y la métrica que el
LLM tiene que ganar en TEST.

## 4. Tareas para Kiro CLI

### Hechas el 15-10-2026 (resultados verificados contra la verdad del mundo sintético)

| Tarea | Resultado |
|---|---|
| K1 Conectar Bedrock | Agente `us.anthropic.claude-haiku-4-5-20251001-v1:0`, regulador `us.anthropic.claude-sonnet-4-5-20250929-v1:0`, us-east-1. Salida `json_schema` en todas las llamadas, 0 errores |
| K2 Primera medición | DEV 118 y TEST 117 pacientes, 0 errores (~300.000 tokens de entrada y ~46.000 de salida por conjunto). TEST: 20 de 21 deterioros subidos; 0 "alta" en baja |
| K3 Ciclo regulador | 3 iteraciones; ninguna regla aceptada (2 probadas bajaban DEV 0,749 → 0,734; el resto, largas). Rúbrica final v0. TEST final: 22 de 23 deterioros, 0 de 29 "alta" en baja, NDCG@10 0,93 |
| K4 S3 | `ia/s3.py` (subir, bajar, listar). Bucket `hlf-priorizacion-ia-<cuenta>`, 33 objetos en `ia/`, sin `*_verdad` |
| K5 Hospital | 423 pacientes en lista, 0 errores, ≈ US$ 1,74. Sube de grupo a 93, propone bajar a 166 (requiere jefe) |
| K6 Pestaña Agente IA | Completada después en esta revisión: prioridad absoluta, revertir, bajar solo con perfil jefe, recorrido, cambios de la sesión, tabla de TEST en números absolutos; revertir adelantos y agendados en Decisiones |

Correcciones hechas al revisar (no requieren volver a llamar a Bedrock; se rehízo todo desde la caché):
- `ia/evaluar.comparar` mide **todos los métodos sobre los mismos pacientes** que evaluó la IA. Antes la regla se
  medía sobre 296 y la IA sobre 118, y el NDCG de listas de distinto largo no se compara (la regla aparecía con
  0,66 de NDCG; sobre los mismos 118 es 0,78). `python -m ia.ciclo --modo bedrock --solo-informe` rehace la tabla.
- Subir/bajar se calcula con las categorías (el campo `direccion` del modelo no siempre coincide con el cambio de
  grupo). Las propuestas guardan además `modelo` e `ignorado`.
- El regulador conoce el límite de 300 caracteres por regla y recibe por qué se rechazó su propuesta anterior.

### Pendientes (opcionales, en orden)

**K3b. Repetir el ciclo regulador con el regulador corregido** (≈ 25 min, ≈ US$ 2)
- `. .\entorno.ps1` y luego `python -m ia.ciclo --modo bedrock --iteraciones 3 --muestra 120 | Out-File -Encoding utf8 ciclo.txt`
- ✅ `ia/resultados/resumen_ciclo_bedrock.md` actualizado. Si se acepta una regla, aparece `ia/rubrica/v1.md` y la
  medición en TEST se hace con ella: revisar a mano que la regla sea clínica y general. Si ninguna mejora DEV, se
  queda v0 y eso también se cuenta (el filtro funciona). Luego `python -m pytest -q`.
- Si se acepta una v1: volver a correr K5 con `--rubrica ia/rubrica/v1.md` (la caché no sirve, ≈ US$ 1,8).

**K7. Lambda semanal de IA**
- `api/ia_semanal.py`: el lunes evalúa solo a quien tuvo datos nuevos desde el corte anterior y escribe
  `s3://<bucket>/cortes/<fecha>/propuestas_ia.csv`. Agregarla a `infra/template.yaml` con permiso `bedrock:InvokeModel`
  restringido al modelo usado.
- (Opcional) Guardar las rúbricas en Bedrock Prompt Management; procesar listas completas con inferencia por lotes.

## 5. Cómo se cuenta en el pitch (honesto, con las cifras reales)
1. "La lista no se entera cuando el CESFAM reevalúa al paciente. Nuestro agente en Amazon Bedrock lee esa historia."
2. "No le pedimos al LLM que ordene 26.000 personas: evalúa a cada una con una rúbrica y cita la evidencia."
3. "Para medir sin médicos construimos un mundo sintético con verdad conocida; el agente nunca la ve. En TEST, con
   notas redactadas de otra forma: de 23 pacientes que empeoraron, la regla actual subió a 0, las palabras clave a
   11, nuestra regla a 19 y el agente a 22. Ninguno de los 29 que debían ser alta quedó en baja."
4. "El 'entrenamiento' es un regulador que corrige la rúbrica; solo se aceptan cambios que mejoran en un conjunto
   aparte. Esta vez propuso dos reglas que empeoraban y las rechazó: así se evita sobreajustar."
5. "La IA propone subir; bajar lo confirma el jefe; la regla pone el piso. Todo se revierte y queda registrado."
6. "Sobre los 423 pacientes del hospital: 0 errores, US$ 1,74 en total."
7. Límite: la verdad del mundo sintético la definimos nosotros y n es chico (23 deterioros); la validación real es
   con especialistas (κ ≥ 0,70, muestra ciega).

## 6. Prompt para pegar en Kiro CLI (pendientes)
> Lee `AGENTS.md` y `PLAN_AGENTE_IA.md` (sección 4, "Pendientes"). Estamos en Windows con PowerShell 5: usa
> `$env:` para variables, `;` para encadenar, y guarda salidas largas con `| Out-File -Encoding utf8 <archivo>`.
> Primero corre `. .\entorno.ps1` y `python -m pytest -q`. Haz K3b; antes dime qué vas a hacer en 3 líneas y
> después muestra la bitácora y la tabla de TEST de `ia/resultados/resumen_ciclo_bedrock.md`. No modifiques
> `ia/mundo.py`, `ia/rubrica/v0.md` ni `data/mundo/*_verdad`, y no escribas credenciales en archivos del
> proyecto. Si se acepta una regla, muéstramela antes de correr K5 con la nueva rúbrica.
