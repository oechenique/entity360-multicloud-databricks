# Spike A.1 (b): identidad de máquina para los productores (OAuth M2M).
# El secreto OAuth se crea con la CLI, fuera de Terraform, para que no quede en el state.

resource "databricks_service_principal" "producer" {
  display_name = "entity360-spike-producer"
  # Sin este entitlement la Files API responde 403 aunque los grants de UC estén bien.
  workspace_access = true
}

# Grants no autoritativos (databricks_grant): suman este principal sin tocar otros.
resource "databricks_grant" "catalog_use" {
  catalog    = databricks_catalog.entity360.name
  principal  = databricks_service_principal.producer.application_id
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "schema_use" {
  schema     = databricks_schema.landing.id
  principal  = databricks_service_principal.producer.application_id
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "volume_rw" {
  volume     = databricks_volume.raw.id
  principal  = databricks_service_principal.producer.application_id
  privileges = ["READ_VOLUME", "WRITE_VOLUME"]
}
