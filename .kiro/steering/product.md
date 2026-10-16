---
inclusion: always
---
# Producto

Herramienta para el equipo de gestión de la demanda del Hospital Clínico Dra. Eloísa Díaz La Florida (HLF).

- Problema: la lista de espera de cada especialidad es estática. El especialista asigna alta/media/baja al recibir
  la interconsulta y después se avanza por orden de llegada. Si el paciente empeora (urgencia, hospitalización, o un
  CESFAM que lo reevalúa y pide adelantar), la lista no se entera. Dentro de "alta" todos son iguales.
- Objetivo: reclasificar (subir de grupo) y ordenar dentro de cada grupo según la evolución del paciente, con
  evidencia trazable, para que la gestora agende primero a quien más lo necesita.
- Usuarios: gestora de demanda (agenda) y jefe de especialidad (revisa, pide ver antes). El paciente no ve la lista.
- Lo que pidió el hospital: repriorizar un día fijo a la semana (lunes) y alertas diarias entre cortes; ver por qué
  cada paciente está donde está y cómo cambió; no mover por eventos que no tienen que ver con la derivación; validar
  con un especialista distinto del que priorizó (meta κ ≥ 0,70).
- Principio: la IA propone con evidencia; la regla pone un piso de seguridad; el equipo decide y queda registrado.
- Dirección del producto: "pulso." (ver `web/` y el mockup del equipo): el contexto de cada persona en el momento de
  decidir. Resumen del hospital (P90, especialidades, lo que cambió), lista con posición y motivo, ficha con por qué,
  evolución, antecedentes con fuente y fecha, bandeja de ingresos antes del corte, y el agente IA con sus decisiones.
