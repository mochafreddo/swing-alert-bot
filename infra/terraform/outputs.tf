output "state_bucket_name" {
  description = "Name of the state S3 bucket"
  value       = module.state_bucket.bucket_name
}

output "state_bucket_arn" {
  description = "ARN of the state S3 bucket"
  value       = module.state_bucket.bucket_arn
}

output "lambda_role_name" {
  description = "IAM role name for Lambda"
  value       = module.iam.role_name
}

output "lambda_role_arn" {
  description = "IAM role ARN for Lambda"
  value       = module.iam.role_arn
}
