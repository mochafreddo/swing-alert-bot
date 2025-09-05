variable "rules" {
  description = "Map of EventBridge rules keyed by name, each with schedule and target Lambda ARN"
  type = map(object({
    schedule_expression = string
    description         = optional(string)
    state               = optional(string, "ENABLED")
    target_lambda_arn   = string
    # Optional constant JSON input for the target
    input = optional(string)
  }))
  default = {}
}

