variable "environment" {
  description = "Synthetic environment name."
  type        = string
}

variable "service_names" {
  description = "Synthetic service names."
  type        = set(string)
}

variable "availability_zones" {
  description = "Synthetic availability-zone labels."
  type        = list(string)
}

variable "deployment_metadata" {
  description = "Non-sensitive deployment metadata."
  type        = map(string)
}