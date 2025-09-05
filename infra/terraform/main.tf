# Skeleton root module for swing-alert-bot infra.
# Modules (S3, IAM, Lambda, EventBridge, Secrets) are defined under ./modules
# and will be instantiated in a subsequent task with env-specific tfvars.

# Example (to be wired in a later task):
# module "state_bucket" {
#   source      = "./modules/s3"
#   bucket_name = "${var.project_name}-${var.environment}-state"
# }

