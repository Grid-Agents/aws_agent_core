#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = REPO_ROOT / "app" / "GridAgentCore" / "colqwen2_service"
DEFAULT_REPOSITORY = "grid-agent-core/colqwen2"
DEFAULT_ENDPOINT = "grid-agent-core-colqwen2"
DEFAULT_MODEL_NAME = "vidore/colqwen2-v1.0"


def format_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run(cmd: list[str], *, input_text: str | None = None, cwd: Path = REPO_ROOT) -> None:
    print(f"$ {format_cmd(cmd)}")
    subprocess.run(cmd, cwd=cwd, text=True, input=input_text, check=True)


def aws_clients(region: str):
    try:
        import boto3
    except ModuleNotFoundError as exc:
        raise SystemExit("boto3 is required. Run this from the GridAgentCore uv environment.") from exc
    return (
        boto3.client("sts", region_name=region),
        boto3.client("ecr", region_name=region),
        boto3.client("sagemaker", region_name=region),
    )


def ensure_ecr_repo(ecr, repository_name: str) -> str:
    try:
        response = ecr.describe_repositories(repositoryNames=[repository_name])
        return response["repositories"][0]["repositoryUri"]
    except ecr.exceptions.RepositoryNotFoundException:
        response = ecr.create_repository(
            repositoryName=repository_name,
            imageScanningConfiguration={"scanOnPush": True},
            encryptionConfiguration={"encryptionType": "AES256"},
        )
        return response["repository"]["repositoryUri"]


def docker_login(ecr, registry: str) -> None:
    token = ecr.get_authorization_token()["authorizationData"][0]
    username, password = base64.b64decode(token["authorizationToken"]).decode("utf-8").split(":", 1)
    run(["docker", "login", "--username", username, "--password-stdin", registry], input_text=password)


def endpoint_exists(sagemaker, endpoint_name: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        sagemaker.describe_endpoint(EndpointName=endpoint_name)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code == "ValidationException":
            return False
        raise


def deploy(args: argparse.Namespace) -> None:
    region = args.region or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not region:
        raise SystemExit("Set AWS_REGION or pass --region.")
    role_arn = args.execution_role_arn or os.getenv("SAGEMAKER_EXECUTION_ROLE_ARN")
    if not role_arn:
        raise SystemExit("Pass --execution-role-arn or set SAGEMAKER_EXECUTION_ROLE_ARN.")

    sts, ecr, sagemaker = aws_clients(region)
    account_id = sts.get_caller_identity()["Account"]
    repository_uri = ensure_ecr_repo(ecr, args.repository_name)
    registry = f"{account_id}.dkr.ecr.{region}.amazonaws.com"
    tag = args.image_tag or dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    image_uri = f"{repository_uri}:{tag}"

    if not args.no_build:
        docker_login(ecr, registry)
        local_tag = f"grid-agent-core-colqwen2:{tag}"
        run(["docker", "build", "--platform", "linux/amd64", "-t", local_tag, "."], cwd=SERVICE_DIR)
        run(["docker", "tag", local_tag, image_uri])
        run(["docker", "push", image_uri])

    suffix = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    model_name = args.sagemaker_model_name or f"{args.endpoint_name}-model-{suffix}"
    endpoint_config_name = args.endpoint_config_name or f"{args.endpoint_name}-config-{suffix}"
    environment = {
        "COLQWEN2_MODEL_NAME": args.model_name,
        "COLQWEN2_MAX_BATCH_SIZE": str(args.max_batch_size),
        "COLQWEN2_MAX_VISUAL_TOKENS": str(args.max_visual_tokens),
        "COLQWEN2_RESPONSE_DTYPE": args.response_dtype,
    }
    sagemaker.create_model(
        ModelName=model_name,
        ExecutionRoleArn=role_arn,
        PrimaryContainer={"Image": image_uri, "Environment": environment},
    )
    sagemaker.create_endpoint_config(
        EndpointConfigName=endpoint_config_name,
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": model_name,
                "InitialInstanceCount": args.initial_instance_count,
                "InstanceType": args.instance_type,
                "InferenceAmiVersion": args.inference_ami_version,
                "InitialVariantWeight": 1.0,
            }
        ],
    )
    if endpoint_exists(sagemaker, args.endpoint_name):
        sagemaker.update_endpoint(
            EndpointName=args.endpoint_name,
            EndpointConfigName=endpoint_config_name,
        )
        action = "Updating"
    else:
        sagemaker.create_endpoint(
            EndpointName=args.endpoint_name,
            EndpointConfigName=endpoint_config_name,
        )
        action = "Creating"
    print(f"{action} SageMaker endpoint {args.endpoint_name}.")
    if args.wait:
        waiter = sagemaker.get_waiter("endpoint_in_service")
        waiter.wait(
            EndpointName=args.endpoint_name,
            WaiterConfig={"Delay": 60, "MaxAttempts": args.wait_attempts},
        )
    print("\nExport these for index builds and AgentCore runtime:")
    print(f"export COLQWEN2_ENDPOINT_NAME={shlex.quote(args.endpoint_name)}")
    print(f"export COLQWEN2_MODEL_NAME={shlex.quote(args.model_name)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy a self-hosted ColQwen2 embedding service on SageMaker.")
    parser.add_argument("--region", default=None)
    parser.add_argument("--execution-role-arn", default=None)
    parser.add_argument("--repository-name", default=DEFAULT_REPOSITORY)
    parser.add_argument("--image-tag", default=None)
    parser.add_argument("--endpoint-name", default=DEFAULT_ENDPOINT)
    parser.add_argument("--sagemaker-model-name", default=None)
    parser.add_argument("--endpoint-config-name", default=None)
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME)
    parser.add_argument("--instance-type", default="ml.g5.xlarge")
    parser.add_argument("--inference-ami-version", default="al2-ami-sagemaker-inference-gpu-2-1")
    parser.add_argument("--initial-instance-count", type=int, default=1)
    parser.add_argument("--max-batch-size", type=int, default=8)
    parser.add_argument("--max-visual-tokens", type=int, default=384)
    parser.add_argument("--response-dtype", choices=["float16", "float32"], default="float16")
    parser.add_argument("--no-build", action="store_true", help="Skip Docker build/push and reuse the given image tag.")
    parser.add_argument("--wait", action="store_true", help="Wait until the endpoint is InService.")
    parser.add_argument("--wait-attempts", type=int, default=60)
    args = parser.parse_args()
    deploy(args)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {format_cmd(exc.cmd)}", file=sys.stderr)
        raise SystemExit(exc.returncode)
