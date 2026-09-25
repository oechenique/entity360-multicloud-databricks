terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

# Siempre el perfil tesseract (regla 00). Región de la regla 05.
provider "aws" {
  profile = var.aws_profile
  region  = var.aws_region

  default_tags {
    tags = {
      proyecto = "entity360"
      gestion  = "terraform"
      stack    = "infra/aws/sec_edgar"
    }
  }
}
