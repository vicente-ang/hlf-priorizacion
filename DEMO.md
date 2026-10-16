# Guion de la demo con el front «pulso.» (≈ 4 minutos y medio, recomendado)

Preparación: `. .\entorno.ps1` y `python -m web.servidor` → http://localhost:8000 a pantalla completa. Perfil
abajo a la izquierda: **Gestora de demanda**. Si quedaron decisiones de un ensayo: página Agente IA → **Borrar
decisiones de este navegador**. Plan B sin red ni Python: doble clic en `web\index.html` (mismos datos).
La consola Streamlit (`streamlit run app.py`) sigue disponible para la escena del evento en vivo (bloque 6).

## 1. Resumen: la lista en perspectiva (30 s)
- Tarjetas: **423** personas en la lista vigente (corte del lunes 12-10-2026), umbral del 90% **495 días**, **42**
  lo superan (9,9%), **124** con prioridad alta hoy, **9** en carril rápido.
- "El contexto cambió": quienes tienen antecedentes nuevos desde el corte anterior (p. ej. Paciente Azucena 469,
  HbA1c fuera de rango; Paciente Tulipán 150, urgencia **no relacionada**: no lo mueve).
- Abajo, el agente en Amazon Bedrock: **423** evaluados, propone subir a **93**, bajar a **166** (lo confirma el
  jefe), y descartó **21 de 21** eventos no relacionados con la derivación.
- Decir: "Lo que hoy hacen en Excel —el P90, qué cambió, quién entra— en una pantalla."

## 2. La lista: vigente y propuesta IA (30 s) · Lista de espera
- Especialidad **Traumatología**. Lista vigente: **#01 Paciente Orquídea 473**, carril rápido (con la regla
  actual sería el 52).
- Cambiar a **Propuesta IA**: #01 Paciente Petunia 055, #02 Paciente Lirio 114, **#03 Paciente Gardenia 079**.
- Decir: "Dos capas: la regla pone el piso y publica la lista del lunes; el agente lee la historia completa y
  propone otro orden. Nadie cambia nada sin dejar registro."

## 3. Por qué subiría: la ficha (60 s) · clic en Paciente Gardenia 079 (PAC-HLF-00079)
- Arriba: lista vigente **#42**, propuesta del agente **#03**.
- **Evolución en la lista** (Prioridad): carril rápido hasta el 28-09; el 05-10 sale porque la hospitalización
  (01-09) quedó fuera de la ventana de 30 días. Botón **Puesto**: llegó al #1 el 28-09, cayó al #47 el 05-10 y hoy
  está en el #42.
- **Propuesta del agente IA**: alta, puntaje **82**, confianza alta; evidencia con fecha y fuente: hospitalización
  por fractura de pelvis (01-09-2026), EVA 9/10 contra 2/10 antes. **Descartado**: la urgencia por artrosis de
  rodilla, no pertinente a lumbago.
- Decir: "La regla tiene una ventana; el agente ve que el dolor no bajó. Y dice qué descartó, como nos pidieron."

