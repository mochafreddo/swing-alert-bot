# Root module for swing-alert-bot infra.
# Modules (S3, IAM, Lambda, EventBridge, Secrets) are defined under ./modules

module "state_bucket" {
  source      = "./modules/s3"
  bucket_name = "${var.project_name}-${var.environment}-state"
}
