# Marts de los modelers (dbt target snowflake) y roles (docs/fase9-plan.md §4).
#
# ENTITY360_MARTS.MARTS: lo que construye dbt sobre Gold (catalog-linked en A/A2, copiado en B).
# ENTITY360_SYNC.GOLD:  solo en el Camino B, las copias que carga la tarea de Airflow.
# Roles: ENTITY360_DBT escribe los marts; ENTITY360_MODELER lee marts y Gold. Los usuarios se asignan a
# mano (no hay usuarios de personas en Terraform).

locals {
  camino_b = var.camino == "B" ? 1 : 0
}

resource "snowflake_account_role" "dbt" {
  name    = "ENTITY360_DBT"
  comment = "dbt (Airflow y la PC): construye ENTITY360_MARTS.MARTS."
}

resource "snowflake_account_role" "modeler" {
  name    = "ENTITY360_MODELER"
  comment = "Modelers: leen los marts y Gold."
}

resource "snowflake_database" "marts" {
  name    = "ENTITY360_MARTS"
  comment = "Marts de entity360 para los modelers (dbt, target snowflake)."
}

resource "snowflake_schema" "marts" {
  database = snowflake_database.marts.name
  name     = "MARTS"
}

resource "snowflake_database" "sync" {
  count   = local.camino_b
  name    = "ENTITY360_SYNC"
  comment = "Camino B: copia de Gold cargada por Airflow (stage interno + COPY INTO)."
}

resource "snowflake_schema" "sync_gold" {
  count    = local.camino_b
  database = snowflake_database.sync[0].name
  name     = "GOLD"
}

# --- warehouse ----------------------------------------------------------------------------------

resource "snowflake_grant_privileges_to_account_role" "wh" {
  for_each          = { dbt = snowflake_account_role.dbt.name, modeler = snowflake_account_role.modeler.name }
  account_role_name = each.value
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.entity360.name
  }
}

# --- marts: dbt crea, los modelers leen ---------------------------------------------------------

resource "snowflake_grant_privileges_to_account_role" "marts_db" {
  for_each          = { dbt = snowflake_account_role.dbt.name, modeler = snowflake_account_role.modeler.name }
  account_role_name = each.value
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = snowflake_database.marts.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "marts_dbt" {
  account_role_name = snowflake_account_role.dbt.name
  privileges        = ["USAGE", "CREATE TABLE", "CREATE VIEW"]
  on_schema {
    schema_name = "\"${snowflake_database.marts.name}\".\"${snowflake_schema.marts.name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "marts_modeler_schema" {
  account_role_name = snowflake_account_role.modeler.name
  privileges        = ["USAGE"]
  on_schema {
    schema_name = "\"${snowflake_database.marts.name}\".\"${snowflake_schema.marts.name}\""
  }
}

resource "snowflake_grant_privileges_to_account_role" "marts_modeler_lectura" {
  for_each          = toset(["TABLES", "VIEWS"])
  account_role_name = snowflake_account_role.modeler.name
  privileges        = ["SELECT"]
  on_schema_object {
    future {
      object_type_plural = each.value
      in_schema          = "\"${snowflake_database.marts.name}\".\"${snowflake_schema.marts.name}\""
    }
  }
}

# Gold (catalog-linked en A/A2, o la copia del Camino B): los grants sobre la base catalog-linked y las
# tablas que descubre los da snowflake/integracion.py después de crearla (docs/fase9-plan.md §2):
# Terraform no conoce esas tablas.

resource "snowflake_grant_account_role" "modeler_a_sysadmin" {
  role_name        = snowflake_account_role.modeler.name
  parent_role_name = "SYSADMIN"
}

resource "snowflake_grant_account_role" "dbt_a_sysadmin" {
  role_name        = snowflake_account_role.dbt.name
  parent_role_name = "SYSADMIN"
}

# --- usuario de servicio de dbt (key pair, sin contraseña) ---------------------------------------
# La clave pública no es un secreto: la genera snowflake/cuenta.py claves y va en terraform.tfvars.
# La privada queda en ~/.snowflake/keys (fuera del repo) y dbt la lee por SNOWFLAKE_PRIVATE_KEY_PATH.

resource "snowflake_service_user" "dbt" {
  name              = "ENTITY360_DBT_SVC"
  comment           = "dbt de entity360 (target snowflake): construye los marts. Key pair, sin contraseña."
  rsa_public_key    = var.dbt_rsa_public_key
  default_role      = snowflake_account_role.dbt.name
  default_warehouse = snowflake_warehouse.entity360.name
}

resource "snowflake_grant_account_role" "dbt_al_usuario" {
  role_name = snowflake_account_role.dbt.name
  user_name = snowflake_service_user.dbt.name
}