## 4. Bajar lo decide una persona (40 s) · Paciente Begonia 008 (PAC-HLF-00008)
- Buscar "Begonia 008" en la lista. La IA propone **baja** (puntaje 18, EVA 3→1).
- **Aceptar propuesta** como gestora → "Bajar de categoría lo confirma el jefe de especialidad".
- Clic en el perfil (abajo a la izquierda) → **Jefe de especialidad** → **Aceptar propuesta** → "#56 → #70".
- **Revertir** → "#70 → #56". (Opcional: motivo + **Prioridad absoluta** → #1 también en la lista vigente.)
- Página **Agente IA** → "Decisiones de esta sesión": quién, qué, motivo; también en `salidas/registro_decisiones.csv`.

## 5. ¿Funciona? (40 s) · Agente IA
- Tabla en 118 pacientes que el agente nunca vio (otra redacción de notas): de **23** que empeoraron, la regla del
  hospital subió a **0**, palabras clave a **11**, nuestra regla a **19**, el agente a **22**; de 29 que debían ser
  alta, **0** quedó en baja.
- Aprendizaje del regulador: propuso reglas; empeoraban la validación (0,749 → 0,734) y **no se aceptaron**.
- Costo de la corrida: **US$ 1,74** por 423 pacientes.

## 6. (Opcional, consola) Llega un evento: alerta, no terremoto (45 s)
- En Streamlit, pestaña Alertas del día: PAC-HLF-00008 → Ingreso a UCI → "si se repriorizara hoy: puesto 1, ↑45",
  la lista vigente no se mueve hasta el lunes; **Adelantar** con motivo. (Detalle en el guion de la consola.)

## 7. Cierre (15 s)
- `impacto.png`: con evento grave, atendidos en 30 días **3,3% → 90,2%**. "Con los reportes que ya tienen, en su
  cuenta de AWS, por menos de medio centavo de dólar por paciente."

---

# Guion con la consola Streamlit (plan B y escena del evento en vivo, ≈ 5 minutos)

Preparación: `streamlit run app.py`, navegador a pantalla completa. Barra lateral: **Hoy 13-10-2026** (lista
vigente: corte del lunes 12-10-2026), especialidad **Traumatología**, modo **Regla MVP**, perfil **Gestora de
demanda**. Tener abiertos `salidas/graficos/impacto.png` y `cadencia.png`.
Plan B si algo falla: el video grabado de esta misma secuencia y, en la terminal, `python demo_evento.py`.
La pestaña Agente IA no llama a Bedrock en vivo: muestra lo que el agente ya calculó (`ia/resultados/`), así que
la demo no depende de la red ni de las credenciales del taller.

Las cifras de abajo son las que aparecen en pantalla con los datos del desafío, las fuentes sintéticas y las
corridas reales en Amazon Bedrock del 15-10-2026 (verificadas el 15-10-2026).

## 1. La lista vigente y por qué cada uno está ahí (40 s) · pestaña Lista vigente

- Pantalla: "91 personas en la lista vigente. 2 en carril rápido…, 2 interconsultas sin priorizar". En la barra:
  "Lista vigente: corte del lunes 12-10-2026. Próximo corte: lunes 19-10-2026".
- Decir: "Ustedes nos dijeron: fíjame un día para repriorizar, y al día siguiente agendo. Esta es la lista del
  lunes; con ella se agenda toda la semana."
- Primera fila: **PAC-HLF-00473, "media → alta", carril rápido**; con la regla actual sería el 52.
- Bajar al detalle (viene seleccionado el #1):
  - "Prioridad de partida media (la dio el especialista). Hoy es alta por hospitalización (20-09-2026)".
  - **Cómo ha cambiado, corte a corte**: "En 7 semanas pasó del puesto 84 (24-08) al 1".
  - **Clusters**: 1 hospitalización, 7 días cama, con cirugía; 1 urgencia grave; Charlson 2; ACG G3;
    **LACE 11** (L5 + A3 + C2 + E1), riesgo alto de muerte o reingreso a 30 días.
- Decir: "Esta es la regla: el piso de seguridad. Dentro del carril no ordenamos por llegada: primero UCI,
  después sala, después urgencia; luego la recurrencia, luego el índice LACE, que tiene puntos publicados."

## 2. El agente en Amazon Bedrock lee la historia completa (80 s) · pestaña Agente IA

- Línea gris arriba: "**Claude Haiku 4.5 en Amazon Bedrock** (Converse, salida JSON validada) · rúbrica v0 ·
  **423 pacientes evaluados, 0 errores**" y "Pertinencia: de **21** eventos que la regla considera no
  relacionados con la derivación, la IA declaró como descartados **21**".
- En **Paciente** elegir **PAC-HLF-00079** (#3, "media → alta", puntaje 82, confianza alta, **puesto en la
  regla 42**). La ficha cita: hospitalización grave por fractura de pelvis el 01-09-2026; EVA 9/10 ese día contra
  2/10 antes. "Descartado por no estar relacionado: la urgencia por artrosis de rodilla". Al final: "Recorrido:
  regla vigente #42 → propuesta IA (híbrida) #3".
- Decir: "La regla tiene una ventana de 30 días para el carril rápido; esta hospitalización fue hace 42, así que
  la regla lo dejó en el 42. El agente lee la historia completa, ve que el dolor no bajó y propone subirlo,
  citando fecha y fuente de cada dato. Y dice qué descartó, igual que nos pidieron en las entrevistas."
- Elegir **PAC-HLF-00008** (#56, "media → baja", confianza alta: "lumbago crónico estable y en mejoría
  progresiva (EVA 3→1)"). Clic **Aceptar propuesta** → "Bajar de categoría lo confirma el jefe de especialidad".
- Cambiar **Perfil** a **Jefe de especialidad** → **Aceptar propuesta** → "Propuesta aceptada: #56 → #70".
  Luego **Revertir** → "#70 → #56". La tabla "Cambios de esta sesión" muestra las dos acciones, con quién y por qué.
- Decir: "La IA puede proponer subir. Bajar a alguien lo decide el jefe, y todo se puede revertir y queda en el
  registro. También existe **Prioridad absoluta**, con motivo obligatorio, que lo pone primero también en la
  lista vigente."
- Bajar a **Medición final en TEST** (118 pacientes que el agente nunca vio, con otra redacción de notas, los
  mismos para todos los métodos):
  - Empeoraron y los subió: regla actual **0 de 23**, palabras clave sin LLM **11 de 23**, regla MVP **19 de 23**,
    **IA 22 de 23**.
  - Debían ser alta y quedaron en baja: regla actual 6 de 29, palabras clave 9 de 29, **IA 0 de 29**.
  - Subió sin que empeoraran: regla MVP 36 de 95, **IA 25 de 95**.
- Decir: "¿Cómo sabemos que no es humo? Fabricamos pacientes con la verdad escondida: el agente nunca la ve. Un
  segundo agente, el regulador, mira los errores en entrenamiento y propone reglas para la rúbrica; solo se
  aceptan si mejoran en validación. Esta vez propuso dos, empeoraban la validación (0,749 → 0,734) y las
  rechazó. Medimos una sola vez al final."
- Volver el perfil a **Gestora de demanda**.

## 3. Llega un evento: alerta, no terremoto (45 s) · pestaña Alertas del día

- Paciente por defecto **#46 · PAC-HLF-00008 (media)** → evento **Urgencia por cólico renal (otro motivo)** →
  **Registrar evento** → "no lo mueve ni genera alerta" (sigue 46).
- Mismo paciente → evento **Ingreso a UCI** → **Registrar evento**.
- Pantalla: "si se repriorizara hoy: **Puesto 1 de 91, ↑45**" y "En la lista vigente sigue en el puesto 46: la
  alerta llega al equipo con el reporte de mañana y el lunes 19-10-2026 entra al nuevo orden".
- Decir: "Las 72 horas son para agendar. Si la lista se moviera a cada rato, nunca tendrían una posición fija.
  Entonces: el evento grave llega como alerta en menos de 24 horas, con el puesto que tendría."
- Botón **Adelantar a la lista vigente** (motivo prellenado "Ingreso a UCI el 13-10") → ahora es el #1 de la
  lista vigente, "adelantado por gestora de demanda".
- Decir: "Si no puede esperar al lunes, el jefe o la gestora lo adelantan, con su nombre y su motivo. Cuando les
  pregunten '¿por qué subiste a este y no a este otro?', está en el registro." (Con el perfil Jefe de
  especialidad, el botón dice "Pedir que lo vean antes".)
- **Quitar cambios de la demo** (barra lateral).

## 4. Las interconsultas que nadie priorizó (30 s) · pestaña Sin priorizar

- Tabla con 14 interconsultas sin prioridad. Viene seleccionada **PAC-HLF-00509 · Broncopulmonar**: «EPOC con
  exacerbaciones frecuentes, 2 hospitalizaciones por exacerbación este año» → **Propuesta: alta** por
  «exacerbaciones frecuentes». En la tabla, **PAC-HLF-00508 · Neurología** («Cefalea de larga data…») queda
  **por revisar**.
- Decir: "Hay especialidades que no priorizan. Mientras nadie la lee, espera con plazo medio; a las 3 semanas se
  usa la prioridad que propone la guía al leer lo que escribió quien derivó. La IA no decide: solo dice qué
  criterios de la guía aparecen; si nadie está seguro, queda para el especialista. Esta guía es un ejemplo:
  la reemplazan las suyas, como la de cataratas."

## 5. Impacto y confianza (40 s) · `impacto.png`, `cadencia.png`, pestañas Equidad e Indicadores

- `impacto.png`: de quienes tienen un evento grave, con la regla actual se atiende en 30 días el **3,3%**; con el
  MVP, el **90,2%**; la mediana baja de **67 a 8 días**; los eventos graves ocurridos en lista bajan de **99 a 69**.
  En **30 de 30** submuestras gana.
- `cadencia.png`: repriorizar los lunes deja quieta la lista: el orden de los 20 primeros cambia el **17,5%** de
  los días hábiles en vez del **35,1%**, a cambio de 1 día más de mediana (**9** con corte semanal y alertas).
- Equidad: "En el corte del lunes, los mayores de 65 quedan en **0,79**, justo bajo el umbral de 0,8 (el martes
  en 0,82). La herramienta lo avisa: eso es lo que tiene que hacer." 36 personas sin datos en 180 días quedan
  para llamar.
- Indicadores: evento → alerta en **< 24 h** (meta 72 h). Concordancia: la mide un médico distinto del que
  priorizó, con una muestra ciega (`validar_concordancia.py`).
- Cierre: "Dos capas: una regla sin pesos inventados que pone el piso, y un agente en Bedrock que lee la historia
  completa y propone, con evidencia. El equipo decide, todo queda registrado y se puede revertir. Con los
  reportes que ya tienen, en su cuenta de AWS, por menos de medio centavo de dólar por paciente."

## Si sobra tiempo (30 s)

- **Gestión (P90)**, pestaña Gestión:
  - Tabla de percentiles: en Traumatología la mediana es **298 días** y el P90 **475**.
  - Recuadro: "9 personas esperan más de 475 días. **M17 Artrosis de rodilla** reúne 4 de ellas (44%, frente al 30%
    de toda la lista): candidato a una estrategia focalizada…; 2 no tienen datos en 180 días: llamar antes".
  - Decir: "Lo que hoy hacen a mano en Excel: mirar el P90, ver si se agrupa por diagnóstico y decidir un operativo.
    Aquí sale solo, con el perfil de riesgo de ese grupo."
