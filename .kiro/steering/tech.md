---
inclusion: always
---
# Tecnología

- Python 3.12+ (el equipo usa 3.14 en Windows), pandas, scipy, PyYAML, Streamlit (interfaz), pytest, boto3 (Bedrock,
  S3), moto (S3 simulado en tests). En Windows la terminal es PowerShell 5: ver la sección Windows de `AGENTS.md`.
- Amazon Bedrock con la Converse API. Salida estructurada con `outputConfig.textFormat` (JSON Schema); respaldo con
  tool use `strict` y luego JSON en texto (ver `ia/bedrock.py`). Temperatura 0. Caché en `ia/cache/`.
- Modelos en uso (probados el 15-10-2026, us-east-1): agente `us.anthropic.claude-haiku-4-5-20251001-v1:0`
  (`BEDROCK_MODEL_ID`), regulador `us.anthropic.claude-sonnet-4-5-20250929-v1:0` (`BEDROCK_MODEL_ID_REGULADOR`).
  `entorno.ps1` los deja definidos. Cambiar de modelo invalida la caché (se vuelve a pagar).
- AWS: S3 (datos, propuestas, versiones de rúbrica), Lambda en imagen de contenedor (`infra/Dockerfile.lambda`),
  EventBridge Scheduler (lunes 7:00 corte), App Runner para la interfaz. Plantilla SAM en `infra/template.yaml`.
- Tests: `python -m pytest -q` (no requieren red; Bedrock se prueba con `botocore.stub.Stubber`).
- Estilo: funciones cortas con docstring en español; nada de pesos clínicos inventados en código (van en YAML o en la rúbrica).
