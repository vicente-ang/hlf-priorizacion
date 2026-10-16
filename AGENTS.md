# Instrucciones para agentes de código (Kiro CLI y otros)

Proyecto: priorización dinámica de la lista de espera del Hospital Clínico Dra. Eloísa Díaz La Florida (HLF),
AWS Breaking Barriers 2026. La lista hoy es estática (alta/media/baja + orden de llegada). Queremos que se
reclasifique y se ordene dentro de cada grupo según lo que le pasa al paciente mientras espera.

## Reglas que no se negocian
1. **Idioma**: español de Chile en código visible, interfaz y documentos. Coma decimal y fechas DD-MM-AAAA en pantalla.
2. **Los tests deben pasar**: `python -m pytest -q` antes y después de cada cambio. Cada función nueva lleva su test.
3. **La IA propone, el equipo decide**: el agente clínico puede proponer SUBIR a un paciente; BAJARLO de su prioridad
   inicial (T1) requiere confirmación humana. La regla determinista pone el piso: evento grave relacionado en 30 días
   ⇒ al menos alta. Toda decisión queda en el registro con usuario, motivo y versión de la rúbrica.
4. **Sin fuga de datos**:
   - El agente clínico (`ia/agente.py`) solo ve la ficha observable (`ia.agente.ficha`). NUNCA le pases
     `data/mundo/*_verdad/`, la trayectoria ni la gravedad latente.
   - La rúbrica (`ia/rubrica/`) solo cambia por el ciclo (`ia/ciclo.py`, con `filtro_fuga`) o por personas desde
     fuentes clínicas. **No edites la rúbrica mirando `ia/mundo.py`** (sus parámetros son la "verdad").
   - DEV decide si se acepta un cambio; TEST se mide una sola vez al final.
5. **AWS primero**: Amazon Bedrock (Converse API, salida JSON con esquema), S3, Lambda. Ver `PLAN_AGENTE_IA.md`.
6. **Costos**: usa `--muestra N` mientras pruebas; la caché de Bedrock (`ia/cache/`) evita pagar dos veces.
7. **Privacidad**: el texto que va a Bedrock pasa por `motor.privacidad.anonimizar_texto`. No subas datos reales a
   repositorios públicos.
8. **Credenciales**: las claves temporales del taller viven SOLO en `credenciales_aws.ps1` (lo pidió el equipo; está
   en `.gitignore` y `.dockerignore` y lo carga `entorno.ps1`). No las copies a ningún otro archivo, script, log ni
   documento, y no subas ese archivo a un repositorio.

## Estado (15-10-2026)
K1–K6 hechas con Bedrock real (Claude Haiku 4.5 agente, Sonnet 4.5 regulador, us-east-1) y revisadas. Resultados
en `ia/resultados/` y en `README.md`. Pendientes opcionales: K3b y K7 en `PLAN_AGENTE_IA.md`.

## Windows / PowerShell 5 (lo que aprendimos)
- `python` puede abrir la Microsoft Store: usar `py -3` para crear el entorno; dentro del entorno activado,
  `python` funciona. Activar: `.\.venv\Scripts\Activate.ps1`.
- Variables: `$env:NOMBRE = "valor"` (no `set` ni `export`); encadenar con `;`; `$LASTEXITCODE` para el código.
- `*>` guarda en UTF-16: usar `| Out-File -Encoding utf8 archivo.txt` y leer el archivo después.
- `. .\entorno.ps1` deja listos región, modelos y bucket. Los tests no dependen de eso (`conftest.py` borra las
  variables de AWS en cada test).
- Para fusionar carpetas usa `robocopy <origen> <destino> /E`. Nunca `Copy-Item -Recurse` sobre una carpeta que ya
  existe (en PowerShell 5 dejó el proyecto sin subcarpetas) ni `robocopy /MIR` (borra `.venv` e `ia/cache`).

## Mapa rápido
- `motor/`: regla determinista (carril rápido, plazo dinámico, pertinencia, clusters, cortes semanales). Es la línea
  base y el piso de seguridad.
- `ia/`: agente clínico (Bedrock), regulador, ciclo de mejora, mundo sintético con verdad conocida y métricas.
- `web/`: **front del producto («pulso.»)**, estático; `python -m web.servidor`. Cambios de interfaz van aquí.
- `app.py`: consola Streamlit (lista vigente, alertas, historial por corte, decisiones).
- `api/`, `infra/`: Lambdas y plantilla SAM.
- `data/dataset_hlf_ambulatorio/`: datos del hospital (500 pacientes). `data/mundo/`: mundos sintéticos.
- Tareas pendientes y criterios de aceptación: `PLAN_AGENTE_IA.md`.

## Comandos
```bash
pip install -r requirements.txt
python -m pytest -q
python -m ia.mundo                                   # regenera train/dev/test sintéticos
python -m ia.agente --datos data/mundo/dev --modo bedrock --muestra 5
python -m ia.evaluar --datos data/mundo/dev --propuestas ia/resultados/propuestas_dev_bedrock.csv
python -m ia.ciclo --modo bedrock --iteraciones 3 --muestra 120
python -m ia.ciclo --modo bedrock --solo-informe     # rehace la tabla de TEST sin llamar a Bedrock
python -m ia.s3 subir --bucket <bucket>             # rúbricas, resultados y mundo (sin *_verdad) a S3
python -m web.construir                             # datos del front (web/datos.js)
python -m web.servidor                              # front en http://localhost:8000
streamlit run app.py
```
Variables: `BEDROCK_MODEL_ID`, `BEDROCK_MODEL_ID_REGULADOR` (opcional, modelo más grande), `AWS_REGION`,
`BEDROCK_CONCURRENCIA` (por defecto 6).
