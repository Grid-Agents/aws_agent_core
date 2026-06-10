#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "app" / "GridAgentCore"
SERVICE_DIR = APP_ROOT / "colqwen2_service"
TERRAFORM_DIR = REPO_ROOT / "infra" / "colqwen2_sagemaker"
LOG_FILE: Path | None = None


def load_env(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        if raw.startswith("export "):
            raw = raw[len("export ") :].strip()
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env.setdefault(key, value)
    env.setdefault("AWS_DEFAULT_REGION", env.get("AWS_REGION", ""))
    env["AWS_PAGER"] = ""
    return env


def format_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def _timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def write_log(text: str) -> None:
    if LOG_FILE is None:
        return
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(text)


def log(message: str) -> None:
    line = f"[{_timestamp()}] {message}"
    print(line, flush=True)
    write_log(line + "\n")


def log_process_output(text: str) -> None:
    print(text, end="", flush=True)
    write_log(text)


def configure_logging(args: argparse.Namespace) -> None:
    global LOG_FILE
    if args.log_file:
        log_file = args.log_file.expanduser()
        if not log_file.is_absolute():
            log_file = REPO_ROOT / log_file
    else:
        log_file = REPO_ROOT / "logs" / f"colqwen2_visual_retriever_{args.deployment_id}.log"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE = log_file.resolve()
    LOG_FILE.write_text(
        f"ColQwen2 visual retriever run started at {_timestamp()}\n",
        encoding="utf-8",
    )
    log(f"Progress log: {LOG_FILE}")


def run(
    cmd: list[str],
    *,
    cwd: Path = REPO_ROOT,
    env: dict[str, str],
    input_text: str | None = None,
    capture: bool = False,
    log_captured_output: bool = True,
) -> str:
    log(f"$ {format_cmd(cmd)}")
    if capture or input_text is not None:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
        if log_captured_output and result.stdout:
            write_log(result.stdout)
            if not result.stdout.endswith("\n"):
                write_log("\n")
        if log_captured_output and result.stderr:
            write_log(result.stderr)
            if not result.stderr.endswith("\n"):
                write_log("\n")
        if not capture:
            if result.stdout:
                log_process_output(result.stdout)
            if result.stderr:
                log_process_output(result.stderr)
        if result.returncode != 0:
            raise subprocess.CalledProcessError(result.returncode, cmd)
        return result.stdout.strip() if capture else ""

    process = subprocess.Popen(
        cmd,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        log_process_output(line)
    return_code = process.wait()
    if return_code != 0:
        raise subprocess.CalledProcessError(return_code, cmd)
    return ""


def tf_var(name: str, value: str | bool | int) -> str:
    if isinstance(value, bool):
        value = "true" if value else "false"
    return f"{name}={value}"


def terraform_apply(args: argparse.Namespace, env: dict[str, str], *, create_endpoint: bool, image_uri: str) -> None:
    variables = [
        tf_var("region", args.region),
        tf_var("name_prefix", args.name_prefix),
        tf_var("artifact_bucket_name", args.artifact_bucket),
        tf_var("artifact_prefix", args.artifact_prefix.strip("/")),
        tf_var("create_artifact_bucket", args.create_artifact_bucket),
        tf_var("force_destroy_artifact_bucket", args.force_destroy_artifact_bucket),
        tf_var("ecr_repository_name", args.ecr_repository_name),
        tf_var("create_endpoint", create_endpoint),
        tf_var("container_image_uri", image_uri),
        tf_var("deployment_id", args.deployment_id),
        tf_var("endpoint_name", args.endpoint_name),
        tf_var("model_name", args.model_name),
        tf_var("instance_type", args.instance_type),
        tf_var("inference_ami_version", args.inference_ami_version),
        tf_var("initial_instance_count", args.initial_instance_count),
        tf_var("max_batch_size", args.max_batch_size),
        tf_var("max_visual_tokens", args.max_visual_tokens),
        tf_var("response_dtype", args.response_dtype),
    ]
    command = ["terraform", "apply", "-auto-approve"]
    for item in variables:
        command.extend(["-var", item])
    run(command, cwd=TERRAFORM_DIR, env=env)


def terraform_output(name: str, env: dict[str, str]) -> str:
    return run(["terraform", "output", "-raw", name], cwd=TERRAFORM_DIR, env=env, capture=True)


def require_commands(args: argparse.Namespace) -> None:
    required = ["aws", "terraform"]
    if not args.skip_docker_build:
        required.append("docker")
    if not args.skip_uv_sync or not args.skip_index or not args.skip_upload or args.parse_documents:
        required.append("uv")
    missing = [command for command in required if shutil.which(command) is None]
    if not missing:
        return
    install_hints = {
        "aws": "Install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
        "docker": "Install Docker Desktop and start it: https://docs.docker.com/desktop/",
        "terraform": "Install Terraform: brew tap hashicorp/tap && brew install hashicorp/tap/terraform",
        "uv": "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
    }
    details = "\n".join(f"- {command}: {install_hints[command]}" for command in missing)
    raise SystemExit(f"Missing required command(s): {', '.join(missing)}\n{details}")


def docker_login(ecr_repository_url: str, env: dict[str, str], region: str) -> None:
    registry = ecr_repository_url.split("/", 1)[0]
    password = run(
        ["aws", "ecr", "get-login-password", "--region", region],
        env=env,
        capture=True,
        log_captured_output=False,
    )
    run(
        ["docker", "login", "--username", "AWS", "--password-stdin", registry],
        env=env,
        input_text=password,
    )


def build_and_push_image(args: argparse.Namespace, env: dict[str, str], ecr_repository_url: str) -> str:
    image_uri = f"{ecr_repository_url}:{args.image_tag}"
    if args.skip_docker_build:
        print(f"Skipping Docker build; using {image_uri}")
        return image_uri
    docker_login(ecr_repository_url, env, args.region)
    local_tag = f"{args.name_prefix}:colqwen2-{args.image_tag}"
    run(["docker", "build", "--platform", "linux/amd64", "-t", local_tag, "."], cwd=SERVICE_DIR, env=env)
    run(["docker", "tag", local_tag, image_uri], env=env)
    run(["docker", "push", image_uri], env=env)
    return image_uri


def ensure_app_dependencies(env: dict[str, str], *, skip: bool) -> None:
    if skip:
        return
    run(["uv", "sync", "--extra", "build", "--extra", "dev"], cwd=APP_ROOT, env=env)


def parse_documents(args: argparse.Namespace, env: dict[str, str]) -> None:
    if not args.parse_documents:
        return
    source_dir = Path(args.source_dir).expanduser()
    command = [
        "uv",
        "run",
        "grid-parse-documents",
        "--source-dir",
        str(source_dir),
        "--artifact-dir",
        str(args.artifact_dir),
        "--parser",
        args.parser,
    ]
    if args.multimodal_enrich:
        command.append("--multimodal-enrich")
    if args.force_parse:
        command.append("--force")
    run(command, cwd=APP_ROOT, env=env)


def build_colqwen2_index(args: argparse.Namespace, env: dict[str, str]) -> None:
    if args.skip_index:
        return
    command = [
        "uv",
        "run",
        "grid-build-indexes",
        "--artifact-dir",
        str(args.artifact_dir),
        "--methods",
        "colqwen2",
    ]
    if args.rebuild_indexes:
        command.append("--rebuild-indexes")
    run(command, cwd=APP_ROOT, env=env)


def upload_artifacts(args: argparse.Namespace, env: dict[str, str]) -> None:
    if args.skip_upload:
        return
    run(
        [
            "uv",
            "run",
            "grid-upload-artifacts",
            "--artifact-dir",
            str(args.artifact_dir),
            "--bucket",
            args.artifact_bucket,
            "--prefix",
            args.artifact_prefix.strip("/"),
        ],
        cwd=APP_ROOT,
        env=env,
    )


def deploy_agentcore(args: argparse.Namespace, env: dict[str, str]) -> None:
    if not args.deploy_agentcore:
        return
    command = ["python3", "scripts/deploy_grid_agentcore.py", "--env-file", str(args.env_file)]
    if args.agentcore_dry_run_only:
        command.append("--dry-run-only")
    run(command, cwd=REPO_ROOT, env=env)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Provision the AWS ColQwen2 visual retriever service, build Grid "
            "multi-vector page indexes, upload artifacts, and optionally deploy AgentCore."
        )
    )
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--region", default="")
    parser.add_argument("--name-prefix", default="grid-agent-core-colqwen2")
    parser.add_argument("--artifact-bucket", default="")
    parser.add_argument("--artifact-prefix", default="")
    parser.add_argument("--create-artifact-bucket", action="store_true")
    parser.add_argument("--force-destroy-artifact-bucket", action="store_true")
    parser.add_argument("--ecr-repository-name", default="grid-agent-core/colqwen2")
    parser.add_argument("--endpoint-name", default="")
    parser.add_argument("--model-name", default="")
    parser.add_argument("--instance-type", default="ml.g5.xlarge")
    parser.add_argument(
        "--inference-ami-version",
        default="al2-ami-sagemaker-inference-gpu-2-1",
        help="SageMaker inference AMI version for GPU driver/CUDA compatibility.",
    )
    parser.add_argument("--initial-instance-count", type=int, default=1)
    parser.add_argument("--max-batch-size", type=int, default=8)
    parser.add_argument(
        "--max-visual-tokens",
        type=int,
        default=384,
        help="Maximum ColQwen2 visual tokens per page image in the SageMaker service.",
    )
    parser.add_argument("--response-dtype", choices=["float16", "float32"], default="float16")
    parser.add_argument("--image-tag", default="")
    parser.add_argument("--deployment-id", default="")
    parser.add_argument("--skip-docker-build", action="store_true")
    parser.add_argument("--skip-uv-sync", action="store_true")
    parser.add_argument("--artifact-dir", type=Path, default=REPO_ROOT / ".grid_artifacts")
    parser.add_argument("--parse-documents", action="store_true")
    parser.add_argument("--source-dir", default="")
    parser.add_argument("--parser", default="llamaparse-agentic")
    parser.add_argument("--multimodal-enrich", action="store_true")
    parser.add_argument("--force-parse", action="store_true")
    parser.add_argument("--skip-index", action="store_true")
    parser.add_argument("--rebuild-indexes", action="store_true")
    parser.add_argument("--skip-upload", action="store_true")
    parser.add_argument("--deploy-agentcore", action="store_true")
    parser.add_argument("--agentcore-dry-run-only", action="store_true")
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Write a persistent progress log. Defaults to logs/colqwen2_visual_retriever_<deployment-id>.log.",
    )
    return parser.parse_args()


