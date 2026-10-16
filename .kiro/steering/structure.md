---
inclusion: always
---
# Estructura

- `motor/` regla determinista: `priorizacion.py` (evaluar_paciente, priorizar), `clusters.py` (LACE, Charlson),
  `pertinencia.py`, `cortes.py` (corte semanal, alertas, adelantos, historial), `config/regla.yaml`.
- `ia/` agente con IA generativa:
  - `mundo.py` mundo sintético con verdad conocida (train/dev/test). La verdad va en `data/mundo/<c>_verdad/`.
  - `agente.py` ficha del paciente + evaluación por paciente (Bedrock o simulado) + híbrido con la regla + orden.
  - `bedrock.py` cliente Converse con JSON validado, reintentos y caché.
  - `evaluar.py` métricas (κ, sensibilidad de deterioro, NDCG@10, τ de Kendall, recall top 10%) vs FIFO y regla.
  - `regulador.py` propone reglas generales desde errores de TRAIN + `filtro_fuga`.
  - `ciclo.py` mejora de la rúbrica: acepta solo si mejora en DEV; mide una vez en TEST.
  - `rubrica/vN.md` versiones de la rúbrica. `resultados/` salidas (CSV, resúmenes).
- `web/` **front del producto («pulso.»)**: `index.html` + `estilos.css` (diseño del mockup del equipo) + `app.js`
  (vanilla, sin build) leen `datos.js`, que genera `construir.py` desde el motor y `ia/resultados/`. `servidor.py`
  (biblioteca estándar) sirve el front y guarda decisiones en el registro. Las pantallas nuevas van aquí, con las
  clases del mockup (`panel`, `metric`, `badge`, `explanation-panel`, `history-event`...).
- `app.py` consola Streamlit (alertas, indicaciones, equidad, agenda); `api/` Lambdas; `infra/` despliegue;
  `tests/` pruebas; `PLAN_AGENTE_IA.md` tareas.
