# Root module for swing-alert-bot infra.
# Modules (S3, IAM, Lambda, EventBridge, Secrets) are defined under ./modules

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  # Default to a globally-unique bucket name by including the AWS account ID.
  # This prevents collisions when others fork and deploy the same project name.
  computed_state_bucket_name = "${var.project_name}-${var.environment}-state-${data.aws_caller_identity.current.account_id}"
  state_bucket_name          = var.state_bucket_name != "" ? var.state_bucket_name : local.computed_state_bucket_name

  # SSM parameter prefix used across modules (e.g., /swing-alert-bot/dev/)
  param_prefix = "/${var.project_name}/${var.environment}/"

  # Always grant Lambdas read access to the whitelist param, even if it is
  # created outside Terraform or the value is omitted in tfvars.
  allowed_chat_ids_param_name = "${local.param_prefix}allowed_chat_ids"
  allowed_chat_ids_param_arn  = "arn:${data.aws_partition.current.partition}:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter${local.allowed_chat_ids_param_name}"
}

module "state_bucket" {
  source      = "./modules/s3"
  bucket_name = local.state_bucket_name
}

# Optional: create SSM SecureString parameters (only when values provided)
module "secrets" {
  source           = "./modules/secrets"
  parameter_prefix = local.param_prefix
  secrets = {
    alpha_vantage_api_key = var.alpha_vantage_api_key
    telegram_bot_token    = var.telegram_bot_token
    telegram_chat_id      = var.telegram_chat_id
    fernet_key            = var.fernet_key
    allowed_chat_ids      = var.allowed_chat_ids
  }
}

# IAM role for Lambda (least privilege):
# - CloudWatch Logs (scoped to /aws/lambda/*)
# - S3 ListBucket/Object R/W for the state bucket
# - SSM read access restricted to created parameters (if any)
module "iam" {
  source       = "./modules/iam"
  project_name = var.project_name
  environment  = var.environment

  s3_bucket_arn                = module.state_bucket.bucket_arn
  # Include any SSM params created by this stack, plus the explicit
  # allowed_chat_ids param ARN so Lambdas can read it even if it was
  # provisioned separately or left unset in tfvars.
  allow_ssm_parameter_arns     = distinct(concat(values(module.secrets.parameter_arns), [local.allowed_chat_ids_param_arn]))
  allow_secretsmanager_secret_arns = []
}
