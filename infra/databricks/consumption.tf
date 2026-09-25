# Consumo (regla 03): lectura de gold. En Free Edition no hay grupos de cuenta propios, así
# que el rol de consumo es "account users"; ingeniería es el owner del catálogo.
# EXTERNAL_USE_SCHEMA sobre gold se otorga en la fase 9 al principal de Snowflake (regla 11).

resource "databricks_grant" "consumo_catalog" {
  catalog    = databricks_catalog.entity360.name
  principal  = "account users"
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "consumo_gold" {
  schema     = databricks_schema.capa["gold"].id
  principal  = "account users"
  privileges = ["USE_SCHEMA", "SELECT"]
}
