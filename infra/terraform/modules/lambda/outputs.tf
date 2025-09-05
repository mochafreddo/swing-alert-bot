output "function_arns" {
  description = "Map of function logical name => ARN"
  value       = { for k, f in aws_lambda_function.this : k => f.arn }
}

output "function_names" {
  description = "Map of function logical name => function name"
  value       = { for k, f in aws_lambda_function.this : k => f.function_name }
}

