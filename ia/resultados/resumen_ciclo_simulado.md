# Ciclo de mejora de la rúbrica (simulado)

Versión final: v0.

## Bitácora (DEV)

|   iteracion | version   | aceptada   |   dev_objetivo |   dev_sens_deterioro |   dev_ndcg10 |   dev_kappa | cambios                                                                                                          | rechazos       |
|------------:|:----------|:-----------|---------------:|---------------------:|-------------:|------------:|:-----------------------------------------------------------------------------------------------------------------|:---------------|
|           0 | v0        | True       |          0.759 |                0.905 |        0.812 |       0.559 |                                                                                                                  |                |
|           1 | v0        | False      |          0.759 |                0.905 |        0.812 |       0.559 | Regla: dos o más notas seguidas que describen empeoramiento equivalen a deterioro claro, aunque no haya eventos. |                |
|           2 | v0        | False      |          0.759 |                0.905 |        0.812 |       0.559 | Regla: una medición fuera de rango y en alza en las últimas tres tomas indica descompensación (al menos media).  |                |
|           3 | v0        | False      |          0.759 |                0.905 |        0.812 |       0.559 |                                                                                                                  | sin propuestas |

## Medición final en TEST (una sola vez, los mismos 296 pacientes para todos los métodos)

| metodo   |   n |   kappa |   sens_deterioro |   falsas_alarmas |   subtriage_alta |   ndcg10 |   kendall |   recall_top10 |   objetivo |
|:---------|----:|--------:|-----------------:|-----------------:|-----------------:|---------:|----------:|---------------:|-----------:|
| fifo     | 296 |   0.307 |             0    |            0     |            0.194 |    0.647 |     0.237 |          0.286 |      0.318 |
| regla    | 296 |   0.257 |             0.8  |            0.354 |            0.032 |    0.657 |     0.25  |          0.276 |      0.571 |
| ia       | 296 |   0.455 |             0.44 |            0.089 |            0.387 |    0.724 |     0.49  |          0.276 |      0.54  |
| hibrido  | 296 |   0.357 |             0.44 |            0.089 |            0.129 |    0.716 |     0.442 |          0.276 |      0.504 |

En números absolutos:

| metodo   |   n |   empeoraron |   detectados |   no_empeoraron |   falsas_alarmas |   debian_ser_alta |   quedaron_en_baja |
|:---------|----:|-------------:|-------------:|----------------:|-----------------:|------------------:|-------------------:|
| fifo     | 296 |           50 |            0 |             246 |                0 |                62 |                 12 |
| regla    | 296 |           50 |           40 |             246 |               87 |                62 |                  2 |
| ia       | 296 |           50 |           22 |             246 |               22 |                62 |                 24 |
| hibrido  | 296 |           50 |           22 |             246 |               22 |                62 |                  8 |
