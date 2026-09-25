# Capas del medallion (regla 03). force_destroy a propósito, igual que el catálogo.

locals {
  schemas = {
    landing    = "Llegada de los productores (push a volumes con manifest por lote)."
    bronze     = "Payload crudo por fuente + metadatos del manifest (Auto Loader)."
    silver     = "Limpieza, tipado y normalización por fuente; CDC aplicado (SCD2)."
    resolution = "Resolución de identidades: matching, clusters y entity_id."
    gold       = "Golden record y vistas de consumo (dashboard, Genie, Snowflake)."
    ops        = "Operación: log de ingesta, controles y métricas del pipeline."
  }
}

resource "databricks_schema" "capa" {
  for_each      = local.schemas
  catalog_name  = databricks_catalog.entity360.name
  name          = each.key
  comment       = each.value
  force_destroy = true
}

resource "databricks_entity_tag_assignment" "capa" {
  for_each    = local.schemas
  entity_type = "schemas"
  entity_name = "${databricks_catalog.entity360.name}.${databricks_schema.capa[each.key].name}"
  tag_key     = "capa"
  tag_value   = each.key
}

resource "databricks_volume" "raw" {
  catalog_name = databricks_catalog.entity360.name
  schema_name  = databricks_schema.capa["landing"].name
  name         = "raw"
  volume_type  = "MANAGED"
  comment      = "Archivos crudos de los productores: <fuente>/ingest_date=YYYY-MM-DD/ + _manifest_<ts>.json (regla 01)."
}
