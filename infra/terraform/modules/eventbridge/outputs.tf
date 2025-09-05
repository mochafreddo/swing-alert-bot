output "rule_arns" {
  description = "Map of rule name => ARN"
  value       = { for k, r in aws_cloudwatch_event_rule.this : k => r.arn }
}

