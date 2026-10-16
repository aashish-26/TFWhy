variable "environment" {
  description = "Environment name used by the synthetic development stack."
  type        = string
  default     = "dev"
}

variable "service_names" {
  description = "Services represented in the development deployment."
  type        = set(string)
  default     = ["api", "worker", "scheduler", "reporter"]
}

variable "availability_zones" {
  description = "Synthetic availability-zone labels for topology testing."
  type        = list(string)
  default     = ["zone-a", "zone-b", "zone-c"]
}

variable "deployment_metadata" {
  description = "Non-sensitive metadata attached to the synthetic deployment."
  type        = map(string)
  default = {
    owner       = "platform"
    cost_center = "engineering"
    managed_by  = "terraform"
  }
}