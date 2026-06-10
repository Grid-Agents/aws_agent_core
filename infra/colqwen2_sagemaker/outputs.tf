output "artifact_bucket_name" {
  value       = local.artifact_bucket
  description = "S3 bucket for Grid runtime artifacts."
}

output "artifact_prefix" {
  value       = var.artifact_prefix
  description = "S3 prefix for Grid runtime artifacts."
}

output "ecr_repository_url" {
  value       = aws_ecr_repository.colqwen2.repository_url
  description = "ECR repository URL for the ColQwen2 container."
}

output "sagemaker_execution_role_arn" {
  value       = aws_iam_role.sagemaker_execution.arn
  description = "IAM role used by the SageMaker endpoint."
}

output "sagemaker_endpoint_name" {
  value       = var.create_endpoint ? aws_sagemaker_endpoint.colqwen2[0].name : var.endpoint_name
  description = "SageMaker endpoint name for ColQwen2 embeddings."
}

output "container_image_uri" {
  value       = var.container_image_uri
  description = "Container image deployed to SageMaker."
}
