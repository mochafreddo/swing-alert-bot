variable "parameter_prefix" {
  description = "Prefix for SSM parameter names (e.g., /swing-alert-bot/dev/)"
  type        = string
}

variable "secrets" {
  description = "Map of secret key => value to create as SecureString parameters. Empty values are ignored."
  type        = map(string)
  default     = {}
}

variable "overwrite" {
  description = "Whether to overwrite existing parameters when values change"
  type        = bool
  default     = false
}

variable "kms_key_id" {
  description = "Optional KMS key ID/ARN for SecureString encryption (defaults to AWS managed)"
  type        = string
  default     = ""
}

