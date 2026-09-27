# Fase 8 (regla 10, ADR 0007): principal de Airflow. Airflow corre local en Docker y no puede usar la
# identidad del usuario (el perfil de la CLI guarda sus tokens OAuth en el llavero de Windows): usa su
# propio SP con OAuth M2M y lo mínimo para orquestar:
#   - verificar lotes (contratos): leer el landing y escribir los veredictos _contrato_*.json;
#   - disparar el job entity360-medallion (el job corre con la identidad de su dueño, no la del SP);
#   - dbt: leer Silver, la resolución y ops.ingestion_log (frescura), y escribir Gold.
# El secreto OAuth se crea fuera de Terraform (airflow/credenciales.py) y vive en el llavero de Windows.

resource "databricks_service_principal" "orquestador" {
  display_name     = "entity360-orquestador"
  workspace_access = true # Files API
  # dbt consulta por el SQL warehouse: sin este entitlement la Statement Execution API
  # responde "disabled for users without the databricks-sql-access". El grupo `users` ya tiene CAN_USE.
  databricks_sql_access = true
}

locals {
  orquestador = databricks_service_principal.orquestador.application_id
  # Schemas que dbt lee: fuentes de Gold y frescura por fuente.
  orquestador_lectura = ["silver", "resolution", "ops"]
}

resource "databricks_grant" "orquestador_catalog" {
  catalog    = databricks_catalog.entity360.name
  principal  = local.orquestador
  privileges = ["USE_CATALOG"]
}

resource "databricks_grant" "orquestador_landing" {
  schema     = databricks_schema.capa["landing"].id
  principal  = local.orquestador
  privileges = ["USE_SCHEMA"]
}

resource "databricks_grant" "orquestador_raw" {
  volume     = databricks_volume.raw.id
  principal  = local.orquestador
  privileges = ["READ_VOLUME", "WRITE_VOLUME"] # WRITE: veredictos de los contratos
}

resource "databricks_grant" "orquestador_lectura" {
  for_each   = toset(local.orquestador_lectura)
  schema     = databricks_schema.capa[each.key].id
  principal  = local.orquestador
  privileges = ["USE_SCHEMA", "SELECT"]
}

# dbt materializa Gold con CREATE OR REPLACE TABLE: el SP es dueño de las tablas que crea. Las cinco
# que creó el usuario en la fase 7 se pasan al SP una vez (docs/manual-steps.md §12).
resource "databricks_grant" "orquestador_gold" {
  schema     = databricks_schema.capa["gold"].id
  principal  = local.orquestador
  privileges = ["USE_SCHEMA", "SELECT", "MODIFY", "CREATE_TABLE"]
}

# Autoritativo sobre el job: el dueño y `admins` los conserva el provider; se suma el SP.
resource "databricks_permissions" "medallion" {
  job_id = databricks_job.medallion.id
  access_control {
    service_principal_name = local.orquestador
    permission_level       = "CAN_MANAGE_RUN"
  }
}

output "orquestador_sp_id" {
  value = databricks_service_principal.orquestador.id
}

output "orquestador_sp_application_id" {
  value = databricks_service_principal.orquestador.application_id
}
