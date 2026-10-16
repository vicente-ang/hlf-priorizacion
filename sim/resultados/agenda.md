# Uso del box: simulación de políticas de agenda

2.188 bloques del 14-04-2026 al 13-10-2026 (21.868 cupos). 300 repeticiones cada uno. Datos sintéticos; supuestos en sim/agenda_sim.py.

| Política | Atendidos por 100 cupos | Atendidos extra en 6 meses | Sobretiempo medio por bloque | Bloques con > 30 min de sobretiempo | Minutos ociosos por bloque |
|---|---|---|---|---|---|
| A) Actual: citar la capacidad | 73,8 | 0 | 20,0 min | 22,6% | 49 min |
| B) + llamada a riesgo alto | 74,5 | +153 | 20,7 min | 23,3% | 47 min |
| C) + llamada + lista de reserva | 79,6 | +1.268 | 28,2 min | 30,7% | 36 min |
| D) + llamada + reserva + sobrecupo fijo (+2) | 95,5 | +4.745 | 64,2 min | 57,4% | 14 min |
| E) + llamada + reserva + sobrecupo con tope de sobretiempo | 82,8 | +1.968 | 30,2 min | 33,5% | 27 min |

Bloques sobreagendados para las duraciones reales de atención (caben menos citas que cupos):

- Broncopulmonar, bloques de 10 cupos: caben 9 citas sin pasarse más de 30 min (atención media 37 min, cupos de 30 min)
- Broncopulmonar, bloques de 12 cupos: caben 9 citas sin pasarse más de 30 min (atención media 37 min, cupos de 25 min)
- Cardiología, bloques de 12 cupos: caben 10 citas sin pasarse más de 30 min (atención media 34 min, cupos de 25 min)
- Endocrinología, bloques de 12 cupos: caben 10 citas sin pasarse más de 30 min (atención media 33 min, cupos de 25 min)
- Gastroenterología, bloques de 8 cupos: caben 7 citas sin pasarse más de 30 min (atención media 43 min, cupos de 38 min)
- Gastroenterología, bloques de 10 cupos: caben 7 citas sin pasarse más de 30 min (atención media 43 min, cupos de 30 min)
- Gastroenterología, bloques de 12 cupos: caben 7 citas sin pasarse más de 30 min (atención media 43 min, cupos de 25 min)
- Neurología, bloques de 10 cupos: caben 9 citas sin pasarse más de 30 min (atención media 38 min, cupos de 30 min)
- Neurología, bloques de 12 cupos: caben 9 citas sin pasarse más de 30 min (atención media 38 min, cupos de 25 min)
- Salud Mental, bloques de 10 cupos: caben 9 citas sin pasarse más de 30 min (atención media 37 min, cupos de 30 min)
- Salud Mental, bloques de 12 cupos: caben 9 citas sin pasarse más de 30 min (atención media 37 min, cupos de 25 min)
- Traumatología, bloques de 12 cupos: caben 10 citas sin pasarse más de 30 min (atención media 34 min, cupos de 25 min)
