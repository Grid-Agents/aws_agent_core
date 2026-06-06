#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
AGENTCORE_JSON = REPO_ROOT / "agentcore" / "agentcore.json"
AWS_TARGETS_JSON = REPO_ROOT / "agentcore" / "aws-targets.json"
DEPLOYED_STATE_JSON = REPO_ROOT / "agentcore" / ".cli" / "deployed-state.json"
CDK_OUT_DIR = REPO_ROOT / "agentcore" / "cdk" / "cdk.out"
RUNTIME_ARTIFACT_DIR = "/tmp/grid-agent-core/artifacts"
DEFAULT_VOYAGE_SECRET_NAME = "grid-agent-core/voyage-api-key"
AWS_HELPER_TIMEOUT_SECONDS = 120
ASSET_UPLOAD_TIMEOUT_SECONDS = 7200
AGENTCORE_DEPLOY_TIMEOUT_SECONDS = 3600


def load_env(path: Path) -> dict[str, str]:
    env = os.environ.copy()
    if not path.exists():
        raise SystemExit(f"Missing {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#"):
            continue
        if raw.startswith("export "):
            raw = raw[len("export ") :].strip()
        if "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        env[key] = value
    env.setdefault("AWS_DEFAULT_REGION", env.get("AWS_REGION", ""))
    env["AWS_PAGER"] = ""
    env.setdefault("AWS_MAX_ATTEMPTS", "10")
    env.setdefault("AWS_RETRY_MODE", "adaptive")
    env.setdefault("CDK_DISABLE_VERSION_CHECK", "1")
    return env


def require_env(env: dict[str, str], names: list[str]) -> None:
    missing = [name for name in names if not env.get(name)]
    if missing:
        raise SystemExit(f"Missing required .env values: {', '.join(missing)}")


def format_cmd(cmd: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in cmd)


