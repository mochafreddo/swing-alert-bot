resource "aws_cloudwatch_event_rule" "this" {
  for_each = var.rules

  name                = each.key
  description         = try(each.value.description, null)
  schedule_expression = each.value.schedule_expression
  is_enabled          = try(each.value.state, "ENABLED") == "ENABLED"
}

resource "aws_cloudwatch_event_target" "this" {
  for_each = var.rules

  rule = aws_cloudwatch_event_rule.this[each.key].name
  arn  = each.value.target_lambda_arn
  # Optional constant input payload
  input = try(each.value.input, null)
}

resource "aws_lambda_permission" "allow_events" {
  for_each = var.rules

  statement_id  = "AllowExecutionFromEventBridge-${each.key}"
  action        = "lambda:InvokeFunction"
  function_name = each.value.target_lambda_arn
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.this[each.key].arn
}

