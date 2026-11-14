variable "aws_region" {
  description = "AWS Region (Frankfurt for EU/German GDPR compliance)"
  type        = string
  default     = "eu-central-1"
}

variable "environment" {
  description = "Deployment environment name (local, ci, staging, prod)"
  type        = string
  default     = "local"
}

variable "use_emulator" {
  description = "Whether to route AWS API calls to the local Official AWS Emulator on port 9297"
  type        = bool
  default     = true
}

variable "emulator_endpoint" {
  description = "Local endpoint URL for the Official AWS Emulator"
  type        = string
  default     = "https://127.0.0.1:9297"
}

variable "project_name" {
  description = "Project prefix for naming AWS resources"
  type        = string
  default     = "sepa-fintech"
}
