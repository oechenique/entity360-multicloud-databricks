# Van a GitHub Secrets (identifican el proyecto: principio 9), no al código del workflow.
output "wif_provider" {
  value = google_iam_workload_identity_pool_provider.github.name
}

output "service_account_email" {
  value = google_service_account.gdelt.email
}

output "dataset" {
  value = google_bigquery_dataset.gdelt.dataset_id
}
