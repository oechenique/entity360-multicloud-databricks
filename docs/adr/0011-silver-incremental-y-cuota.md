# ADR 0011 — Silver incremental por la cuota diaria de cómputo de Free Edition

- **Estado:** aceptado (2026-09-29). Código listo; validación en el workspace pendiente
  (`databricks/evidencia/silver-incremental-validacion.md`).
- **Relacionado:** ADR 0004 (medallion en PySpark), D6 (idempotencia en tres capas).

## Contexto
Free Edition tiene una cuota diaria de cómputo serverless. El 2026-09-29, después de un día con varias
corridas de la resolución, `dbt build`, validación del dashboard, pruebas de Genie y una corrida del DAG,
el SQL warehouse dejó de arrancar (`Cannot create the resource, please try again later`): no corría ni
dbt, ni el dashboard, ni Genie. Silver recalculaba todo Bronze en cada corrida aunque no llegara nada
nuevo (5 min por corrida, la tarea que más consumía; `databricks/evidencia/pasos1-3-primeras-corridas.txt`).

## Decisión
- Silver procesa **solo los lotes de Bronze que no procesó**: `silver._lotes_procesados` guarda el sha256
  de cada lote por fuente; una fuente sin lotes nuevos no se toca.
- Capa 3 incremental: el registro de un lote nuevo reemplaza al de Silver solo si no es más viejo, con el
  mismo orden que el recálculo completo. Las tablas de nombres se reemplazan por padre.
- SCD2 de GLEIF sin cambios: ya aplicaba los cambios nuevos sobre la última versión.
- La lógica de decisión vive en `incremental.py` (puro) con tests de equivalencia contra el recálculo
  completo.

## Consecuencias
- Un día sin lotes nuevos cuesta casi nada en Silver; el consumo sigue a los datos, no al calendario.
- Vaciar `silver._lotes_procesados` de una fuente fuerza su reproceso completo (así migra la primera
  corrida).
- La cuota queda como restricción del proyecto: el trabajo que usa el warehouse se agrupa.
