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
