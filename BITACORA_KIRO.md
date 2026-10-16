# Bitácora Kiro — hackatón HLF

Zona horaria: hora de Chile. Ventana de desarrollo continuo: hasta las 02:15 (acortada desde 09:30).

## 2026-10-16 01:15 — Preparación
- Leídos AGENTS.md, README.md, PLAN_AGENTE_IA.md (vía K1–K6 previos), DEMO.md y .kiro/steering/*.md.
- Respaldo: `git init` + commit `base` (ab7d0c2). `.gitignore` ya excluía credenciales/cache; agregué `.venv/`.
  Verificado que `credenciales_aws.ps1` y `.venv/` NO entraron al repo.
- Creados BACKLOG.md (P1–P6) y esta bitácora.
- Estado base: `python -m pytest -q` → 134 passed (verificado en el setup previo). Proyecto en
  `C:\Users\Usuario\Downloads\hlf-priorizacion`.
- Recursos AWS existentes de sesiones previas: bucket `hlf-priorizacion-ia-904433306629` (datos/resultados IA).
- Costo acumulado estimado: ~US$ 1,74 (corrida del agente sobre 423 pacientes, ya hecha; reproducible desde caché).

SIGO: P1 (publicar el front web/ en AWS)

## 2026-10-16 01:35 — P1: front publicado en AWS
- Qué: `python -m web.construir` (datos.js con 423 pacientes) y despliegue idempotente del front.
- Archivos nuevos: `infra/desplegar_web.py` (S3 privado + CloudFront OAC, sube 4 archivos con Content-Type,
  invalida caché), `infra/desplegar_web_lambda.py` (fallback Lambda Function URL), `infra/__init__.py`.
  Docs: README.md y DEMO.md con la URL.
- Verificación: `python -m pytest -q` → 134 passed. Bucket con acceso público bloqueado (verificado).
  CloudFront status InProgress (propaga ~10-15 min); los 4 objetos están en el bucket. URL por DNS aún propagando.
- Recursos AWS creados:
  - S3 `hlf-priorizacion-web-904433306629` (bucket privado, tag proyecto=hlf-priorizacion) — hospeda el front.
  - CloudFront `E2276ADQM8SNAX` (dominio da8n28k4fli3t.cloudfront.net) — sirve el front por HTTPS con OAC.
  - CloudFront Origin Access Control `hlf-priorizacion-web-oac`.
- Costo estimado: CloudFront/S3 por este volumen y tráfico de demo ≈ US$ 0 (free tier) a centavos.
- Pendiente de P1: confirmar la URL por HTTP cuando termine de propagar (reintentar antes del congelado).

SIGO: P2 (repetir el ciclo regulador K3b en un subagente)