def fill_defaults(args: argparse.Namespace, env: dict[str, str]) -> None:
    args.region = args.region or env.get("AWS_REGION") or env.get("AWS_DEFAULT_REGION") or "us-west-2"
    args.artifact_bucket = args.artifact_bucket or env.get("GRID_S3_BUCKET", "")
    args.artifact_prefix = args.artifact_prefix or env.get("GRID_S3_PREFIX", "grid-agent-core")
    args.endpoint_name = args.endpoint_name or env.get("COLQWEN2_ENDPOINT_NAME", "grid-agent-core-colqwen2")
    args.model_name = args.model_name or env.get("COLQWEN2_MODEL_NAME", "vidore/colqwen2-v1.0")
    args.source_dir = args.source_dir or env.get("GRID_DOCS_DIR", "")
    if not args.image_tag:
        args.image_tag = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d%H%M%S")
    if not args.deployment_id:
        args.deployment_id = args.image_tag.replace("_", "-").replace(".", "-")
    missing = []
    if not args.artifact_bucket:
        missing.append("GRID_S3_BUCKET or --artifact-bucket")
    if args.parse_documents and not args.source_dir:
        missing.append("GRID_DOCS_DIR or --source-dir")
    if missing:
        raise SystemExit("Missing required values: " + ", ".join(missing))
    env["AWS_REGION"] = args.region
    env["AWS_DEFAULT_REGION"] = args.region
    env["GRID_S3_BUCKET"] = args.artifact_bucket
    env["GRID_S3_PREFIX"] = args.artifact_prefix.strip("/")
    env["COLQWEN2_ENDPOINT_NAME"] = args.endpoint_name
    env["COLQWEN2_MODEL_NAME"] = args.model_name


