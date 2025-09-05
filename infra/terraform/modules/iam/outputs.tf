output "role_name" {
  description = "IAM role name for Lambda"
  value       = aws_iam_role.lambda.name
}

output "role_arn" {
  description = "IAM role ARN for Lambda"
  value       = aws_iam_role.lambda.arn
}

output "policy_arn" {
  description = "Attached policy ARN"
  value       = aws_iam_policy.lambda_inline.arn
}

