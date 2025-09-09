variable "aws_region" {
  description = "AWS region to deploy resources into"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name used for tagging and naming"
  type        = string
  default     = "swing-alert-bot"
}

variable "environment" {
  description = "Environment name (e.g., dev, prod)"
  type        = string
  default     = "dev"
}

variable "tags" {
  description = "Extra tags to apply to all resources"
  type        = map(string)
  default     = {}
}

# Optional: secrets supplied via tfvars to create SSM parameters
variable "alpha_vantage_api_key" { type = string, default = null }
variable "telegram_bot_token"    { type = string, default = null }
variable "telegram_chat_id"      { type = string, default = null }
variable "fernet_key"            { type = string, default = null }
