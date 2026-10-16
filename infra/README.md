# Despliegue en AWS (prototipo)

> Estos archivos no se probaron contra una cuenta de AWS real. La plantilla pasa `cfn-lint`. La Lambda de
> recálculo se probó localmente con eventos de EventBridge y de HTTP API, y la de carga diaria contra un S3
> simulado (moto) en `tests/test_diario.py`.

## Qué se despliega

```
Recálculo por evento (en el momento):
  Ficha / urgencia ──► EventBridge (source: hlf.registro-clinico) ─┐
  App o integración ──► HTTP API POST /evento ─────────────────────┴─► Lambda recálculo (api/handler.py)

Carga diaria (el hospital trabaja con reportes diarios, carpeta Polo):
  Reporte del día (CSV) ──► s3://<bucket>/reportes/AAAA-MM-DD/
  07:00 lunes a viernes, hora de Chile (EventBridge Scheduler) ──► Lambda carga diaria (api/diario.py)
      ├─ incorpora el reporte al almacén  s3://<bucket>/almacen/
      ├─ recalcula la lista y la compara con la carga anterior
      ├─ deja salidas/cambios_<fecha>.csv y salidas/resumen_<fecha>.txt (resumen redactado por Bedrock)
      └─ corte semanal: el lunes publica cortes/<fecha>/lista_vigente.csv (la lista con que se agenda la
         semana); martes a viernes deja salidas/alertas_<fecha>.csv (eventos graves desde el corte, con su
         puesto proyectado), sin mover la lista vigente
  El reporte puede traer también los de otras fuentes (talamo_hospitalizaciones.csv, talamo_urgencias.csv,
  acg_estratificacion.csv, rayen_diagnosticos_cronicos.csv, interconsultas.csv): van a almacen/fuentes/.
```

- `template.yaml`: plantilla SAM con las dos Lambdas (misma imagen), la regla de EventBridge, la HTTP API,
  el bucket de reportes (cifrado y sin acceso público) y la programación diaria.
- `Dockerfile.lambda`: imagen de la Lambda. Lleva el código del motor y, para el prototipo, el dataset.
- `Dockerfile.app`: imagen de la interfaz Streamlit, para App Runner, ECS o una EC2.
- `evento_ejemplo.json`: un evento para enviar con `aws events put-events`.

## Pasos

1. **Habilitar el modelo en Bedrock** (consola de Bedrock → acceso a modelos) en la región que usarán.
   Anotar el id del modelo o del inference profile.
2. **Desplegar la Lambda** (requiere AWS SAM CLI y Docker):
   ```bash
   cd infra
   sam build
   sam deploy --guided            # pide región, nombre del stack y el parámetro BedrockModelId
   ```
3. **Probar con un evento**:
   ```bash
   aws events put-events --entries file://evento_ejemplo.json
   # o por HTTP:
   curl -X POST "$URL_API" -H "Content-Type: application/json" \
     -d '{"id_paciente":"PAC-HLF-00136","corte":"2026-10-13","evento":{"fecha_evento":"2026-10-13","tipo_evento":"hospitalizacion","subtipo":"ingreso hospitalario","severidad":"grave"}}'
   ```
   La respuesta trae el puesto antes y después, el motivo y la explicación.
   Los logs quedan en CloudWatch (`sam logs --stack-name <stack> --tail`).
4. **Carga diaria**: subir el reporte del día y esperar a las 07:00, o invocarla a mano:
   ```bash
   aws s3 cp reporte_2026-10-14/ s3://$BUCKET/reportes/2026-10-14/ --recursive
   aws lambda invoke --function-name <CargaDiariaFunction> --payload '{"fecha":"2026-10-14"}' \
     --cli-binary-format raw-in-base64-out salida.json
   aws s3 cp s3://$BUCKET/salidas/resumen_2026-10-14.txt -
   ```
5. **Interfaz**: construir `Dockerfile.app` y publicarla en App Runner (puerto 8501), con las variables
   `BEDROCK_MODEL_ID` y `AWS_REGION`, `HLF_CLAVE` como secreto (pide clave de acceso) y un rol con
   permiso `bedrock:InvokeModel`.
6. **Retención en Bedrock**: en la configuración de Bedrock de la región, dejar el modo de retención de
   datos en `none` para que no se guarden pedidos ni respuestas.

## Límites del prototipo (decirlos si preguntan)

- La Lambda de recálculo guarda los eventos en memoria mientras la instancia vive; la carga diaria sí
  persiste en S3. Paso siguiente: que el recálculo lea el almacén de S3 y escriba en DynamoDB.
- El almacén en S3 son archivos CSV: suficiente para un hospital (decenas de miles de filas). Si crece,
  pasar a Parquet o a una base de datos.
- El permiso de Bedrock está abierto a cualquier modelo (`Resource: "*"`). En producción hay que
  restringirlo al ARN del modelo usado.
- La HTTP API no tiene autenticación. En producción: autorizador IAM o Cognito.
