# Fase 9 (regla 11, docs/fase9-plan.md): el principal con el que Snowflake lee Gold.
#
# Apagado por defecto (fase9_snowflake = false): un plan o apply de este stack por otro motivo no crea
# nada de la fase 9. Se prende en terraform.tfvars recién al empezarla, y el primer paso es validar el
# credential vending con este SP (snowflake/validar_vending.py), antes de abrir el trial.
#
# Grants mínimos (ADR 0001: consumo por principal dedicado): lectura de gold y nada más. Sin MODIFY ni
# ALL PRIVILEGES aunque la doc de Snowflake los liste: Databricks sigue siendo el dueño de la escritura.
# EXTERNAL_USE_SCHEMA solo en gold y solo en el Camino A (vended credentials); el A2 lee S3 con el
# external volume de Snowflake y el B no usa este SP.

variable "fase9_snowflake" {
  description = "Crea el SP de Snowflake y sus grants (fase 9). false hasta empezar la fase."
  type        = bool
  default     = false
}

variable "snowflake_camino" {
  description = "A (Iceberg REST + vended credentials), A2 (Iceberg REST + external volume) o B (sync)."
  type        = string
  default     = "A"

  validation {
    condition     = contains(["A", "A2", "B"], var.snowflake_camino)
    error_message = "snowflake_camino tiene que ser A, A2 o B."
  }
}

locals {
  snowflake_sp = var.fase9_snowflake && var.snowflake_camino != "B" ? 1 : 0
}

resource "databricks_service_principal" "snowflake" {
  count        = local.snowflake_sp
  display_name = "entity360-snowflake"
  # La API de Iceberg REST de Unity Catalog es del workspace: el SP necesita entrar (D5).
  workspace_access = true
}

resource "databricks_grant" "snowflake_catalog" {
  count      = local.snowflake_sp
  catalog    = databricks_catalog.entity360.name
  principal  = databricks_service_principal.snowflake[0].application_id
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "snowflake_gold" {
  count     = local.snowflake_sp
  schema    = databricks_schema.capa["gold"].id
  principal = databricks_service_principal.snowflake[0].application_id
  privileges = concat(["USE_SCHEMA", "SELECT"],
  var.snowflake_camino == "A" ? ["EXTERNAL_USE_SCHEMA"] : [])
}

output "snowflake_sp_id" {
  description = "id del SP de Snowflake: snowflake/integracion.py le crea el secreto OAuth."
  value       = local.snowflake_sp == 1 ? databricks_service_principal.snowflake[0].id : null
}

output "snowflake_sp_application_id" {
  description = "client_id del SP de Snowflake (OAuth M2M). Su secreto se crea aparte y no pasa por el state."
  value       = local.snowflake_sp == 1 ? databricks_service_principal.snowflake[0].application_id : null
}
