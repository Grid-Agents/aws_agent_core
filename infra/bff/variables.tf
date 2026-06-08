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

# The deployed AgentCore runtime the BFF forwards to (account 218254303724).
variable "runtime_arn" {
  type    = string
  default = "arn:aws:bedrock-agentcore:us-east-1:218254303724:runtime/GridAgentCore_GridAgentCore-j9s7R2FPWR"
}

variable "s3_bucket" {
  type    = string
  default = "maoxun-grid-agent-artifacts-us-east-1"
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
