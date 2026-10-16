output "deployment_id" {
  description = "Synthetic deployment identifier."
  value       = terraform_data.deployment.output.id
}

output "service_ids" {
  description = "Synthetic service identifiers keyed by service name."
  value = {
    for name, service in terraform_data.services : name => service.output.service
  }
}

output "topology" {
  description = "Synthetic topology and workload summary."
  value = {
    zones     = random_shuffle.availability_zones.result
    services  = keys(terraform_data.services)
    workloads = length(terraform_data.workload)
    configs   = length(terraform_data.service_config)
  }
}