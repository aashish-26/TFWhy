locals {
  common_metadata = merge(var.deployment_metadata, {
    environment = var.environment
    module      = "dev"
  })
}

resource "random_pet" "deployment" {
  length    = 2
  separator = "-"
}

resource "random_string" "release" {
  length  = 10
  lower   = true
  numeric = true
  special = false
  upper   = false
}

resource "random_integer" "base_port" {
  min = 20000
  max = 30000
}

resource "random_uuid" "deployment" {}

resource "random_id" "audit" {
  byte_length = 8
}

resource "random_shuffle" "availability_zones" {
  input        = var.availability_zones
  result_count = 2
}

resource "terraform_data" "deployment" {
  input = {
    id       = random_pet.deployment.id
    release  = random_string.release.result
    run_uuid = random_uuid.deployment.result
    metadata = local.common_metadata
  }
}

resource "terraform_data" "services" {
  for_each = var.service_names

  input = {
    service       = each.key
    port          = random_integer.base_port.result
    deployment_id = terraform_data.deployment.output.id
    audit_id      = random_id.audit.hex
  }
}

resource "terraform_data" "service_config" {
  for_each = terraform_data.services

  input = {
    service_id = each.value.output.service
    endpoint   = "${each.value.output.service}.${var.environment}.internal"
    port       = each.value.output.port
    zones      = random_shuffle.availability_zones.result
  }
}

resource "terraform_data" "workload" {
  count = 4

  input = {
    ordinal      = count.index
    deployment   = terraform_data.deployment.output.id
    service_keys = keys(terraform_data.services)
    config_count = length(terraform_data.service_config)
  }
}

resource "terraform_data" "policy" {
  input = {
    allowed_services = sort(toset(var.service_names))
    metadata_keys    = sort(keys(local.common_metadata))
    workload_count   = length(terraform_data.workload)
  }
}

resource "terraform_data" "observability" {
  input = {
    audit_id       = random_id.audit.hex
    deployment_id  = terraform_data.deployment.output.id
    tracked_config = keys(terraform_data.service_config)
    policy_digest  = terraform_data.policy.output
  }
}

resource "terraform_data" "release_manifest" {
  input = {
    deployment_id = terraform_data.deployment.output.id
    release       = random_string.release.result
    services      = [for service in terraform_data.services : service.output.service]
    workloads     = [for workload in terraform_data.workload : workload.output.ordinal]
    observability = terraform_data.observability.output
  }
}