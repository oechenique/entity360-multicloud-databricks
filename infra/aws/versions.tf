terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

# Siempre el perfil tesseract (regla 00). Región del metastore de Unity Catalog.
provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region

  default_tags {
    tags = {
      proyecto = "entity360"
      gestion  = "terraform"
      stack    = "infra/aws"
    }
  }
}
