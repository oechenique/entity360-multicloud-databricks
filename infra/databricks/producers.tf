# Principales técnicos de los productores (regla 03, D4/D5): un SP por productor, con OAuth M2M
# (ADR 0002: límite de 5 secretos por SP, auditoría y aislamiento).
# Los secretos OAuth se crean fuera de Terraform (docs/manual-steps.md) para que no queden en el state.

# SP del extractor CDC (fase 2). Conserva el nombre de la fase 1 (un SP para todos): en Free Edition
# el SP es de cuenta y la API SCIM del workspace ignora el cambio de displayName sin dar error (el
# provider reporta "Modifications complete" y el plan siguiente vuelve a proponerlo). Renombrarlo
# implica reemplazarlo: ver ADR 0002, "Pendiente".
resource "databricks_service_principal" "producer_cdc" {
  display_name = "entity360-producer"
  # Sin este entitlement la Files API responde 403 aunque los grants de UC estén bien (spike 1b).
  workspace_access = true
}

# Grants no autoritativos: suman este principal sin tocar otros.
resource "databricks_grant" "cdc_catalog" {
  catalog    = databricks_catalog.entity360.name
  principal  = databricks_service_principal.producer_cdc.application_id
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "cdc_landing" {
  schema     = databricks_schema.capa["landing"].id
  principal  = databricks_service_principal.producer_cdc.application_id
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "cdc_raw" {
  volume     = databricks_volume.raw.id
  principal  = databricks_service_principal.producer_cdc.application_id
  privileges = ["READ_VOLUME", "WRITE_VOLUME"]
}

# Direcciones viejas del state (antes del ADR 0002): se mueven sin destruir nada.
moved {
  from = databricks_service_principal.producer
  to   = databricks_service_principal.producer_cdc
}

moved {
  from = databricks_grant.producer_catalog
  to   = databricks_grant.cdc_catalog
}

moved {
  from = databricks_grant.producer_landing
  to   = databricks_grant.cdc_landing
}

moved {
  from = databricks_grant.producer_raw
  to   = databricks_grant.cdc_raw
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

# SP del container de enriquecimiento (fase 5): lo usa el workflow de GitHub Actions (secreto en
# GitHub Secrets). Mismos grants mínimos.
resource "databricks_service_principal" "producer_enrichment" {
  display_name     = "entity360-producer-enrichment"
  workspace_access = true
}

resource "databricks_grant" "enrichment_catalog" {
  catalog    = databricks_catalog.entity360.name
  principal  = databricks_service_principal.producer_enrichment.application_id
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "enrichment_landing" {
  schema     = databricks_schema.capa["landing"].id
  principal  = databricks_service_principal.producer_enrichment.application_id
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "enrichment_raw" {
  volume     = databricks_volume.raw.id
  principal  = databricks_service_principal.producer_enrichment.application_id
  privileges = ["READ_VOLUME", "WRITE_VOLUME"]
}
