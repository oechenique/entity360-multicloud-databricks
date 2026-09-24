output "volume_path" {
  value = "/Volumes/${databricks_catalog.entity360.name}/${databricks_schema.landing.name}/${databricks_volume.raw.name}"
}

output "producer_sp_id" {
  value = databricks_service_principal.producer.id
}

output "producer_sp_application_id" {
  value = databricks_service_principal.producer.application_id
}
