# Snowflake en el DAG (fase 9, próximos pasos): Airflow refresca la base catalog-linked y reaplica los
# grants de lectura sin ACCOUNTADMIN. ENTITY360_SYNC es dueño de ENTITY360_UC (lo cede una vez
# `snowflake/integracion.py ceder`, porque la base y sus tablas no están en Terraform): REFRESH y GRANT
# sobre las tablas exigen OWNERSHIP, y así no hace falta MANAGE GRANTS (de cuenta).

resource "snowflake_account_role" "sync" {
  name    = "ENTITY360_SYNC"
  comment = "Airflow: refresca ENTITY360_UC y reaplica los grants de lectura. Dueño de la base."
}

resource "snowflake_grant_account_role" "sync_a_sysadmin" {
  role_name        = snowflake_account_role.sync.name
  parent_role_name = "SYSADMIN"
}

resource "snowflake_grant_privileges_to_account_role" "sync_wh" {
  account_role_name = snowflake_account_role.sync.name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.entity360.name
  }
}

# Key pair como ENTITY360_DBT_SVC: `snowflake/cuenta.py claves` y la pública en terraform.tfvars.
resource "snowflake_service_user" "sync" {
  count             = var.sync_rsa_public_key == null ? 0 : 1
  name              = "ENTITY360_SYNC_SVC"
  comment           = "Airflow: tareas de Snowflake del DAG (refresco y grants). Key pair, sin contraseña."
  rsa_public_key    = var.sync_rsa_public_key
  default_role      = snowflake_account_role.sync.name
  default_warehouse = snowflake_warehouse.entity360.name
}

resource "snowflake_grant_account_role" "sync_al_usuario" {
  count     = var.sync_rsa_public_key == null ? 0 : 1
  role_name = snowflake_account_role.sync.name
  user_name = snowflake_service_user.sync[0].name
}
