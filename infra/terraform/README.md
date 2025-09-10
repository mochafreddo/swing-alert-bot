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
// Root module computes a fork-safe, unique S3 bucket name by default
// ("${var.project_name}-${var.environment}-state-<AWS_ACCOUNT_ID>").
// You can override via `var.state_bucket_name` if you need an exact name.
module "state_bucket" {
  source      = "./modules/s3"
  bucket_name = local.state_bucket_name
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
    allowed_chat_ids      = var.allowed_chat_ids
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
variable "allowed_chat_ids"      { type = string, default = null }
```

Notes:
- Secrets module only creates parameters when values are non-empty.
- `allowed_chat_ids` is intended for chat ID whitelisting. It may be provided
  as a CSV (e.g., `"12345,67890"`) or a JSON array string
  (e.g., `"[\"12345\", \"67890\"]"`). It is stored as an SSM SecureString
  for simplicity even though it is not sensitive.
- Schedules here use EventBridge (CloudWatch Events) cron in UTC; you may adjust for DST or use EventBridge Scheduler later.
- Next roadmap tasks will add tfvars for dev/prod and create the state bucket for Terraform itself.

### Fork-safe S3 bucket names

- S3 bucket names are globally unique. This project avoids collisions by
  defaulting the state bucket to: `${var.project_name}-${var.environment}-state-<AWS_ACCOUNT_ID>`.
- To pin an exact bucket name (e.g., you already own one), set
  `state_bucket_name` in a local, uncommitted tfvars file and include it when
  running plan/apply. The `Makefile` auto-loads these if present:

```
# infra/terraform/envs/local.dev.tfvars (gitignored)
state_bucket_name = "swing-alert-bot-dev-state"

# infra/terraform/envs/local.prod.tfvars (gitignored)
state_bucket_name = "swing-alert-bot-prod-state"
```

---

## Environments via Workspaces (local state)

This project uses Terraform workspaces to separate environments while keeping local state (solo setup). Use `default` as dev and a `prod` workspace for production.

Quick start:

1) Dev (default workspace)
- Ensure you are in `infra/terraform`
- Check workspace: `terraform workspace show` (should be `default`)
- Plan/apply dev:
  - `aws-vault exec <profile> -- terraform plan  -var-file=envs/dev.tfvars`
  - `aws-vault exec <profile> -- terraform apply -var-file=envs/dev.tfvars`

2) Create/select prod workspace
- First time only: `aws-vault exec <profile> -- terraform workspace new prod`
- Select: `aws-vault exec <profile> -- terraform workspace select prod`
- Plan/apply prod:
  - `aws-vault exec <profile> -- terraform plan  -var-file=envs/prod.tfvars`
  - `aws-vault exec <profile> -- terraform apply -var-file=envs/prod.tfvars`

3) Verify separation
- Show current workspace: `terraform workspace show`
- Outputs reflect that env’s values: `aws-vault exec <profile> -- terraform output`
- State lists only that env’s resources: `aws-vault exec <profile> -- terraform state list`
 - S3 bucket per env (discover via outputs):
  - `aws-vault exec <profile> -- terraform output -raw state_bucket_name`
  - then: `aws-vault exec <profile> -- aws s3api head-bucket --bucket $(terraform output -raw state_bucket_name)`

Tips:
- Always verify `terraform workspace show` and pass the matching `-var-file` for that env.
- Local state is per workspace under `infra/terraform/terraform.tfstate.d/` — do not commit `*.tfstate`.
- Destroy is also per workspace: `terraform destroy -var-file=envs/<env>.tfvars` (prod caution!).

---

## Makefile Usage (convenience targets)

The repo root contains a `Makefile` wrapping common Terraform commands. It supports optional `aws-vault` via the `AWS_VAULT_PROFILE` variable.

- Init providers:
  - `make init`

- Check/select workspaces:
  - `make ws-show`
  - `AWS_VAULT_PROFILE=<profile> make ws-new-prod`   # create once
  - `AWS_VAULT_PROFILE=<profile> make ws-select-dev`
  - `AWS_VAULT_PROFILE=<profile> make ws-select-prod`

- Dev (default workspace):
  - `AWS_VAULT_PROFILE=<profile> make plan-dev`
  - `AWS_VAULT_PROFILE=<profile> make apply-dev`
  - `AWS_VAULT_PROFILE=<profile> make output-dev`
  - `AWS_VAULT_PROFILE=<profile> make state-list-dev`

- Prod (prod workspace):
  - `AWS_VAULT_PROFILE=<profile> make plan-prod`
  - `AWS_VAULT_PROFILE=<profile> make apply-prod`
  - `AWS_VAULT_PROFILE=<profile> make output-prod`
  - `AWS_VAULT_PROFILE=<profile> make state-list-prod`

- Bucket sanity checks:
  - `AWS_VAULT_PROFILE=<profile> make head-bucket-dev`
  - `AWS_VAULT_PROFILE=<profile> make head-bucket-prod`

Notes:
- If you don’t use `aws-vault`, omit `AWS_VAULT_PROFILE` and ensure your AWS CLI is authenticated.
- All targets run with `-chdir=infra/terraform`, so you can invoke from the repo root.
