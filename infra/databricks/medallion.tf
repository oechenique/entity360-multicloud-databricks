# Fase 6 (regla 08): Bronze, Silver y resolución de identidades.

# Checkpoints de Auto Loader, uno por fuente (<fuente>/). Borrar el de una fuente la reprocesa
# entera; la capa 2 de idempotencia (sha256 en ops.ingestion_log) evita que se dupliquen filas.
resource "databricks_volume" "checkpoints" {
  catalog_name = databricks_catalog.entity360.name
  schema_name  = databricks_schema.capa["ops"].name
  name         = "checkpoints"
  volume_type  = "MANAGED"
  comment      = "Checkpoints de Auto Loader del job entity360-medallion, uno por fuente."
}

# --------------------------------------------------------------------------- código del job

# Solo los módulos del job (databricks/medallion/*.py). Cualquier cambio de código se despliega con
# un apply: el md5 de cada archivo cambia y Terraform lo reemplaza.
locals {
  medallion_dir      = "${path.module}/../../databricks/medallion"
  medallion_archivos = fileset(local.medallion_dir, "*.py")
  medallion_ruta     = "/Shared/entity360/medallion"
}

resource "databricks_directory" "medallion" {
  path = local.medallion_ruta
}

resource "databricks_workspace_file" "medallion" {
  for_each = local.medallion_archivos
  source   = "${local.medallion_dir}/${each.value}"
  path     = "${databricks_directory.medallion.path}/${each.value}"
}

# La tarea `resolucion` lee las claves de GDELT del diccionario de alias del productor (fase 4).
resource "databricks_workspace_file" "alias_gdelt" {
  source = "${path.module}/../../producers/gcp_gdelt/alias.json"
  path   = "${databricks_directory.medallion.path}/alias.json"
}

# --------------------------------------------------------------------------- job

# ADR 0004: job de PySpark explícito, serverless. Una tarea por capa (Free Edition: pocas tareas
# concurrentes y cuota diaria de cómputo). Los reintentos cubren el "manifest todavía no llegó"
# (paso 0: el micro-batch falla y el checkpoint no avanza). Una corrida por día, después de los
# productores diarios (enriquecimiento 06:17, SEC EDGAR 08:00); GDELT y el CDC se acumulan.
resource "databricks_job" "medallion" {
  name                = "entity360-medallion"
  description         = "Bronze (Auto Loader) -> Silver (SCD2, normalización, cuarentena) -> resolución de identidades. Regla 08, ADR 0004."
  max_concurrent_runs = 1

  environment {
    environment_key = "default"
    spec {
      environment_version = "4"
      dependencies        = ["rapidfuzz==3.14.6"]
    }
  }

  task {
    task_key                  = "bronze"
    environment_key           = "default"
    max_retries               = 2
    min_retry_interval_millis = 120000
    timeout_seconds           = 1800
    spark_python_task {
      python_file = databricks_workspace_file.medallion["bronze.py"].workspace_path
      source      = "WORKSPACE"
    }
  }

  # Las tareas van en orden alfabético de task_key, como las devuelve la API: si no, el plan
  # muestra un cambio permanente (el orden de ejecución lo dan los depends_on).
  # rapidfuzz: verificado en el paso 0 (se instala en el environment serverless).
  task {
    task_key                  = "resolucion"
    environment_key           = "default"
    max_retries               = 1
    min_retry_interval_millis = 60000
    timeout_seconds           = 1800
    depends_on {
      task_key = "silver"
    }
    spark_python_task {
      python_file = databricks_workspace_file.medallion["resolucion.py"].workspace_path
      source      = "WORKSPACE"
    }
  }

  task {
    task_key                  = "silver"
    environment_key           = "default"
    max_retries               = 1
    min_retry_interval_millis = 60000
    timeout_seconds           = 1800
    depends_on {
      task_key = "bronze"
    }
    spark_python_task {
      python_file = databricks_workspace_file.medallion["silver.py"].workspace_path
      source      = "WORKSPACE"
    }
  }

  schedule {
    quartz_cron_expression = "0 45 8 * * ?"
    timezone_id            = "America/Argentina/Buenos_Aires"
    pause_status           = "UNPAUSED" # activo desde el 2026-09-27, después de dos corridas manuales verificadas
  }

  tags = {
    proyecto = "entity360"
    capa     = "medallion"
  }
}

output "medallion_job_id" {
  value = databricks_job.medallion.id
}
