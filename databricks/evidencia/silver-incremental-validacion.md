# Silver incremental: validación en el workspace (pendiente, cuota diaria de Free Edition)

Código: `databricks/medallion/silver.py` e `incremental.py` (2026-09-29). En local, `tests/medallion/test_incremental.py`
prueba que procesar de a lotes da lo mismo que el recálculo completo (capa 3 con 500 secuencias de lotes
al azar, tablas hijas, y SCD2 con los cambios reales del CDC partidos en todos los cortes posibles y con
un lote reprocesado). Lo que los tests no cubren es el Spark: joins, MERGE con DELETE sobre Iceberg
gestionado y el esquema de las tablas existentes. Eso se valida acá.

## Pasos
1. **Huellas antes**, con el código viejo todavía desplegado (Silver recién recalculado entero):
   ```sql
   -- una fila por tabla: filas y una huella que no depende del orden
   SELECT 'sec_emisor' AS tabla, count(*) AS filas, sum(xxhash64(to_json(struct(*)))) AS huella FROM entity360.silver.sec_emisor
   UNION ALL SELECT 'sec_nombre', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.sec_nombre
   UNION ALL SELECT 'opensanctions_entidad', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.opensanctions_entidad
   UNION ALL SELECT 'opensanctions_nombre', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.opensanctions_nombre
   UNION ALL SELECT 'wikidata_item', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.wikidata_item
   UNION ALL SELECT 'wikidata_nombre', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.wikidata_nombre
   UNION ALL SELECT 'gdelt_mencion', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.gdelt_mencion
   UNION ALL SELECT 'gleif_entidad_hist', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.gleif_entidad_hist
   UNION ALL SELECT 'gleif_direccion_hist', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.gleif_direccion_hist
   UNION ALL SELECT 'gleif_nombre_alternativo_hist', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.gleif_nombre_alternativo_hist
   UNION ALL SELECT 'gleif_relacion_hist', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.gleif_relacion_hist
   UNION ALL SELECT 'gleif_lei', count(*), sum(xxhash64(to_json(struct(*)))) FROM entity360.silver.gleif_lei
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
