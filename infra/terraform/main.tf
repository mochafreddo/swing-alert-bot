# Root module for swing-alert-bot infra.
# Modules (S3, IAM, Lambda, EventBridge, Secrets) are defined under ./modules

data "aws_caller_identity" "current" {}

locals {
  # Default to a globally-unique bucket name by including the AWS account ID.
  # This prevents collisions when others fork and deploy the same project name.
  computed_state_bucket_name = "${var.project_name}-${var.environment}-state-${data.aws_caller_identity.current.account_id}"
  state_bucket_name          = var.state_bucket_name != "" ? var.state_bucket_name : local.computed_state_bucket_name
}

module "state_bucket" {
  source      = "./modules/s3"
  bucket_name = local.state_bucket_name
}

# Optional: create SSM SecureString parameters (only when values provided)
module "secrets" {
  source           = "./modules/secrets"
  parameter_prefix = "/${var.project_name}/${var.environment}/"
  secrets = {
    alpha_vantage_api_key = var.alpha_vantage_api_key
    telegram_bot_token    = var.telegram_bot_token
    telegram_chat_id      = var.telegram_chat_id
    fernet_key            = var.fernet_key
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
  allow_ssm_parameter_arns     = values(module.secrets.parameter_arns)
  allow_secretsmanager_secret_arns = []
}
