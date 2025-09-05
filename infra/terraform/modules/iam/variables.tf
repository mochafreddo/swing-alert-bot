variable "project_name" {
  description = "Project name for IAM resource naming"
  type        = string
}

variable "environment" {
  description = "Environment (dev, prod) for IAM resource naming"
  type        = string
}

variable "s3_bucket_arn" {
  description = "ARN of the S3 bucket to allow access"
  type        = string
}

variable "allow_ssm_parameter_arns" {
  description = "SSM Parameter ARNs the Lambda can read"
  type        = list(string)
  default     = []
}

variable "allow_secretsmanager_secret_arns" {
  description = "Secrets Manager ARNs the Lambda can read"
  type        = list(string)
  default     = []
}

variable "role_name_override" {
  description = "Optional explicit IAM role name override"
  type        = string
  default     = ""
}