- **Indicaciones**: paciente #46 · PAC-HLF-00008, "Control prioritario en 2 semanas con ecografía.", consulta
  hace 60 días → **Leer indicación** → **Aplicar** → si se repriorizara hoy pasa del **46 al 26**; entra en el
  corte del lunes 19-10. "Si la indicación no se formaliza, el control no existe. En 30 notas de prueba, el 90% se
  resolvió solo y el 100% quedó visible."
- **Qué cambió en el corte** con Hoy en 20-09-2026 y "Ver todas las especialidades": "Entre el 07-09-2026 y el 14-09-2026: 3 pacientes entraron al carril rápido…".

---

# Preguntas probables del jurado

**¿Por qué no en tiempo real?**
Lo pidió el hospital: las 72 horas son el plazo para agendar a cada persona, y si la lista cambia a diario nadie
tiene una posición fija. El cálculo es instantáneo (35 ms por especialidad con ~27.000 pacientes); lo que se
decide es cuándo se publica. Los eventos graves no esperan: llegan como alerta al día siguiente y se pueden
adelantar. En la simulación, la semana cuesta 1 día de mediana y deja la lista quieta la mitad de los días.

**Ustedes ya probaron un score y no funcionó. ¿Qué cambia?**
Ese score tenía pesos arbitrarios y nadie lo validó con especialistas. Este es un modelo multicriterio (MCDA)
lexicográfico: los criterios van en orden y cada uno sale de una fuente publicada o del propio registro, sin pesos
inventados. Lo que depende de cada enfermedad (qué evento es pertinente a qué derivación) es una tabla que valida
cada jefe de especialidad, y la concordancia la mide un especialista distinto del que priorizó, con muestra ciega.

