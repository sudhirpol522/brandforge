variable "aws_region" {
  description = "AWS region for the BrandForge stack."
  type        = string
  default     = "us-east-1"
}

variable "name" {
  description = "Lowercase deployment name."
  type        = string
  default     = "brandforge"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "name must be a lowercase DNS-safe identifier."
  }
}

variable "environment" {
  type    = string
  default = "staging"
}

variable "vpc_cidr" {
  type    = string
  default = "10.42.0.0/16"
}

variable "api_image" {
  description = "Immutable API image reference, preferably an ECR digest."
  type        = string
}

variable "worker_image" {
  description = "Immutable worker image reference. Defaults to the API image."
  type        = string
  default     = ""
}

variable "openai_api_key_secret_arn" {
  description = "Existing Secrets Manager ARN containing the OpenAI API key as its full secret string."
  type        = string
  default     = ""
  sensitive   = true
}

variable "text_model" {
  type    = string
  default = "gpt-5.6"
}

variable "vision_model" {
  type    = string
  default = "gpt-5.6"
}

variable "image_model" {
  type    = string
  default = "gpt-image-2"
}

variable "enable_public_demo" {
  description = "Makes the ALB public and enables development-header auth. Never use for production."
  type        = bool
  default     = false
}

variable "allowed_origins" {
  description = "Comma-separated HTTPS origins allowed by the API CORS policy."
  type        = string
  default     = "https://brandforge.example.com"
}

variable "database_instance_class" {
  type    = string
  default = "db.t4g.medium"
}

variable "database_allocated_storage_gb" {
  type    = number
  default = 50
}

variable "api_desired_count" {
  type    = number
  default = 2
}

variable "worker_desired_count" {
  type    = number
  default = 1
}
