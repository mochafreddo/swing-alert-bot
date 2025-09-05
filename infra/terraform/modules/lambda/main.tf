resource "aws_lambda_function" "this" {
  for_each = var.functions

  function_name = each.key
  role          = each.value.role_arn
  handler       = each.value.handler
  runtime       = coalesce(try(each.value.runtime, null), "python3.11")

  timeout     = coalesce(try(each.value.timeout, null), 60)
  memory_size = coalesce(try(each.value.memory_size, null), 256)

  architectures = try(each.value.architectures, null)
  layers        = try(each.value.layers, null)
  description   = try(each.value.description, null)

  # Code from local file or S3 (one of these must be provided when creating functions)
  filename          = try(each.value.filename, null)
  s3_bucket         = try(each.value.s3_bucket, null)
  s3_key            = try(each.value.s3_key, null)
  s3_object_version = try(each.value.s3_object_version, null)

  publish = var.publish

  dynamic "environment" {
    for_each = length(try(each.value.env, {})) > 0 ? [1] : []
    content {
      variables = each.value.env
    }
  }
}

