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
  # Credentials are taken from the environment (AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY),
  # which we export from the repo .env (MaoXun's account 218254303724) before running terraform.
  default_tags {
    tags = {
      Project   = "GridAgentCore"
      Component = "bff-proxy"
      ManagedBy = "terraform"
      Owner     = "kaps"
    }
  }
}

# ----- network: reuse the default VPC + one of its subnets (no new VPC) -----
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# Latest Amazon Linux 2023 x86_64 AMI (public SSM parameter).
data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# ----- IAM: instance role so the box needs NO static AWS keys -----
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "bff" {
  name               = "${var.name}-role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

data "aws_iam_policy_document" "bff" {
  # Forward requests to the deployed AgentCore runtime (the whole point of the BFF).
  statement {
    sid       = "InvokeAgentCore"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [var.runtime_arn, "${var.runtime_arn}/*"]
  }

  # Read artifacts (corpus + figure crops) and the deploy tarball.
  statement {
    sid       = "ReadArtifacts"
    actions   = ["s3:GetObject"]
    resources = ["arn:aws:s3:::${var.s3_bucket}/${var.s3_prefix}/*"]
  }

  # Read/write run history under <prefix>/runs/.
  statement {
    sid       = "RunHistory"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["arn:aws:s3:::${var.s3_bucket}/${var.s3_prefix}/runs/*"]
  }

  statement {
    sid       = "ListBucket"
    actions   = ["s3:ListBucket"]
    resources = ["arn:aws:s3:::${var.s3_bucket}"]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["${var.s3_prefix}/*"]
    }
  }
}

resource "aws_iam_role_policy" "bff" {
  name   = "${var.name}-policy"
  role   = aws_iam_role.bff.id
  policy = data.aws_iam_policy_document.bff.json
}

# SSM Session Manager so we can reach the box with NO inbound ports.
resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.bff.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "bff" {
  name = "${var.name}-profile"
  role = aws_iam_role.bff.name
}

# ----- security group: private by default (no inbound; reach via SSM tunnel) -----
resource "aws_security_group" "bff" {
  name        = "${var.name}-sg"
  description = "Grid BFF proxy - egress only by default"
  vpc_id      = data.aws_vpc.default.id

  dynamic "ingress" {
    for_each = var.expose_public ? [1] : []
    content {
      description = "HTTPS from allowed CIDR (public mode)"
      from_port   = 443
      to_port     = 443
      protocol    = "tcp"
      cidr_blocks = [var.ingress_cidr]
    }
  }

  egress {
    description = "All outbound (AWS APIs, pypi, astral.sh)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# ----- ship the app code to S3 so the box can pull it (private repo, no GitHub creds on box) -----
resource "aws_s3_object" "code" {
  bucket = var.s3_bucket
  key    = "${var.s3_prefix}/deploy/grid-bff.tar.gz"
  source = "${path.module}/dist/grid-bff.tar.gz"
  etag   = filemd5("${path.module}/dist/grid-bff.tar.gz")
}

# ----- the instance -----
resource "aws_instance" "bff" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnets.default.ids[0]
  iam_instance_profile        = aws_iam_instance_profile.bff.name
  vpc_security_group_ids      = [aws_security_group.bff.id]
  associate_public_ip_address = true

  root_block_device {
    volume_size = 30
    volume_type = "gp3"
    encrypted   = true
  }

  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/user_data.sh.tftpl", {
    region       = var.region
    runtime_arn  = var.runtime_arn
    s3_bucket    = var.s3_bucket
    s3_prefix    = var.s3_prefix
    model        = var.model
    code_s3_uri  = "s3://${var.s3_bucket}/${aws_s3_object.code.key}"
    bind_address = var.expose_public ? "0.0.0.0" : "127.0.0.1"
  })

  tags = {
    Name = var.name
  }

  depends_on = [aws_s3_object.code]
}
