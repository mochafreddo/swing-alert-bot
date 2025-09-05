# Terraform — swing-alert-bot

This directory contains Terraform IaC for swing-alert-bot. It is structured as reusable modules and a thin root that wires modules per environment.

Modules provided:
- s3: Encrypted, versioned S3 bucket (state JSON storage)
- secrets: SSM Parameter Store SecureString helper
- iam: Lambda execution role with least-privilege to S3 + secrets + logs
- lambda: Lambda function factory (Python 3.11 by default)
- eventbridge: Scheduled rules targeting Lambda functions

Quick start (outline):
1) Pick an AWS region and environment name (e.g., dev/prod).
2) Create tfvars per env under `infra/terraform/envs/`.
3) Wire modules in `infra/terraform/main.tf` (see example below).
4) Run: `terraform init && terraform plan -var-file=infra/terraform/envs/dev.tfvars`.

Example main.tf wiring (edit to fit):

```
module "state_bucket" {
  source      = "./modules/s3"
  bucket_name = "${var.project_name}-${var.environment}-state"
}

module "secrets" {
  source           = "./modules/secrets"
  parameter_prefix = "/${var.project_name}/${var.environment}/"
  # Provide values at apply time or leave empty to skip creation
  secrets = {
    alpha_vantage_api_key = var.alpha_vantage_api_key
    telegram_bot_token    = var.telegram_bot_token
    telegram_chat_id      = var.telegram_chat_id
    fernet_key            = var.fernet_key
  }
}

module "iam" {
  source      = "./modules/iam"
  project_name = var.project_name
  environment  = var.environment
  s3_bucket_arn = module.state_bucket.bucket_arn
  allow_ssm_parameter_arns = values(module.secrets.parameter_arns)
}

module "lambda" {
  source = "./modules/lambda"
  functions = {
    eod_runner = {
      handler     = "src/eod/handler.lambda_handler"
      role_arn    = module.iam.role_arn
      runtime     = "python3.11"
      timeout     = 600
      memory_size = 512
      # Provide either filename (local zip) or s3_bucket/s3_key after CI uploads
      # filename = "build/eod_runner.zip"
      env = {
        STATE_BUCKET = module.state_bucket.bucket_name
        PARAM_PREFIX = "/${var.project_name}/${var.environment}/"
      }
    }
  }
}

module "schedules" {
  source = "./modules/eventbridge"
  rules = {
    us_close = {
      schedule_expression = "cron(5 21 ? * MON-FRI *)" # 21:05 UTC ≈ 4:05pm US/Eastern (non-DST aware)
      target_lambda_arn   = module.lambda.function_arns["eod_runner"]
      description         = "Run at (approx) US market close"
    }
  }
}
```

Add these variables to `variables.tf` if you plan to set secrets via tfvars:

```
variable "alpha_vantage_api_key" { type = string, default = null }
variable "telegram_bot_token"    { type = string, default = null }
variable "telegram_chat_id"      { type = string, default = null }
variable "fernet_key"            { type = string, default = null }
```

Notes:
- Secrets module only creates parameters when values are non-empty.
- Schedules here use EventBridge (CloudWatch Events) cron in UTC; you may adjust for DST or use EventBridge Scheduler later.
- Next roadmap tasks will add tfvars for dev/prod and create the state bucket for Terraform itself.