def run(
    cmd: list[str],
    *,
    env: dict[str, str],
    cwd: Path = REPO_ROOT,
    check: bool = True,
    quiet: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    if not quiet:
        print(f"$ {format_cmd(cmd)}")
    try:
        return subprocess.run(cmd, cwd=cwd, env=env, text=True, check=check, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise SystemExit(f"Command timed out after {exc.timeout}s: {format_cmd(cmd)}") from exc


def ensure_artifact_files() -> None:
    required = [
        ".grid_artifacts/manifest.jsonl",
        ".grid_artifacts/artifact_revision.txt",
        ".grid_artifacts/indexes/vector/index.json",
        ".grid_artifacts/indexes/vector/config.json",
        ".grid_artifacts/indexes/pageindex/index.json",
        ".grid_artifacts/indexes/pageindex/config.json",
    ]
    missing = [rel for rel in required if not (REPO_ROOT / rel).exists()]
    if missing:
        raise SystemExit(
            "Missing local artifact/index files:\n"
            + "\n".join(f"  - {item}" for item in missing)
        )


def ensure_voyage_secret(env: dict[str, str], secret_name: str) -> None:
    key = env.get("VOYAGE_API_KEY", "")
    if not key:
        raise SystemExit("VOYAGE_API_KEY is required because the vector index uses Voyage.")

    describe = subprocess.run(
        [
            "aws",
            "secretsmanager",
            "describe-secret",
            "--secret-id",
            secret_name,
            "--region",
            env["AWS_REGION"],
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=AWS_HELPER_TIMEOUT_SECONDS,
    )

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            temp_path = handle.name
            handle.write(key)
        os.chmod(temp_path, 0o600)
        secret_arg = f"file://{temp_path}"
        if describe.returncode == 0:
            run(
                [
                    "aws",
                    "secretsmanager",
                    "put-secret-value",
                    "--secret-id",
                    secret_name,
                    "--secret-string",
                    secret_arg,
                    "--region",
                    env["AWS_REGION"],
                ],
                env=env,
                timeout=AWS_HELPER_TIMEOUT_SECONDS,
            )
        else:
            run(
                [
                    "aws",
                    "secretsmanager",
                    "create-secret",
                    "--name",
                    secret_name,
                    "--secret-string",
                    secret_arg,
                    "--region",
                    env["AWS_REGION"],
                ],
                env=env,
                timeout=AWS_HELPER_TIMEOUT_SECONDS,
            )
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def set_runtime_env(env_vars: list[dict[str, str]], name: str, value: str) -> None:
    for item in env_vars:
        if item.get("name") == name:
            item["value"] = value
            return
    env_vars.append({"name": name, "value": value})


def update_agentcore_json(env: dict[str, str], secret_name: str) -> None:
    payload = json.loads(AGENTCORE_JSON.read_text(encoding="utf-8"))
    runtimes = payload.get("runtimes", [])
    runtime = next((item for item in runtimes if item.get("name") == "GridAgentCore"), None)
    if runtime is None:
        raise SystemExit("agentcore/agentcore.json does not define a GridAgentCore runtime.")

    env_vars = runtime.setdefault("envVars", [])
    set_runtime_env(env_vars, "AWS_REGION", env["AWS_REGION"])
    set_runtime_env(env_vars, "CLAUDE_CODE_USE_BEDROCK", "1")
    set_runtime_env(env_vars, "ANTHROPIC_MODEL", env["ANTHROPIC_MODEL"])
    set_runtime_env(env_vars, "GRID_ARTIFACT_DIR", RUNTIME_ARTIFACT_DIR)
    set_runtime_env(env_vars, "GRID_S3_BUCKET", env["GRID_S3_BUCKET"])
    set_runtime_env(env_vars, "GRID_S3_PREFIX", env["GRID_S3_PREFIX"].strip("/"))
    set_runtime_env(env_vars, "VOYAGE_API_KEY", f"{{{{resolve:secretsmanager:{secret_name}}}}}")

    AGENTCORE_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def verify_s3_artifacts(env: dict[str, str]) -> None:
    base = f"s3://{env['GRID_S3_BUCKET']}/{env['GRID_S3_PREFIX'].strip('/')}"
    required = [
        "manifest.jsonl",
        "indexes/vector/index.json",
        "indexes/vector/config.json",
        "indexes/pageindex/index.json",
        "indexes/pageindex/config.json",
    ]
    for rel in required:
        run(["aws", "s3", "ls", f"{base}/{rel}"], env=env, timeout=AWS_HELPER_TIMEOUT_SECONDS)


def abort_incomplete_uploads(
    env: dict[str, str],
    *,
    bucket: str,
    key: str,
    region: str,
) -> None:
    result = subprocess.run(
        [
            "aws",
            "s3api",
            "list-multipart-uploads",
            "--bucket",
            bucket,
            "--prefix",
            key,
            "--region",
            region,
            "--query",
            "Uploads[].UploadId",
            "--output",
            "text",
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
        timeout=AWS_HELPER_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        return
    for upload_id in result.stdout.split():
        if upload_id == "None":
            continue
        print(f"Aborting incomplete upload for s3://{bucket}/{key}")
        run(
            [
                "aws",
                "s3api",
                "abort-multipart-upload",
                "--bucket",
                bucket,
                "--key",
                key,
                "--upload-id",
                upload_id,
                "--region",
                region,
            ],
            env=env,
            timeout=AWS_HELPER_TIMEOUT_SECONDS,
        )


def prepublish_cdk_assets(env: dict[str, str], target: str) -> None:
    assets_path = CDK_OUT_DIR / f"AgentCore-GridAgentCore-{target}.assets.json"
    if not assets_path.exists():
        raise SystemExit(f"Missing synthesized CDK assets manifest: {assets_path}")

    assets = json.loads(assets_path.read_text(encoding="utf-8"))
    upload_env = env.copy()
    upload_config = REPO_ROOT / "agentcore" / ".cache" / "aws-cli-upload-config"
    upload_config.parent.mkdir(parents=True, exist_ok=True)
    upload_config.write_text(
        "[default]\n"
        "s3 =\n"
        "    max_concurrent_requests = 4\n"
        "    multipart_threshold = 8MB\n"
        "    multipart_chunksize = 8MB\n",
        encoding="utf-8",
    )
    upload_env["AWS_CONFIG_FILE"] = str(upload_config)

    for item in assets.get("files", {}).values():
        source = item.get("source", {})
        source_path = CDK_OUT_DIR / source.get("path", "")
        if source.get("packaging") != "file" or not source_path.exists():
            raise SystemExit(f"Invalid CDK file asset source: {source_path}")

        for destination in item.get("destinations", {}).values():
            bucket = destination["bucketName"]
            key = destination["objectKey"]
            head = subprocess.run(
                [
                    "aws",
                    "s3api",
                    "head-object",
                    "--bucket",
                    bucket,
                    "--key",
                    key,
                    "--region",
                    destination["region"],
                ],
                cwd=REPO_ROOT,
                env=env,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=AWS_HELPER_TIMEOUT_SECONDS,
            )
            if head.returncode == 0:
                print(f"CDK asset already present: s3://{bucket}/{key}")
                continue

            abort_incomplete_uploads(env, bucket=bucket, key=key, region=destination["region"])
            run(
                [
                    "aws",
                    "--cli-read-timeout",
                    "0",
                    "--cli-connect-timeout",
                    "60",
                    "s3",
                    "cp",
                    str(source_path),
                    f"s3://{bucket}/{key}",
                    "--region",
                    destination["region"],
                ],
                env=upload_env,
                timeout=ASSET_UPLOAD_TIMEOUT_SECONDS,
            )


def deploy(env: dict[str, str], *, target: str, dry_run_only: bool) -> None:
    run(["python3", "-m", "json.tool", str(AGENTCORE_JSON)], env=env, quiet=True)
    run(["python3", "-m", "json.tool", str(AWS_TARGETS_JSON)], env=env, quiet=True)
    run(["agentcore", "validate"], env=env)
    run(["agentcore", "deploy", "--dry-run"], env=env, timeout=AGENTCORE_DEPLOY_TIMEOUT_SECONDS)
    if dry_run_only:
        print("Dry run completed. Re-run without --dry-run-only to deploy.")
        return
    prepublish_cdk_assets(env, target)
    run(["agentcore", "deploy", "-y"], env=env, timeout=AGENTCORE_DEPLOY_TIMEOUT_SECONDS)
    run(["agentcore", "status"], env=env)


def attach_s3_policy(env: dict[str, str], target: str) -> None:
    if not DEPLOYED_STATE_JSON.exists():
        raise SystemExit(f"Missing deployed state: {DEPLOYED_STATE_JSON}")
    state = json.loads(DEPLOYED_STATE_JSON.read_text(encoding="utf-8"))
    try:
        runtime = state["targets"][target]["resources"]["runtimes"]["GridAgentCore"]
        role_arn = runtime["roleArn"]
    except KeyError as exc:
        raise SystemExit("GridAgentCore runtime role ARN was not found in deployed state.") from exc

    role_name = role_arn.rsplit("/", 1)[-1]
    bucket = env["GRID_S3_BUCKET"]
    prefix = env["GRID_S3_PREFIX"].strip("/")
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "s3:ListBucket",
                "Resource": f"arn:aws:s3:::{bucket}",
                "Condition": {
                    "StringLike": {
                        "s3:prefix": [prefix, f"{prefix}/*"],
                    }
                },
            },
            {
                "Effect": "Allow",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{bucket}/{prefix}/*",
            },
        ],
    }

    temp_path = ""
    try:
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            temp_path = handle.name
            json.dump(policy, handle)
        run(
            [
                "aws",
                "iam",
                "put-role-policy",
                "--role-name",
                role_name,
                "--policy-name",
                "GridAgentArtifactsRead",
                "--policy-document",
                f"file://{temp_path}",
            ],
            env=env,
            timeout=AWS_HELPER_TIMEOUT_SECONDS,
        )
    finally:
        if temp_path:
            Path(temp_path).unlink(missing_ok=True)


def print_frontend_instructions(target: str) -> None:
    state = json.loads(DEPLOYED_STATE_JSON.read_text(encoding="utf-8"))
    runtime_arn = state["targets"][target]["resources"]["runtimes"]["GridAgentCore"]["runtimeArn"]
    print("\nFrontend test commands:")
    print("Terminal 1:")
    print("  cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core/app/GridAgentCore")
    print("  set -a; source ../../.env; set +a")
    print(f"  export AGENTCORE_RUNTIME_ARN={shlex.quote(runtime_arn)}")
    print("  export AGENTCORE_RUNTIME_QUALIFIER=DEFAULT")
    print("  uv run grid-local-api --port 8000")
    print("\nTerminal 2:")
    print("  cd /Users/maoxunhuang/Desktop/GridAgents/aws_agent_core/app/GridAgentCore/frontend")
    print("  npm run dev")
    print("\nOpen http://127.0.0.1:5173")


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy GridAgentCore to AWS Bedrock AgentCore.")
    parser.add_argument("--target", default="default")
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--voyage-secret-name", default=DEFAULT_VOYAGE_SECRET_NAME)
    parser.add_argument("--dry-run-only", action="store_true")
    parser.add_argument("--skip-s3-check", action="store_true")
    args = parser.parse_args()

    env = load_env(args.env_file)
    require_env(
        env,
        [
            "AWS_REGION",
            "AWS_ACCESS_KEY_ID",
            "AWS_SECRET_ACCESS_KEY",
            "ANTHROPIC_MODEL",
            "GRID_S3_BUCKET",
            "GRID_S3_PREFIX",
            "VOYAGE_API_KEY",
        ],
    )

    ensure_artifact_files()
    ensure_voyage_secret(env, args.voyage_secret_name)
    update_agentcore_json(env, args.voyage_secret_name)
    if not args.skip_s3_check:
        verify_s3_artifacts(env)
    deploy(env, target=args.target, dry_run_only=args.dry_run_only)
    if not args.dry_run_only:
        attach_s3_policy(env, args.target)
        print_frontend_instructions(args.target)


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {format_cmd(exc.cmd)}", file=sys.stderr)
        raise SystemExit(exc.returncode)
