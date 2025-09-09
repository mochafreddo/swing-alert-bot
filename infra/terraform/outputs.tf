output "state_bucket_name" {
  description = "Name of the state S3 bucket"
  value       = module.state_bucket.bucket_name
}

output "state_bucket_arn" {
  description = "ARN of the state S3 bucket"
  value       = module.state_bucket.bucket_arn
}

