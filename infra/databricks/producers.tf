# Principales técnicos de los productores (regla 03, D4/D5): un SP por productor, con OAuth M2M
# (ADR 0002: límite de 5 secretos por SP, auditoría y aislamiento).
# Los secretos OAuth se crean fuera de Terraform (docs/manual-steps.md) para que no queden en el state.

# SP del extractor CDC (fase 2). Pendiente: renombrarlo a entity360-producer-cdc (ADR 0002).
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

# SP del productor SEC EDGAR (fase 3): lo usa la Lambda de entrega. Mismos grants mínimos.
resource "databricks_service_principal" "producer_sec_edgar" {
  display_name     = "entity360-producer-sec-edgar"
  workspace_access = true
}

resource "databricks_grant" "sec_edgar_catalog" {
  catalog    = databricks_catalog.entity360.name
  principal  = databricks_service_principal.producer_sec_edgar.application_id
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "sec_edgar_landing" {
  schema     = databricks_schema.capa["landing"].id
  principal  = databricks_service_principal.producer_sec_edgar.application_id
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "sec_edgar_raw" {
  volume     = databricks_volume.raw.id
  principal  = databricks_service_principal.producer_sec_edgar.application_id
  privileges = ["READ_VOLUME", "WRITE_VOLUME"]
}
