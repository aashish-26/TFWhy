output "deployment_id" {
  description = "Synthetic deployment identifier."
  value       = module.dev.deployment_id
}

output "service_ids" {
  description = "Synthetic service identifiers keyed by service name."
  value       = module.dev.service_ids
}

output "topology" {
  description = "Synthetic deployment topology summary."
  value       = module.dev.topology
}