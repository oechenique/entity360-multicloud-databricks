# ADR 0014 — El latido de un productor se separa de la frescura de sus datos

- **Estado:** aceptado (2026-10-01). Desplegado en los 4 productores.
- **Relacionado:** ADR 0006 (Bronze exige contrato), ADR 0009 (push al landing), `airflow/README.md`.

## Contexto
El sensor `llegada_<fuente>` de Airflow pasaba si el último manifest del landing era más nuevo que el
`warn_after` de la frescura de esa fuente en dbt. Un productor sano que no tenía nada nuevo (el CDC sin
cambios en el legacy, la SEC sin presentaciones) no dejaba manifest, y el sensor no podía distinguirlo de
un productor caído. El 2026-09-30 la corrida del DAG necesitó un bypass manual en `llegada_sqlserver_cdc`.

## Decisión
- Dos preguntas, dos señales: **"¿el productor está vivo?"** la responde el manifest; **"¿los datos son
  recientes?"** la responde `dbt source freshness` sobre lo que llegó a Bronze.
- Cuando no hay nada nuevo, cada productor deja un `_manifest_<ts>.json` **sin datos** (`sin_cambios: true`,
  `archivo: null`, `registros: 0`, `ultimo_archivo`) que conserva el estado del anterior (sha256,
  `lsn_hasta`, `lote_hasta`): la deduplicación y la recuperación no cambian.
- El sensor ve el latido; Bronze (lee `*.jsonl`) y los contratos (parten de los datos) no lo ven. SEC
  EDGAR entrega solo el manifest.

## Consecuencias
- La corrida `scheduled__2026-10-01T11:45` pasó `llegada_sqlserver_cdc` con el latido, sin bypass
  (`airflow/evidencia/corrida-2026-10-01.md`).
- Un productor caído sigue atrasando su sensor y alertando; una fuente viva pero quieta envejece en la
  frescura de dbt (warn/error según `dbt/models/sources.yml`), que es donde corresponde verlo.
- Más archivos en el landing (uno por corrida sin datos). Tests: `tests/productores/test_latido.py` y un
  caso en `tests/gcp_gdelt`.