**¿Cualquier urgencia sube a alguien?**
No. Si el evento trae diagnóstico, solo cuenta si tiene que ver con la derivación: una urgencia por esguince no
mueve a quien espera cardiología; una descompensación respiratoria de un cardiópata, sí. La UCI cuenta siempre.

**¿Funciona en otros servicios, que no tienen BIAU?**
Sí. No dependemos del BIAU (solo existe en el Sur Oriente y se abre persona a persona). La entrada son los
reportes en tablas que cualquier ficha exporta (`FORMATO_ENTRADA.md`); cada fuente es un adaptador. Con la Ley
21.668 de interoperabilidad, el paso siguiente es leer HL7 FHIR con un adaptador más.

**¿Y si el paciente ya tiene hora?**
Sale del orden apenas se agenda (no se le quita el cupo ni se le mueve) y vuelve si no llega.

**¿Por qué LACE y no pesos propios? ¿Y la cirugía?**
Porque sus puntos ya están publicados y validados (muerte o reingreso a 30 días, van Walraven 2010): no hay nada
que calibrar. Usa justo lo que nombró el hospital: días cama, ingreso urgente, comorbilidad y consultas de
urgencia. La cirugía no suma en LACE; el puntaje HOSPITAL (Donzé 2013) sí la incluye, y el orden del carril se
cambia en la configuración. La UCI va primero por nivel de cuidado (Lone 2016: más mortalidad a 5 años que
otros hospitalizados).

