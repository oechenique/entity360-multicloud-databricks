# ops.ingestion_log (regla 03): una fila por lote aterrizado. El sha256 del manifest es la
# base de la capa 2 de idempotencia (Bronze descarta lotes ya ingeridos, D6).

data "databricks_sql_warehouse" "starter" {
  name = var.warehouse_name
}

resource "databricks_sql_table" "ingestion_log" {
  catalog_name       = databricks_catalog.entity360.name
  schema_name        = databricks_schema.capa["ops"].name
  name               = "ingestion_log"
  table_type         = "MANAGED"
  data_source_format = "DELTA"
  warehouse_id       = data.databricks_sql_warehouse.starter.id
  comment            = "Una fila por lote aterrizado en landing.raw (manifest)."

  column {
    name    = "fuente"
    type    = "string"
    comment = "Fuente del lote (gleif, sec_edgar, gdelt, opensanctions, wikidata, sqlserver_cdc)."
  }
  column {
    name    = "archivo"
    type    = "string"
    comment = "Ruta del archivo de datos en el volume."
  }
  column {
    name    = "manifest"
    type    = "string"
    comment = "Ruta del _manifest_<ts>.json del lote."
  }
  column {
    name    = "sha256"
    type    = "string"
    comment = "Hash del archivo de datos; clave de idempotencia de Bronze."
  }
  column {
    name    = "registros"
    type    = "bigint"
    comment = "Cantidad de registros según el manifest."
  }
  column {
    name    = "extraido_utc"
    type    = "timestamp"
    comment = "Momento de extracción en la fuente (manifest)."
  }
  column {
    name    = "aterrizado_utc"
    type    = "timestamp"
    comment = "Momento en que se registró el lote en landing."
  }
  column {
    name    = "producer_version"
    type    = "string"
    comment = "Versión del productor que generó el lote."
  }
  column {
    name    = "estado"
    type    = "string"
    comment = "aterrizado | ingerido_bronze | duplicado | error."
  }
}

resource "databricks_entity_tag_assignment" "ingestion_log" {
  entity_type = "tables"
  entity_name = "${databricks_catalog.entity360.name}.${databricks_schema.capa["ops"].name}.${databricks_sql_table.ingestion_log.name}"
  tag_key     = "capa"
  tag_value   = "ops"
}
