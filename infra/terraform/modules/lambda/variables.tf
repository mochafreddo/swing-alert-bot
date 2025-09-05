variable "functions" {
  description = "Map of Lambda function definitions keyed by logical name"
  type = map(object({
    handler           = string
    role_arn          = string
    runtime           = optional(string, "python3.11")
    timeout           = optional(number, 60)
    memory_size       = optional(number, 256)
    env               = optional(map(string), {})
    filename          = optional(string)
    s3_bucket         = optional(string)
    s3_key            = optional(string)
    s3_object_version = optional(string)
    architectures     = optional(list(string), ["x86_64"])
    layers            = optional(list(string), [])
    description       = optional(string)
  }))
  default = {}
}

variable "publish" {
  description = "Whether to publish a new version on update"
  type        = bool
  default     = false
}

