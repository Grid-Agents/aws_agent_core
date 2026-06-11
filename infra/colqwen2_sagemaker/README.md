# ColQwen2 SageMaker Infrastructure

Terraform for the self-hosted ColQwen2 visual retriever embedding service.

This stack manages:

- optional S3 artifact bucket;
- ECR repository for the ColQwen2 container image;
- SageMaker execution IAM role;
- SageMaker Model, EndpointConfig, and real-time Endpoint.

The usual entrypoint is the repo-level orchestrator:

```bash
python3 scripts/build_colqwen2_visual_retriever.py
```

Manual two-phase flow:

```bash
cd /path/to/aws_agent_core
set -a
source .env
set +a

cd infra/colqwen2_sagemaker
terraform init

# Phase 1: create ECR/IAM/S3 resources before an image exists.
terraform apply \
  -var "region=$AWS_REGION" \
  -var "artifact_bucket_name=$GRID_S3_BUCKET" \
  -var "artifact_prefix=$GRID_S3_PREFIX" \
  -var "create_endpoint=false"

ECR_REPO=$(terraform output -raw ecr_repository_url)
```

Build and push the image:

```bash
cd /path/to/aws_agent_core
TAG=$(date -u +%Y%m%d%H%M%S)
REGISTRY="${ECR_REPO%%/*}"

aws ecr get-login-password --region "$AWS_REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY"

docker build --platform linux/amd64 \
  -t "grid-agent-core-colqwen2:$TAG" \
  app/GridAgentCore/colqwen2_service

docker tag "grid-agent-core-colqwen2:$TAG" "$ECR_REPO:$TAG"
docker push "$ECR_REPO:$TAG"
```

Apply the endpoint:

```bash
cd infra/colqwen2_sagemaker
terraform apply \
  -var "region=$AWS_REGION" \
  -var "artifact_bucket_name=$GRID_S3_BUCKET" \
  -var "artifact_prefix=$GRID_S3_PREFIX" \
  -var "create_endpoint=true" \
  -var "container_image_uri=$ECR_REPO:$TAG" \
  -var "deployment_id=$TAG" \
  -var "endpoint_name=${COLQWEN2_ENDPOINT_NAME:-grid-agent-core-colqwen2}" \
  -var "model_name=${COLQWEN2_MODEL_NAME:-vidore/colqwen2-v1.0}"
```

Terraform state is local by default. Do not commit `.terraform/`, `terraform.tfstate`, or `*.tfvars`.
