aws_region   = "us-east-1"
project_name = "swing-alert-bot"
environment  = "prod"

# Note: Do NOT set `state_bucket_name` here. If you need to pin an exact
# bucket name locally (e.g., you already have one), create
# `infra/terraform/envs/local.prod.tfvars` and set it there. The Makefile will
# auto-load it and the file is gitignored.
