# Root module for swing-alert-bot infra.
# Modules (S3, IAM, Lambda, EventBridge, Secrets) are defined under ./modules

module "state_bucket" {
  source      = "./modules/s3"
  bucket_name = "${var.project_name}-${var.environment}-state"
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
