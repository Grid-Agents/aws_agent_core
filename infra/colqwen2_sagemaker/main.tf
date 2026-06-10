terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = "GridAgentCore"
      Component = "colqwen2-visual-retriever"
      ManagedBy = "terraform"
    }
  }
}

locals {
  ecr_repository_name = var.ecr_repository_name != "" ? var.ecr_repository_name : "${var.name_prefix}/colqwen2"
  artifact_bucket     = var.artifact_bucket_name
}

resource "aws_s3_bucket" "artifacts" {
  count         = var.create_artifact_bucket ? 1 : 0
  bucket        = local.artifact_bucket
  force_destroy = var.force_destroy_artifact_bucket
}

resource "aws_s3_bucket_public_access_block" "artifacts" {
  count                   = var.create_artifact_bucket ? 1 : 0
  bucket                  = aws_s3_bucket.artifacts[0].id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "artifacts" {
  count  = var.create_artifact_bucket ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "artifacts" {
  count  = var.create_artifact_bucket ? 1 : 0
  bucket = aws_s3_bucket.artifacts[0].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_ecr_repository" "colqwen2" {
  name                 = local.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

data "aws_iam_policy_document" "sagemaker_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["sagemaker.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sagemaker_execution" {
  name               = "${var.name_prefix}-sagemaker-execution"
  assume_role_policy = data.aws_iam_policy_document.sagemaker_assume_role.json
}

data "aws_iam_policy_document" "sagemaker_execution" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPullImage"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.colqwen2.arn]
  }

  statement {
    sid = "ReadWriteGridArtifacts"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
    ]
    resources = ["arn:aws:s3:::${local.artifact_bucket}/${var.artifact_prefix}/*"]
  }

  statement {
    sid       = "ListGridArtifactPrefix"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${local.artifact_bucket}"]

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [var.artifact_prefix, "${var.artifact_prefix}/*"]
    }
  }

  statement {
    sid = "WriteSageMakerEndpointLogs"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:DescribeLogStreams",
      "logs:PutLogEvents",
    ]
    resources = [
      "arn:aws:logs:${var.region}:*:log-group:/aws/sagemaker/Endpoints/${var.endpoint_name}*",
      "arn:aws:logs:${var.region}:*:log-group:/aws/sagemaker/Endpoints/${var.endpoint_name}*:*",
    ]
  }
}

resource "aws_iam_role_policy" "sagemaker_execution" {
  name   = "${var.name_prefix}-sagemaker-execution"
  role   = aws_iam_role.sagemaker_execution.id
  policy = data.aws_iam_policy_document.sagemaker_execution.json
}

resource "aws_sagemaker_model" "colqwen2" {
  count              = var.create_endpoint ? 1 : 0
  name               = "${var.endpoint_name}-model-${var.deployment_id}"
  execution_role_arn = aws_iam_role.sagemaker_execution.arn

  primary_container {
    image = var.container_image_uri
    environment = {
      COLQWEN2_MODEL_NAME        = var.model_name
      COLQWEN2_MAX_BATCH_SIZE    = tostring(var.max_batch_size)
      COLQWEN2_MAX_VISUAL_TOKENS = tostring(var.max_visual_tokens)
      COLQWEN2_RESPONSE_DTYPE    = var.response_dtype
    }
  }

  lifecycle {
    precondition {
      condition     = var.container_image_uri != ""
      error_message = "container_image_uri is required when create_endpoint is true."
    }
  }
}

resource "aws_sagemaker_endpoint_configuration" "colqwen2" {
  count = var.create_endpoint ? 1 : 0
  name  = "${var.endpoint_name}-config-${var.deployment_id}"

  production_variants {
    variant_name           = "AllTraffic"
    model_name             = aws_sagemaker_model.colqwen2[0].name
    initial_instance_count = var.initial_instance_count
    instance_type          = var.instance_type
    inference_ami_version  = var.inference_ami_version
    initial_variant_weight = 1
  }
}

resource "aws_sagemaker_endpoint" "colqwen2" {
  count                = var.create_endpoint ? 1 : 0
  name                 = var.endpoint_name
  endpoint_config_name = aws_sagemaker_endpoint_configuration.colqwen2[0].name
}
