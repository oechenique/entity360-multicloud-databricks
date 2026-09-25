# Principal técnico de los productores (regla 03, D4/D5): SP con OAuth M2M.
# El secreto OAuth se crea fuera de Terraform (docs/manual-steps.md) para que no quede en el state.

resource "databricks_service_principal" "producer" {
  display_name = "entity360-producer"
  # Sin este entitlement la Files API responde 403 aunque los grants de UC estén bien (spike 1b).
  workspace_access = true
}

# Grants no autoritativos: suman este principal sin tocar otros.
resource "databricks_grant" "producer_catalog" {
  catalog    = databricks_catalog.entity360.name
  principal  = databricks_service_principal.producer.application_id
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "producer_landing" {
  schema     = databricks_schema.capa["landing"].id
  principal  = databricks_service_principal.producer.application_id
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "producer_raw" {
  volume     = databricks_volume.raw.id
  principal  = databricks_service_principal.producer.application_id
  privileges = ["READ_VOLUME", "WRITE_VOLUME"]
}