**¿Por qué una regla y no machine learning?**
Probamos aprender pesos de los desenlaces: predice mejor (AUC 0,75 contra 0,62), pero los pesos son absurdos,
por ejemplo la hospitalización con peso negativo. Predecir el próximo evento no es lo mismo que necesitar al
especialista (Obermeyer 2019). El ML lo usamos donde sirve: el riesgo de no llegar a la cita.

**¿Quién validó clínicamente la regla?**
No necesita pesos clínicos. Los 6 pacientes de ejemplo del hospital y lo que dijeron en las entrevistas
("no por orden de llegada", "un evento entre cortes no mueve la lista", "UCI antes que urgencia") son tests de
aceptación y pasan (`tests/test_entrevistas.py`). La concordancia (κ) la mide un médico distinto del que
priorizó, con una muestra ciega.

**El 90% ¿no es circular?**
En parte sí: el carril adelanta justo a quien tuvo un evento grave, así que mide que se cumple el KPI de
reacción. La cifra menos directa: eventos graves ocurridos mientras seguían en lista, de 99 a 69. Y suponemos
que atender antes no evita eventos, lo que es conservador.

**Son datos sintéticos.**
Sí. La muestra del hospital trae la estructura de Tálamo, y las otras fuentes (hospitalización con días y tipo de
cama, urgencias, ACG, APS, interconsultas sin priorizar) las fabricamos con semilla fija para mostrar cómo se
unen. Las cifras muestran el mecanismo, no el impacto real. Con los reportes reales: `validar_datos.py` y se
vuelve a correr todo igual.

**¿Cómo se unen las fuentes?**
Cada reporte tiene su adaptador. Si el hecho ya está (misma persona, mismo tipo, misma fecha), lo completa; si
no, lo agrega. Así una hospitalización que llega por Tálamo y por una alerta del Servicio cuenta una vez. Se unen
por un seudónimo del RUT con sal secreta.

**¿Escala?**
~27.000 pacientes en 49 especialidades: la lista completa en 1,7 s y un evento en 35 ms. Todo se configura por
especialidad.

**¿Qué pasa si Bedrock falla o no está?**
La lista vigente sale de la regla y funciona igual. La propuesta de la IA es una capa encima: si una llamada
falla, ese paciente queda con la regla y marcado para revisar (en la corrida real: 0 errores en 423). Cada
respuesta queda en una caché con huella del dato y de la rúbrica: la misma entrada da la misma propuesta y se
puede auditar después sin volver a pagar.

**¿Equidad?**
Medir necesidad por uso de servicios puede desfavorecer a quien accede menos. Las comunas rurales se atienden
algo menos en la simulación (25,6% contra 30,2%) y los mayores de 65 oscilan en el umbral. Por eso la auditoría
por grupo es parte del producto, y quien lleva 180 días sin datos queda para llamar.

**¿Y el box?**
El hospital nos dijo que la eficiencia del box va por otro carril. Lo dejamos como complemento: la lista vigente
se convierte en a quién llamar con 72 horas, con reserva para cancelaciones. Hallazgo: con atenciones de 33 a 43
minutos, los bloques de 12 cupos de 25 minutos están sobreagendados.

