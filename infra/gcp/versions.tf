terraform {
  required_version = ">= 1.6"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}

# Auth por ADC del usuario (gcloud auth application-default login): nunca claves en el código.
# Proyecto en modo sandbox, sin cuenta de facturación (ADR 0003).
provider "google" {
  project = var.project_id

  default_labels = {
    proyecto = "entity360"
    gestion  = "terraform"
    stack    = "infra-gcp"
  }
}
