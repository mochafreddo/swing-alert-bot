output "parameter_names" {
  description = "Map of secret key => SSM parameter name"
  value       = { for k, p in aws_ssm_parameter.secret : k => p.name }
}

output "parameter_arns" {
  description = "Map of secret key => SSM parameter ARN"
  value       = { for k, p in aws_ssm_parameter.secret : k => p.arn }
}

