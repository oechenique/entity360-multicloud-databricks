# Respaldo del lado de GCP (regla 01: cada productor escribe primero en su nube). Sin facturación no
# hay GCS: el respaldo es una tabla de BigQuery sandbox, escrita con load jobs (el sandbox no admite
# DML ni streaming). El sandbox vence tablas y particiones a los 60 días (ADR 0003).
resource "google_bigquery_dataset" "gdelt" {
  dataset_id    = "entity360_gdelt"
  friendly_name = "entity360 GDELT (respaldo)"
  description   = "Respaldo de las menciones de GDELT del universo, antes del push al volume de Databricks."
  location      = var.bq_location
  # El sandbox impone 60 días a tablas y particiones aunque no se declaren (verificado en el paso 0):
  # se declaran para que el plan no tenga drift. La tabla de respaldo es particionada y creada por
  # load job: queda sin expiración de tabla y solo vencen sus particiones (ventana móvil de 60 días).
  default_table_expiration_ms     = 60 * 24 * 60 * 60 * 1000
  default_partition_expiration_ms = 60 * 24 * 60 * 60 * 1000
  # Borrar el dataset con tablas es un paso consciente (destroy.md).
  delete_contents_on_destroy = false
  depends_on                 = [google_project_service.api]
}

resource "google_bigquery_dataset_iam_member" "gdelt_editor" {
  dataset_id = google_bigquery_dataset.gdelt.dataset_id
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.gdelt.email}"
}
