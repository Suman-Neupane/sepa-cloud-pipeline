terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # When running against the local AWS Emulator, use mock credentials and skip live IAM/Account checks
  access_key                  = var.use_emulator ? "test" : null
  secret_key                  = var.use_emulator ? "test" : null
  skip_credentials_validation = var.use_emulator
  skip_metadata_api_check     = var.use_emulator
  skip_requesting_account_id  = var.use_emulator

  # S3 path-style addressing is required for local endpoints (https://127.0.0.1:9297/bucket-name)
  s3_use_path_style = var.use_emulator

  # Allow self-signed local emulator TLS certificate if CA bundle isn't explicitly injected into Terraform
  insecure = var.use_emulator

  dynamic "endpoints" {
    for_each = var.use_emulator ? [1] : []
    content {
      s3       = var.emulator_endpoint
      sqs      = var.emulator_endpoint
      dynamodb = var.emulator_endpoint
      sns      = var.emulator_endpoint
      iam      = var.emulator_endpoint
      sts      = var.emulator_endpoint
      kms      = var.emulator_endpoint
    }
  }

  default_tags {
    tags = {
      Project     = var.project_name
      Environment = var.environment
      ManagedBy   = "Terraform"
      Compliance  = "GDPR-SEPA"
    }
  }
}
