locals {
  secrets_to_create = {
    for k, v in var.secrets : k => v
    if v != null && v != ""
  }
}

resource "aws_ssm_parameter" "secret" {
  for_each = local.secrets_to_create

  name  = "${var.parameter_prefix}${each.key}"
  type  = "SecureString"
  value = each.value

  overwrite = var.overwrite

  # Optional KMS key; if empty, AWS managed key for SSM is used
  kms_key_id = var.kms_key_id != "" ? var.kms_key_id : null
}

