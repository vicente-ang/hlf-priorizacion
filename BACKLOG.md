# Backlog — modo desarrollo continuo (hackatón HLF)

Orden de ejecución. Marcar `[x]` al terminar y verificar (`python -m pytest -q`; si cambia front/datos, `python -m web.construir`).

- [x] **P1. Publicar el front `web/` en AWS**
  - Script idempotente `infra/desplegar_web.py` (boto3): bucket S3 **privado** `hlf-priorizacion-web-<cuenta>`,
    CloudFront con Origin Access Control, sube `index.html`, `estilos.css`, `app.js`, `datos.js` con su
    Content-Type, invalida la caché al re-subir.
  - Alternativa si CloudFront no está permitido: Lambda con URL que sirva esos 4 archivos.
  - Aceptación: la URL muestra los 423 pacientes. Anotarla en `README.md` y `DEMO.md`.
- [x] **P2. Repetir el ciclo regulador (K3b)** en un subagente
  - `. .\entorno.ps1; python -m ia.ciclo --modo bedrock --iteraciones 3 --muestra 120 | Out-File -Encoding utf8 ciclo.txt`
  - Si aparece `ia/rubrica/v1.md`: revisar que la regla sea clínica y general; correr el agente sobre
    `data/dataset_hlf_ambulatorio` con esa rúbrica; luego `python -m web.construir`.
- [ ] **P3. Alertas entre cortes en el front**
  - `web/construir.py` exporta `motor.cortes.alertas_desde_corte` con el puesto proyectado de cada paciente.
  - Nueva página "Alertas" con el diseño del mockup.
  - Test en `tests/test_web.py` con `--hoy 2026-10-16`.
- [ ] **P4. Lambda del corte del lunes**
  - Regenera `datos.js` en el bucket de P1. EventBridge Scheduler `cron(0 7 ? * MON *)`, zona America/Santiago.
  - Sin Docker: capa administrada AWSSDKPandas para Python 3.12, y PyYAML dentro del zip.
  - Si no se permite crear el rol IAM, documentar el bloqueo y seguir.
- [ ] **P5. Explicaciones redactadas por Bedrock (Claude Haiku 4.5)** para los 10 primeros de cada especialidad
  - Se guardan en `ia/resultados/explicaciones_hlf.csv` y se muestran en la ficha.
  - Sin red, el front muestra la explicación de la regla. Usa la caché. Costo < US$ 0,50.
- [ ] **P6. Pulir la demo**
  - Revisar el front a 1280 px y a 390 px. Gráfico `salidas/graficos/ia_test.png` con la tabla de TEST.
  - Recorrer `DEMO.md` sobre la URL de P1 y corregir cifras que no coincidan.

## Reglas que mandan (de AGENTS.md y steering)
- No modificar `ia/mundo.py`, `ia/rubrica/v0.md` ni `data/mundo/*_verdad`.
- Tests siempre en verde (nunca debilitarlos). Español de Chile en pantalla.
- AWS: solo recursos `hlf-...` con etiqueta `proyecto=hlf-priorizacion`; región us-east-1; no tocar buckets
  `pulso-*` (de otros); sin usuarios IAM ni claves nuevas; sin buckets públicos; presupuesto ~US$ 15.
- PowerShell 5: `| Out-File -Encoding utf8`, `robocopy /E` (nunca `Copy-Item -Recurse` sobre carpeta existente ni `/MIR`).
