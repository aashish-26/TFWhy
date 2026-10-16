terraform {
  required_version = ">= 1.5.0"

  required_providers {
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

module "dev" {
  source = "./modules/dev"

  environment         = var.environment
  service_names       = var.service_names
  availability_zones  = var.availability_zones
  deployment_metadata = var.deployment_metadata
}