# Fase 4 (regla 06, ADR 0003): GDELT sin facturación. GitHub Actions consulta BigQuery sandbox
# autenticado por Workload Identity Federation (OIDC), sin claves de service account.

# APIs de WIF. Ninguna requiere cuenta de facturación (verificado en el paso 0 de la fase 4).
# disable_on_destroy = false: deshabilitar una API no borra nada propio y puede romper otros usos
# del proyecto (BigQuery lo usa también el spike); se deshabilitan a mano si hace falta (destroy.md).
resource "google_project_service" "api" {
  for_each = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "sts.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "bigquery.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --------------------------------------------------------------------------- WIF

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "entity360-github"
  display_name              = "entity360 GitHub Actions"
  description               = "OIDC de GitHub Actions para el productor GDELT (fase 4)."
  depends_on                = [google_project_service.api]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-oidc"
  display_name                       = "GitHub OIDC"
  attribute_mapping = {
    "google.subject"         = "assertion.sub"
    "attribute.repository"   = "assertion.repository"
    "attribute.ref"          = "assertion.ref"
    "attribute.workflow_ref" = "assertion.workflow_ref"
  }
  # Solo este repo, solo la rama main y solo los workflows de GDELT. Cualquier otro token de
  # GitHub (otro repo, otra rama, otro workflow) se rechaza en el intercambio.
  attribute_condition = join(" && ", [
    "assertion.repository == '${var.github_repository}'",
    "assertion.ref == 'refs/heads/main'",
    "assertion.workflow_ref.startsWith('${var.github_repository}/.github/workflows/gdelt-')",
  ])
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# --------------------------------------------------------------------------- service account

# SA dedicada (regla 06), sin claves: solo se usa por impersonación desde el pool.
resource "google_service_account" "gdelt" {
  account_id   = "entity360-gdelt"
  display_name = "entity360 productor GDELT"
  description  = "Consulta GDELT en BigQuery y escribe el respaldo. Sin claves: WIF desde GitHub Actions."
}

resource "google_service_account_iam_member" "wif" {
  service_account_id = google_service_account.gdelt.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# Correr jobs (consultas, dry runs, load jobs) en el proyecto. Leer gdelt-bq no necesita nada: es público.
resource "google_project_iam_member" "gdelt_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.gdelt.email}"
}
