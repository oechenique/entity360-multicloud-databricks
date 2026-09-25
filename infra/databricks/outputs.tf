output "catalog_storage_root" {
  value = databricks_catalog.entity360.storage_root
}

output "producer_sp_id" {
  value = databricks_service_principal.producer.id
}

output "producer_sp_application_id" {
  value = databricks_service_principal.producer.application_id
}

output "volume_path" {
  value = "/Volumes/${databricks_catalog.entity360.name}/${databricks_schema.capa["landing"].name}/${databricks_volume.raw.name}"
}

output "producer_sec_edgar_sp_id" {
  value = databricks_service_principal.producer_sec_edgar.id
}

output "producer_sec_edgar_sp_application_id" {
  value = databricks_service_principal.producer_sec_edgar.application_id
}