**¿Privacidad?**
Los datos quedan en la cuenta AWS del hospital, con S3 cifrado. A Bedrock solo va el ID seudonimizado y hechos
codificados; del texto libre se borran RUT, teléfonos y correos. Retención de Bedrock en `none`. Preparado para
la Ley 21.719, vigente desde diciembre de 2026.

**¿Cuánto cuesta en AWS?**
Pago por uso. La corrida real del agente sobre los 423 pacientes en lista usó 927.417 tokens de entrada y 130.587
de salida con Claude Haiku 4.5 (perfil de inferencia de EE. UU.: US$ 1,10 y US$ 5,50 por millón): unos
**US$ 1,74**, menos de medio centavo de dólar por paciente. Con la caché solo se vuelve a evaluar a quien tuvo
datos nuevos en la semana. El resto: dos Lambdas (la diaria corre una vez al día), un bucket S3 y la interfaz.

---

# Preguntas sobre el agente IA

**¿Cómo saben que la IA prioriza bien, si los datos son sintéticos?**
Porque fabricamos pacientes con una verdad que el agente nunca ve (riesgo real a 90 días), en tres conjuntos
separados: entrenamiento, validación y prueba. La prueba tiene otros parámetros y otra forma de redactar las
notas. En 118 pacientes de prueba, de 23 que empeoraron la IA subió a 22 (intervalo de confianza 95%: 79% a
99%); la regla, a 19; las palabras clave, a 11. Ninguno de los 29 que debían ser alta quedó en baja. La cifra
que importa para el hospital viene después: la concordancia con sus especialistas, con muestra ciega
(`validar_concordancia.py`).

**¿No es que la IA memorizó los casos?**
Tres resguardos. El agente clínico solo ve la ficha observable, nunca la verdad. El regulador ve errores de
entrenamiento, y sus reglas pasan por un filtro que rechaza identificadores, fechas y frases copiadas de las notas.
Una regla solo se acepta si mejora en validación, y la prueba se mide una sola vez. En la corrida real el
regulador propuso dos reglas, bajaban la validación de 0,749 a 0,734 y no se aceptaron. Medimos en dos muestras
de prueba distintas y dio lo mismo: 20 de 21 y 22 de 23.

**¿Por qué no entrenar (fine-tuning) un modelo?**
Porque ajustamos instrucciones, no pesos: la rúbrica es un documento versionado que un médico puede leer,
corregir y firmar. No hay datos de pacientes dentro de un modelo y cambiar de modelo en Bedrock es cambiar una
variable.

**¿Y si la IA se equivoca o inventa?**
Cada propuesta trae la evidencia con fecha y fuente, y lo que descartó. La salida es JSON validado contra un
esquema. La regla pone el piso: los 8 pacientes del carril rápido siguen en alta pase lo que pase (la IA también
los puso en alta, 8 de 8). Subir lo propone la IA; bajar lo confirma el jefe; todo se revierte y queda en el
registro. Y en pertinencia coincide con la regla: de 21 eventos no relacionados con la derivación (un cólico
renal en quien espera traumatología), declaró como descartados los 21.

**La IA propone bajar a muchos (166 de 423). ¿No es peligroso?**
No se aplica sola. La prioridad que puso el especialista al derivar tiene información que no está en los
registros, y no tener datos no es estar bien (por eso quien lleva 180 días sin datos queda para llamar). Esas
propuestas van al jefe, primero las de confianza alta (62). En la prueba la tendencia fue la contraria: subió
de más (25 de 95 que no empeoraron, contra 36 de 95 de la regla).

**¿Dónde está AWS en todo esto?**
Amazon Bedrock (Converse API con salida JSON validada; Claude Haiku 4.5 para evaluar a cada paciente y Claude
Sonnet 4.5 como regulador), Amazon S3 (rúbricas, resultados y datos sin la verdad, en
`s3://hlf-priorizacion-ia-<cuenta>/ia/`), y para producción Lambda con EventBridge Scheduler para el corte de
los lunes (`infra/template.yaml`).
