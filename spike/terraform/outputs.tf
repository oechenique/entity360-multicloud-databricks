output "volume_path" {
  value = "/Volumes/${databricks_catalog.entity360.name}/${databricks_schema.landing.name}/${databricks_volume.raw.name}"
}
