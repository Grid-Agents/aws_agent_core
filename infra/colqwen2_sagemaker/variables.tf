variable "region" {
  type        = string
  description = "AWS region for ECR, SageMaker, and optional S3 bucket."
}

variable "name_prefix" {
  type        = string
  description = "Prefix for named AWS resources."
  default     = "grid-agent-core-colqwen2"
}

variable "artifact_bucket_name" {
  type        = string
  description = "S3 bucket used for Grid raw documents, indexes, page images, and run artifacts."
}

variable "artifact_prefix" {
  type        = string
  description = "S3 prefix for Grid runtime artifacts."
  default     = "grid-agent-core"
}

variable "create_artifact_bucket" {
  type        = bool
  description = "Create artifact_bucket_name in this stack. Leave false when using an existing bucket."
  default     = false
}

variable "force_destroy_artifact_bucket" {
  type        = bool
  description = "Allow Terraform to delete a non-empty created artifact bucket. Keep false for production."
  default     = false
}

variable "ecr_repository_name" {
  type        = string
  description = "ECR repository name for the ColQwen2 container image. Defaults to <name_prefix>/colqwen2."
  default     = ""
}

variable "create_endpoint" {
  type        = bool
  description = "Create or update the SageMaker model, endpoint config, and endpoint."
  default     = false
}

variable "container_image_uri" {
  type        = string
  description = "Full ECR image URI, including tag, to deploy to SageMaker."
  default     = ""
}

variable "deployment_id" {
  type        = string
  description = "Unique suffix for SageMaker Model and EndpointConfig names."
  default     = "manual"
}

variable "endpoint_name" {
  type        = string
  description = "SageMaker real-time endpoint name."
  default     = "grid-agent-core-colqwen2"
}

variable "model_name" {
  type        = string
  description = "ColQwen2 model name loaded by the container."
  default     = "vidore/colqwen2-v1.0"
}

variable "instance_type" {
  type        = string
  description = "GPU instance type for the SageMaker endpoint."
  default     = "ml.g5.xlarge"
}

variable "inference_ami_version" {
  type        = string
  description = "SageMaker inference AMI version. The default provides NVIDIA 535/CUDA 12.2 for CUDA 12.x containers on ml.g5."
  default     = "al2-ami-sagemaker-inference-gpu-2-1"
}

variable "initial_instance_count" {
  type        = number
  description = "Number of endpoint instances."
  default     = 1
}

variable "max_batch_size" {
  type        = number
  description = "Maximum image/query batch size accepted by the container."
  default     = 8
}

variable "max_visual_tokens" {
  type        = number
  description = "Maximum ColQwen2 visual tokens per page image. Lower values reduce SageMaker real-time latency."
  default     = 384
}

variable "response_dtype" {
  type        = string
  description = "Embedding dtype returned by the SageMaker service."
  default     = "float16"

  validation {
    condition     = contains(["float16", "float32"], var.response_dtype)
    error_message = "response_dtype must be float16 or float32."
  }
}
