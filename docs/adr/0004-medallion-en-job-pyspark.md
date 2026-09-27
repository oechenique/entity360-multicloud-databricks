# ADR 0004 — Medallion en un job de PySpark explícito, no en Lakeflow Declarative Pipelines

- **Estado:** aceptado (fase 6, 2026-09-27). Decisión de Gastón.
- **Relacionado:** regla 08, regla 03 (idempotencia en tres capas, D6), D11 (set de validación).

## Contexto
Bronze, Silver y la resolución de identidades se pueden construir de dos maneras en Databricks:

1. **Lakeflow Declarative Pipelines** (antes Delta Live Tables): tablas declaradas en SQL o Python,
   con Auto Loader, `AUTO CDC ... STORED AS SCD TYPE 2` y expectations (calidad de datos con
   cuarentena) incluidos.
2. **Un job con tareas de PySpark**: Auto Loader con `Trigger.AvailableNow`, `foreachBatch` y
   `MERGE` escritos a mano.

Lo que el proyecto necesita que se vea y se pueda probar:
- La **capa 2 de idempotencia** (D6): un lote con un `sha256` ya ingerido no suma filas, y un lote
  cuyo manifest todavía no llegó no se ingiere (el micro-batch falla y el reintento lo toma).
- El **SCD2 sobre el CDC del legacy**, ordenado por `(lsn, seqval)`, con `update_antes` descartado
  y `delete` que cierra la versión sin abrir otra.
- La **resolución de identidades**: blocking, score por reglas con la contribución de cada señal,
  clusters con restricciones (nunca dos LEI ni dos CIK distintos) y golden record. No tiene
  equivalente declarativo: es código igual en los dos caminos.
- **Precisión y recall contra el set curado a mano**, con intervalo de Wilson al 95 %.

## Decisión
**Job de PySpark explícito** (`entity360-medallion`, serverless), con tareas `bronze` → `silver` →
`resolucion`, definido en Terraform y con el código en `databricks/`.

## Por qué no Lakeflow Declarative Pipelines
- **La capa 2 quedaría implícita.** Una pipeline deduplica por el estado de su checkpoint, no por el
  `sha256` del manifest. El reenvío de un lote idéntico con otro nombre (el caso que motivó el D6)
  habría que resolverlo igual con código propio, dentro de un marco que no está pensado para eso.
- **Se testea mal fuera de Databricks.** La lógica de negocio (normalización de nombres,
  encadenamiento del SCD2, score, clusters) vive en funciones de Python puro con pytest local, como
  los tests de la fase 4. En una pipeline, las tablas solo existen dentro de un update.
- **`AUTO CDC` resuelve el caso fácil.** Nuestro CDC trae `update_antes`, deletes solo en una tabla,
  varios cambios de la misma clave en un lote y updates sin cambios reales. Escrito a mano, cada
  regla queda a la vista y tiene su test con los cambios reales del 2026-09-26.
- **Límites inciertos en Free Edition.** La cuota diaria de serverless corta el workspace (spike,
  6c). Un job con `AvailableNow` procesa lo pendiente y termina, y su duración se mide igual que
  los minutos de Actions de la fase 4. No hay límites publicados de las pipelines en Free Edition.
- **Menos piezas para Airflow.** El DAG dispara un job con reintentos, igual que cualquier otro.

## Consecuencias
- Lo que una pipeline trae de fábrica se escribe y se mantiene: checkpoints por fuente
  (`ops.checkpoints`), `MERGE` idempotentes, cuarentena (`silver._quarantine`) y el linaje (se
  documenta con comentarios y tags en Unity Catalog).
- Las expectations de calidad se reemplazan por la cuarentena de Silver y, en la fase de contratos,
  por Soda Core y los tests de dbt (regla 09).
- **Cómo migrar:** Bronze pasa casi igual (Auto Loader dentro de una tabla de streaming), y el SCD2
  pasa a `AUTO CDC ... SEQUENCE BY (lsn, seqval) APPLY AS DELETE WHEN op = 'delete'`. La capa 2 y
  la resolución siguen siendo código propio: se llamarían desde la pipeline o quedarían en el job.
