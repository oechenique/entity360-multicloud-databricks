# Silver incremental: validación en el workspace (pasos 1 a 4 hechos el 2026-09-30; falta el 5)

Código: `databricks/medallion/silver.py` e `incremental.py` (2026-09-29). En local, `tests/medallion/test_incremental.py`
prueba que procesar de a lotes da lo mismo que el recálculo completo (capa 3 con 500 secuencias de lotes
al azar, tablas hijas, y SCD2 con los cambios reales del CDC partidos en todos los cortes posibles y con
un lote reprocesado). Lo que los tests no cubren es el Spark: joins, MERGE con DELETE sobre Iceberg
gestionado y el esquema de las tablas existentes. Eso se valida acá.

## Pasos
1. **Huellas antes**, con el código viejo todavía desplegado (Silver recién recalculado entero):
   ```sql
   -- una fila por tabla: filas y una huella que no depende del orden
   SELECT 'sec_emisor' AS tabla, count(*) AS filas, sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) AS huella FROM entity360.silver.sec_emisor
   UNION ALL SELECT 'sec_nombre', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.sec_nombre
   UNION ALL SELECT 'opensanctions_entidad', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.opensanctions_entidad
   UNION ALL SELECT 'opensanctions_nombre', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.opensanctions_nombre
   UNION ALL SELECT 'wikidata_item', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.wikidata_item
   UNION ALL SELECT 'wikidata_nombre', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.wikidata_nombre
   UNION ALL SELECT 'gdelt_mencion', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.gdelt_mencion
   UNION ALL SELECT 'gleif_entidad_hist', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.gleif_entidad_hist
   UNION ALL SELECT 'gleif_direccion_hist', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.gleif_direccion_hist
   UNION ALL SELECT 'gleif_nombre_alternativo_hist', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.gleif_nombre_alternativo_hist
   UNION ALL SELECT 'gleif_relacion_hist', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.gleif_relacion_hist
   UNION ALL SELECT 'gleif_lei', count(*), sum(cast(xxhash64(to_json(struct(*))) AS decimal(38,0))) FROM entity360.silver.gleif_lei
   ```
2. **Desplegar** (`terraform plan` en `infra/databricks`: cambia `silver.py` y agrega `incremental.py`).
3. **Corrida 1, solo `silver`** (`databricks jobs run-now --json '{"job_id": ..., "only": ["silver"]}'`):
   `silver._lotes_procesados` está vacía, así que procesa todos los lotes de Bronze. Esperado: las mismas
   huellas del paso 1 y `lotes_nuevos` con todos los lotes de cada fuente.
4. **Corrida 2, solo `silver`**, sin lotes nuevos en Bronze. Esperado: `lotes_nuevos` en 0 para las cinco
   fuentes, las mismas huellas y una duración mucho menor (la de siempre: ~5 min).
5. **Corrida completa del DAG** con lotes nuevos (GDELT, OpenSanctions): solo esas fuentes en
   `lotes_nuevos`; resolución, `integridad.py` 7/7 y `dbt build` en verde.

Si las huellas del paso 3 difieren, comparar por clave (`EXCEPT` en los dos sentidos) antes de tocar nada.

## Resultados (2026-09-30)
La consulta del paso 1 sumaba `xxhash64` en BIGINT y desbordaba con ANSI (`ARITHMETIC_OVERFLOW`): se castea
a `decimal(38,0)`, y la huella sigue sin depender del orden.

| tabla | filas | huella (antes = corrida 1 = corrida 2) |
|---|---:|---:|
| sec_emisor | 16 | -33509828188419049299 |
| sec_nombre | 22 | 9335521388001440939 |
| opensanctions_entidad | 2618 | -401596650133132527291 |
| opensanctions_nombre | 13183 | 91773279142906218813 |
| wikidata_item | 20 | 1691140232068465388 |
| wikidata_nombre | 23 | -16338179916503986025 |
| gdelt_mencion | 42 | -66568909410298131934 |
| gleif_entidad_hist | 1167 | 16703230970331832152 |
| gleif_direccion_hist | 2327 | 46849081238015775421 |
| gleif_nombre_alternativo_hist | 147 | -83184178794955438607 |
| gleif_relacion_hist | 395 | 59252525503948804776 |
| gleif_lei | 1163 | 251520797883640904297 |

- **Paso 2:** `terraform apply` (1 a crear y 1 a modificar); el plan posterior no mostró diferencias.
- **Paso 3, corrida 1** (run `590379780825726`, tarea `silver` en 423 s): huellas iguales;
  `lotes_nuevos` = sqlserver_cdc 2, sec_edgar 3, opensanctions 4, wikidata 1, gdelt 8.
- **Paso 4, corrida 2** (run `645348923721662`, tarea `silver` en 32 s): huellas iguales;
  `lotes_nuevos` en 0 para las cinco fuentes.
- **Paso 5:** pendiente (corrida del DAG desde Airflow).
