from __future__ import annotations

import os
import mimetypes
from pathlib import Path

from .corpus import load_manifest
from .settings import artifact_dir, s3_bucket, s3_prefix


UPLOAD_EXCLUDED_DIRS = {"parse_resume_cache", "parse"}
# GraphRAG's LLM cache (~70MB) and logs are only needed to resume a rebuild, never at
# query time — skip them so the runtime download stays lean. (Vector's cache/ IS needed,
# so this is path-specific rather than a bare "cache" name match.)
UPLOAD_EXCLUDED_PREFIXES = (
    "graphrag_data/graph_index/graphrag_ms/cache",
    "graphrag_data/graph_index/graphrag_ms/logs",
)


def artifact_revision(path: Path | None = None) -> str:
    root = path or artifact_dir()
    revision_path = root / "artifact_revision.txt"
    if not revision_path.exists():
        return ""
    return revision_path.read_text(encoding="utf-8").strip()


def ensure_artifacts(path: Path | None = None) -> Path:
    root = path or artifact_dir()
    try:
        load_manifest(root)
        return root
    except FileNotFoundError:
        bucket = s3_bucket()
        if not bucket:
            raise
        download_artifacts(bucket=bucket, prefix=s3_prefix(), target_dir=root)
        load_manifest(root)
        return root


def _client():
    try:
        import boto3
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
        raise RuntimeError("boto3 is required for S3 artifact sync.") from exc
    return boto3.client("s3")


def upload_artifacts(*, source_dir: Path, bucket: str, prefix: str) -> int:
    if not bucket:
        raise ValueError("S3 bucket is required.")
    client = _client()
    uploaded = 0
    prefix = prefix.strip("/")
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(source_dir).as_posix()
        if any(part in UPLOAD_EXCLUDED_DIRS for part in Path(rel).parts):
            continue
        if any(rel.startswith(prefix) for prefix in UPLOAD_EXCLUDED_PREFIXES):
            continue
        key = f"{prefix}/{rel}" if prefix else rel
        content_type = mimetypes.guess_type(path.name)[0]
        extra_args = {"ExtraArgs": {"ContentType": content_type}} if content_type else {}
        client.upload_file(str(path), bucket, key, **extra_args)
        uploaded += 1
    return uploaded


def download_artifacts(*, bucket: str, prefix: str, target_dir: Path) -> int:
    if not bucket:
        raise ValueError("S3 bucket is required.")
    client = _client()
    prefix = prefix.strip("/")
    paginator = client.get_paginator("list_objects_v2")
    downloaded = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.endswith("/"):
                continue
            rel = key[len(prefix) :].lstrip("/") if prefix else key
            target = target_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(target))
            downloaded += 1
    if downloaded == 0:
        raise FileNotFoundError(f"No S3 artifacts found at s3://{bucket}/{prefix}")
    return downloaded


def configured_s3_uri() -> str:
    bucket = s3_bucket()
    prefix = s3_prefix()
    if not bucket:
        return ""
    return f"s3://{bucket}/{prefix}" if prefix else f"s3://{bucket}"


def runtime_artifact_dir() -> Path:
    configured = os.getenv("GRID_ARTIFACT_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path("/tmp/grid-agent-core/artifacts")
