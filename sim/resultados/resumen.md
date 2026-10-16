# Resultados de la simulación (14-04-2026 al 13-10-2026)

Datos sintéticos del desafío. Contrafactual simplificado: ver supuestos en sim/simulador.py.


## Capacidad: cada especialidad atiende al 15% de sus pacientes en el período

Cohorte con evento grave durante la espera: 61 pacientes.

| Métrica | Regla actual | Actual + carril rápido | MVP: carril rápido + plazo dinámico + 10% por antigüedad | Puntaje v1 (pesos a mano) |
|---|---|---|---|---|
| % atendidos ≤30 días tras su primer evento grave | 9.8 | 72.1 | 57.4 | 50.8 |
| Mediana de días entre evento grave y atención | 59 | 18 | 25 | 25.5 |
| Eventos graves ocurridos estando en lista | 114 | 93 | 99 | 109 |
| Pacientes 'baja' atendidos | 0 | 11 | 17 | 4 |
| Pacientes que siguen esperando > 365 días | 156 | 158 | 156 | 156 |
| % atendido, NSE bajo | 13.7 | 15.5 | 14.9 | 17.9 |
| % atendido, comunas rurales | 18.6 | 11.6 | 9.3 | 14 |

Si la regla actual no detecta defunciones, entregaría **4 cupos a pacientes fallecidos**.


## Capacidad: cada especialidad atiende al 25% de sus pacientes en el período

Cohorte con evento grave durante la espera: 61 pacientes.

| Métrica | Regla actual | Actual + carril rápido | MVP: carril rápido + plazo dinámico + 10% por antigüedad | Puntaje v1 (pesos a mano) |
|---|---|---|---|---|
| % atendidos ≤30 días tras su primer evento grave | 3.3 | 85.2 | 90.2 | 72.1 |
| Mediana de días entre evento grave y atención | 67 | 5 | 8 | 17 |
| Eventos graves ocurridos estando en lista | 99 | 55 | 69 | 92 |
| Pacientes 'baja' atendidos | 0 | 18 | 25 | 15 |
| Pacientes que siguen esperando > 365 días | 128 | 142 | 124 | 125 |
| % atendido, NSE bajo | 25.6 | 23.2 | 26.2 | 26.2 |
| % atendido, comunas rurales | 30.2 | 23.3 | 25.6 | 23.3 |

Si la regla actual no detecta defunciones, entregaría **3 cupos a pacientes fallecidos**.


## Capacidad: cada especialidad atiende al 40% de sus pacientes en el período

Cohorte con evento grave durante la espera: 61 pacientes.

| Métrica | Regla actual | Actual + carril rápido | MVP: carril rápido + plazo dinámico + 10% por antigüedad | Puntaje v1 (pesos a mano) |
|---|---|---|---|---|
| % atendidos ≤30 días tras su primer evento grave | 3.3 | 78.7 | 85.2 | 77 |
| Mediana de días entre evento grave y atención | 55 | 4 | 4 | 10.5 |
| Eventos graves ocurridos estando en lista | 95 | 45 | 52 | 78 |
| Pacientes 'baja' atendidos | 0 | 19 | 36 | 23 |
| Pacientes que siguen esperando > 365 días | 76 | 90 | 65 | 90 |
| % atendido, NSE bajo | 43.5 | 41.1 | 41.7 | 41.1 |
| % atendido, comunas rurales | 48.8 | 39.5 | 34.9 | 32.6 |

Si la regla actual no detecta defunciones, entregaría **7 cupos a pacientes fallecidos**.