def main() -> None:
    args = parse_args()
    env = load_env(args.env_file)
    fill_defaults(args, env)
    configure_logging(args)
    require_commands(args)

    log("Step 1/8: initialize Terraform")
    run(["terraform", "init"], cwd=TERRAFORM_DIR, env=env)

    log("Step 2/8: provision base AWS resources (S3 optional, ECR, IAM)")
    terraform_apply(args, env, create_endpoint=False, image_uri="")
    ecr_repository_url = terraform_output("ecr_repository_url", env)

    log("Step 3/8: build and push ColQwen2 container image")
    image_uri = build_and_push_image(args, env, ecr_repository_url)

    log("Step 4/8: create or update SageMaker endpoint")
    terraform_apply(args, env, create_endpoint=True, image_uri=image_uri)
    endpoint_name = terraform_output("sagemaker_endpoint_name", env)
    env["COLQWEN2_ENDPOINT_NAME"] = endpoint_name

    log("Step 5/8: prepare local GridAgentCore Python environment")
    ensure_app_dependencies(env, skip=args.skip_uv_sync)

    log("Step 6/8: parse documents if requested")
    parse_documents(args, env)

    log("Step 7/8: build ColQwen2 visual index and upload artifacts")
    build_colqwen2_index(args, env)
    upload_artifacts(args, env)

    log("Step 8/8: deploy AgentCore if requested")
    deploy_agentcore(args, env)

    log("ColQwen2 visual retriever is ready.")
    log(f"export COLQWEN2_ENDPOINT_NAME={shlex.quote(endpoint_name)}")
    log(f"export COLQWEN2_MODEL_NAME={shlex.quote(args.model_name)}")
    log(f"export GRID_S3_BUCKET={shlex.quote(args.artifact_bucket)}")
    log(f"export GRID_S3_PREFIX={shlex.quote(args.artifact_prefix.strip('/'))}")
    log(f"Container image: {image_uri}")
    log(f"Progress log: {LOG_FILE}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        message = f"Command failed with exit code {exc.returncode}: {format_cmd(exc.cmd)}"
        print(message, file=sys.stderr)
        write_log(f"[{_timestamp()}] {message}\n")
        raise SystemExit(exc.returncode)
