# Prueba de escala

Pacientes: **27.242** (el HLF tiene 26.356 en lista) · especialidades: **49**

| Operación | Tiempo |
|---|---|
| Cargar datos y replicar | 0,3 s |
| Priorizar la lista completa (49 especialidades) | 1,7 s |
| Llega un evento y se reordena su especialidad (~648 pacientes) | 35 ms |

Medido en un solo núcleo, sin paralelizar ni cachear. Meta del hospital: reevaluar en < 72 horas.
