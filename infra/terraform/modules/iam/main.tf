locals {
  role_name = var.role_name_override != "" ? var.role_name_override : "${var.project_name}-${var.environment}-lambda-role"

  statements = concat(
    [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
        ]
        Resource = "*"
      },
      {
        Sid    = "S3ListBucket"
        Effect = "Allow"
        Action = ["s3:ListBucket"]
        Resource = var.s3_bucket_arn
      },
      {
        Sid    = "S3ObjectRW"
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
        ]
        Resource = "${var.s3_bucket_arn}/*"
      },
    ],
    length(var.allow_ssm_parameter_arns) > 0 ? [
      {
        Sid      = "SSMGetParameters"
        Effect   = "Allow"
        Action   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParameterHistory"]
        Resource = var.allow_ssm_parameter_arns
      }
    ] : [],
    length(var.allow_secretsmanager_secret_arns) > 0 ? [
      {
        Sid      = "SecretsManagerGetSecretValue"
        Effect   = "Allow"
        Action   = ["secretsmanager:GetSecretValue"]
        Resource = var.allow_secretsmanager_secret_arns
      }
    ] : []
  )
}

data "aws_iam_policy_document" "assume" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "lambda" {
  name               = local.role_name
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

resource "aws_iam_policy" "lambda_inline" {
  name   = "${local.role_name}-policy"
  policy = jsonencode({
    Version   = "2012-10-17",
    Statement = local.statements
  })
}

resource "aws_iam_role_policy_attachment" "attach" {
  role       = aws_iam_role.lambda.name
  policy_arn = aws_iam_policy.lambda_inline.arn
}

