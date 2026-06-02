from __future__ import annotations

import argparse
from pathlib import Path

from .artifacts import upload_artifacts
from .settings import DEFAULT_ARTIFACT_DIR, s3_bucket, s3_prefix


def main() -> None:
    parser = argparse.ArgumentParser(description="Upload Grid raw documents and indexes to S3.")
    parser.add_argument("--artifact-dir", type=Path, default=DEFAULT_ARTIFACT_DIR)
    parser.add_argument("--bucket", default=s3_bucket())
    parser.add_argument("--prefix", default=s3_prefix())
    args = parser.parse_args()
    count = upload_artifacts(
        source_dir=args.artifact_dir.expanduser().resolve(),
        bucket=args.bucket,
        prefix=args.prefix,
    )
    print(f"Uploaded {count} files to s3://{args.bucket}/{args.prefix.strip('/')}")
