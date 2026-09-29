# Gold de Unity Catalog en Snowflake, sin copiar (Caminos A y A2, docs/fase9-plan.md §2).
#
# A:  la catalog integration pide a Unity Catalog la metadata y credenciales S3 temporales (vended
#     credentials). Exige external_access_enabled en el metastore y EXTERNAL_USE_SCHEMA en gold.
# A2: la misma integración para la metadata, pero Snowflake lee S3 con su external volume (un rol IAM
#     de solo lectura sobre el bucket del catálogo). No depende del vending.
#
# El secreto OAuth del SP entra por TF_VAR_uc_sp_client_secret y queda en el state local (ignorado por
# git, marcado sensitive): es el costo de declarar la integración en Terraform. Se rota con el SP.

locals {
  zero_copy = contains(["A", "A2"], var.camino) ? 1 : 0
  a2        = var.camino == "A2" ? 1 : 0
}

resource "snowflake_external_volume" "gold" {
  count        = local.a2
  name         = "ENTITY360_GOLD_VOL"
  allow_writes = "false" # Databricks es el único que escribe Gold
  comment      = "Camino A2: lectura de Gold en S3 con un rol propio de Snowflake."

  storage_location {
    storage_location_name = "entity360-uc-gold"
    storage_provider      = "S3"
    storage_base_url      = var.a2_bucket_url
    storage_aws_role_arn  = var.a2_role_arn
  }
}

resource "snowflake_catalog_integration_iceberg_rest" "unity" {
  count   = local.zero_copy
  name    = "ENTITY360_UNITY"
  enabled = true
  # Cada cuánto Snowflake vuelve a pedir la metadata: dbt reescribe Gold una vez por día.
  refresh_interval_seconds = 300
  comment                  = "Unity Catalog de entity360 por Iceberg REST (camino ${var.camino})."

  rest_config {
    catalog_uri            = "${var.databricks_workspace_url}/api/2.1/unity-catalog/iceberg-rest"
    catalog_name           = "entity360"
    access_delegation_mode = var.camino == "A" ? "VENDED_CREDENTIALS" : "EXTERNAL_VOLUME_CREDENTIALS"
  }

  oauth_rest_authentication {
    oauth_token_uri      = "${var.databricks_workspace_url}/oidc/v1/token"
    oauth_client_id      = var.uc_sp_client_id
    oauth_client_secret  = var.uc_sp_client_secret
    oauth_allowed_scopes = ["all-apis"]
  }
}

# Base catalog-linked: Snowflake descubre los schemas y tablas que el SP puede ver en Unity Catalog
# (solo gold, por los grants de infra/databricks/snowflake.tf) y los mantiene sincronizados.
# El provider no tiene atributo LINKED_CATALOG en snowflake_database: va por SQL, con su reversión.
resource "snowflake_execute" "gold_uc" {
  count = local.zero_copy
  execute = join(" ", [
    "CREATE DATABASE IF NOT EXISTS ENTITY360_UC LINKED_CATALOG = (",
    "CATALOG = '${snowflake_catalog_integration_iceberg_rest.unity[0].name}'",
    local.a2 == 1 ? "EXTERNAL_VOLUME = '${snowflake_external_volume.gold[0].name}'" : "",
    ")",
  ])
  revert = "DROP DATABASE IF EXISTS ENTITY360_UC"
  query  = "SHOW DATABASES LIKE 'ENTITY360_UC'"
}
