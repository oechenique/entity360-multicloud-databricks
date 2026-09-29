# Cómputo y tope de gasto (regla 11, "en ambos caminos"). El resource monitor va primero: ningún
# warehouse existe sin tope (principio 5 aplicado a Snowflake).

resource "snowflake_resource_monitor" "entity360" {
  name         = "ENTITY360_MONITOR"
  credit_quota = var.creditos_mensuales
  # Sin frequency ni start_timestamp: Snowflake usa MONTHLY desde la creación (el provider exige los
  # dos juntos). Avisos a los administradores con notificaciones activas.
  notify_triggers           = [50, 75, 90]
  suspend_trigger           = 100 # deja terminar lo que está corriendo
  suspend_immediate_trigger = 110 # corta todo
}

resource "snowflake_warehouse" "entity360" {
  name                = "ENTITY360_WH"
  warehouse_size      = "XSMALL" # 1 crédito por hora, por segundo con mínimo de 60 s
  auto_suspend        = 60
  auto_resume         = "true"
  initially_suspended = true
  min_cluster_count   = 1
  max_cluster_count   = 1
  # Una consulta desbocada no puede quemar el mes: 15 min por statement.
  statement_timeout_in_seconds = 900
  resource_monitor             = snowflake_resource_monitor.entity360.name
  comment                      = "entity360: dbt (marts) y consultas de los modelers."
}

# --- tope de la cuenta entera (2026-09-29) --------------------------------------------------------
# ENTITY360_MONITOR es de nivel warehouse (solo ENTITY360_WH). Este cubre todos los warehouses de la cuenta
# (COMPUTE_WH de Snowsight, SNOWFLAKE_LEARNING_WH y los que aparezcan). Es un monitor aparte porque un
# warehouse admite un solo monitor y la documentación no aclara si el mismo puede estar a los dos niveles
# (podría contar dos veces a ENTITY360_WH).
# NO cubre serverless (sincronización catalog-linked, Snowpipe, tareas serverless) ni cloud services:
# eso se mide a diario (snowflake/evidencia/consumo.md).

resource "snowflake_resource_monitor" "cuenta" {
  name                      = "ENTITY360_CUENTA"
  credit_quota              = var.creditos_cuenta
  notify_triggers           = [50, 75, 90]
  suspend_trigger           = 100
  suspend_immediate_trigger = 110
}

# snowflake_current_account manejaría todos los parámetros de la cuenta (los que no se declaran se
# resetean al crearlo y al borrarlo): demasiado para asignar un monitor. Va por SQL.
resource "snowflake_execute" "monitor_de_cuenta" {
  execute = "ALTER ACCOUNT SET RESOURCE_MONITOR = ${snowflake_resource_monitor.cuenta.name}"
  # Sintaxis de UNSET a verificar en el destroy; si fallara, el DROP del monitor (que viene después)
  # también lo desasigna.
  revert = "ALTER ACCOUNT UNSET RESOURCE_MONITOR"
  query  = "SHOW RESOURCE MONITORS LIKE '${snowflake_resource_monitor.cuenta.name}'"
}

# COMPUTE_WH lo crea el trial y lo usa Snowsight: no es de Terraform ni se borra. Solo se le baja el
# auto-suspend de 300 a 60 s; el revert lo deja como estaba.
resource "snowflake_execute" "compute_wh_auto_suspend" {
  execute = "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 60"
  revert  = "ALTER WAREHOUSE COMPUTE_WH SET AUTO_SUSPEND = 300"
  query   = "SHOW WAREHOUSES LIKE 'COMPUTE_WH'"
}
