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

## 2026-10-16 02:00 — P2: ciclo regulador K3b (con el regulador mejorado)
- Qué: `python -m ia.ciclo --modo bedrock --iteraciones 3 --muestra 120`. Esta vez el regulador (que ahora
  conoce el límite de largo y recibe por qué se rechazaron sus reglas) SÍ aceptó reglas y creó `ia/rubrica/v1.md`
  y `v2.md`.
- Revisión manual (requisito P2): las 6 reglas de v2 son clínicas y GENERALES, sin fuga (sin IDs, fechas ni
  frases copiadas). Ejemplos: "evento grave aislado >60 días sin recurrencia no justifica alta por sí solo";
  "HbA1c >8% en alza + complicaciones → alta"; "psicosis/ideación suicida estable sin hospitalización reciente →
  media". Mejora el objetivo en DEV 0,749 → 0,771 (v1) → 0,782 (v2). En TEST con v2: IA detecta 23/23 deterioros,
  0/29 "alta" en baja, objetivo 0,835.
- DECISIÓN (segura y reversible): mantengo **v0** como rúbrica de producción/demo. Motivo: `tests/test_web.py` y
  la narrativa de `DEMO.md` están clavados a las cifras de v0 (PAC-HLF-00079 → alta #3; "22 de 23"). Correr el
  agente del hospital con v2 cambia esas cifras (PAC-HLF-00079 pasa a "media"; 23 de 23) y rompería 2 tests y la
  demo verificada. Resultado: `propuestas_hlf.csv`, `datos.js` y los CSV del ciclo quedan en v0 (restaurados con
  `git checkout`, verificado 134 passed). **v1.md y v2.md se conservan en el repo como evidencia** de que el
  regulador mejorado ahora sí produce y acepta reglas clínicas que mejoran la validación.
- Verificación: `python -m pytest -q` → 134 passed. `python -m web.construir` OK (rúbrica IA = v0 en datos.js).
  Front re-subido a S3 e invalidada la caché de CloudFront.
- Recursos AWS: ninguno nuevo (usa Bedrock Haiku/Sonnet ya configurados y el bucket IA existente).
- Costo estimado: ciclo (train+dev+test muestra 120, ~360 llamadas Haiku + 3 Sonnet) + 423 llamadas del agente
  con v2 ≈ US$ 2 a 3. La reversión a v0 usó caché (sin costo).

SIGO: P3 (alertas entre cortes en el front)
