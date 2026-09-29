# Fase 10 (regla 12): consumo y observabilidad. El dashboard AI/BI "Entity 360" y las dos tablas de ops
# que alimentan su panel de salud. El espacio de Genie no tiene recurso en el provider: lo crea y
# actualiza databricks/consumo/genie.py desde databricks/consumo/genie/espacio.json.

# Una fila por nodo de cada invocación de dbt (hook on-run-end, dbt/macros/registrar_resultados.sql).
# Delta como ops.ingestion_log: se escribe con INSERT, no con MERGE.
resource "databricks_sql_table" "dbt_resultado" {
  catalog_name       = databricks_catalog.entity360.name
  schema_name        = databricks_schema.capa["ops"].name
  name               = "dbt_resultado"
  table_type         = "MANAGED"
  data_source_format = "DELTA"
  warehouse_id       = data.databricks_sql_warehouse.starter.id
  comment            = "Resultado de cada modelo, test y fuente en cada invocación de dbt (build, run, test, source freshness)."

  column {
    name    = "invocacion"
    type    = "string"
    comment = "invocation_id de dbt: agrupa los nodos de una misma corrida."
  }
  column {
    name    = "comando"
    type    = "string"
    comment = "Comando de dbt: build, run, test, source."
  }
  column {
    name    = "nodo"
    type    = "string"
    comment = "unique_id del nodo (model.entity360.dim_entity, test..., source...)."
  }
  column {
    name    = "tipo"
    type    = "string"
    comment = "model | test | source | seed | snapshot."
  }
  column {
    name    = "estado"
    type    = "string"
    comment = "success | pass | warn | fail | error | skipped | runtime error."
  }
  column {
    name    = "fallas"
    type    = "bigint"
    comment = "Filas que fallan (tests); nulo en modelos y fuentes."
  }
  column {
    name    = "mensaje"
    type    = "string"
    comment = "Mensaje de dbt (hasta 1000 caracteres)."
  }
  column {
    name    = "duracion_s"
    type    = "double"
    comment = "Segundos que tardó el nodo."
  }
  column {
    name    = "ejecutado_utc"
    type    = "timestamp"
    comment = "Momento en que se registró el resultado."
  }
}

# Precisión y recall de la resolución de identidades contra el set curado a mano, por versión
# (calibrar.py --publicar, desde los resultados_<version>.json versionados).
resource "databricks_sql_table" "calidad_resolucion" {
  catalog_name       = databricks_catalog.entity360.name
  schema_name        = databricks_schema.capa["ops"].name
  name               = "calidad_resolucion"
  table_type         = "MANAGED"
  data_source_format = "DELTA"
  warehouse_id       = data.databricks_sql_warehouse.starter.id
  comment            = "Precisión y recall de la resolución de identidades por versión, contra el set de validación curado (D11)."

  column {
    name    = "version"
    type    = "string"
    comment = "Versión de la resolución (v1, v2, v2.1): databricks/resolucion/calibracion/INFORME.md."
  }
  column {
    name    = "particion"
    type    = "string"
    comment = "evaluacion (57 unidades) o set_completo (119)."
  }
  column {
    name    = "ciega"
    type    = "boolean"
    comment = "La medición se hizo sin mirar los errores de esa partición."
  }
  column {
    name = "vp"
    type = "int"
  }
  column {
    name = "fp"
    type = "int"
  }
  column {
    name = "fn"
    type = "int"
  }
  column {
    name = "precision"
    type = "double"
  }
  column {
    name    = "precision_ic_inf"
    type    = "double"
    comment = "Wilson al 95 %."
  }
  column {
    name = "precision_ic_sup"
    type = "double"
  }
  column {
    name = "recall"
    type = "double"
  }
  column {
    name    = "recall_ic_inf"
    type    = "double"
    comment = "Wilson al 95 %."
  }
  column {
    name = "recall_ic_sup"
    type = "double"
  }
  column {
    name    = "entidades"
    type    = "int"
    comment = "Entidades que da la versión sobre el universo (nulo si no se midió)."
  }
  column {
    name = "publicado_utc"
    type = "timestamp"
  }
}

resource "databricks_entity_tag_assignment" "ops_consumo" {
  for_each    = { dbt_resultado = databricks_sql_table.dbt_resultado.name, calidad_resolucion = databricks_sql_table.calidad_resolucion.name }
  entity_type = "tables"
  entity_name = "${databricks_catalog.entity360.name}.${databricks_schema.capa["ops"].name}.${each.value}"
  tag_key     = "capa"
  tag_value   = "ops"
}

# dbt corre en Airflow con el SP del orquestador: el hook necesita escribir sus resultados.
resource "databricks_grant" "orquestador_dbt_resultado" {
  table      = databricks_sql_table.dbt_resultado.id
  principal  = local.orquestador
  privileges = ["SELECT", "MODIFY"]
}

# --------------------------------------------------------------------------- dashboard

# Generado por databricks/consumo/generar_dashboard.py. Publicado con las credenciales del dueño
# (embed_credentials): quien lo ve no necesita permisos sobre las tablas.
resource "databricks_dashboard" "entity360" {
  display_name      = "Entity 360"
  warehouse_id      = data.databricks_sql_warehouse.starter.id
  file_path         = "${path.module}/../../databricks/consumo/entity360.lvdash.json"
  parent_path       = "/Shared/entity360"
  embed_credentials = true
}

output "dashboard_id" {
  value = databricks_dashboard.entity360.dashboard_id
}
