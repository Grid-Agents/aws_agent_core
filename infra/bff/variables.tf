variable "region" {
  type    = string
  default = "us-east-1"
}

variable "name" {
  type    = string
  default = "grid-bff"
}

variable "instance_type" {
  type    = string
  default = "t3.medium" # thin proxy; AgentCore does the heavy compute. Stoppable to save cost.
}

variable "runtime_arn" {
  type        = string
  description = "Deployed AgentCore runtime ARN that the BFF forwards requests to."
}

variable "s3_bucket" {
  type        = string
  description = "S3 bucket containing Grid artifacts and the BFF deploy tarball."
}

variable "s3_prefix" {
  type    = string
  default = "grid-agent-core"
}

variable "model" {
  type    = string
  default = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
}

# Private by default: no inbound ports, reach the box via SSM port-forward.
# Flip to true (and set ingress_cidr) only when you add TLS + auth in front.
variable "expose_public" {
  type    = bool
  default = false
}

variable "ingress_cidr" {
  type    = string
  default = "0.0.0.0/0"
}
