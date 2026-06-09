from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID_DOCS_DIR = Path("/Users/maoxunhuang/Desktop/GridAgents/Grid Docs")
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / ".grid_artifacts"
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_BATCH_MODEL = "claude-3-5-haiku-20241022"
RETRIEVAL_METHODS = ("vector", "pageindex", "graphrag", "colivara", "find")
DEFAULT_RETRIEVAL_METHODS = ("vector", "pageindex", "find")
SUBAGENT_NAME = "span-retriever"


def artifact_dir() -> Path:
    return Path(os.getenv("GRID_ARTIFACT_DIR", str(DEFAULT_ARTIFACT_DIR))).expanduser()


def grid_docs_dir() -> Path:
    return Path(os.getenv("GRID_DOCS_DIR", str(DEFAULT_GRID_DOCS_DIR))).expanduser()


def aws_region() -> str:
    return os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-west-2"


def model_id() -> str:
    return os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL_ID)


def batch_model() -> str:
    return os.getenv("GRID_BATCH_MODEL", DEFAULT_BATCH_MODEL)


def s3_bucket() -> str:
    return os.getenv("GRID_S3_BUCKET", "").strip()


def s3_prefix() -> str:
    return os.getenv("GRID_S3_PREFIX", "grid-agent-core").strip().strip("/")


def colivara_api_key() -> str:
    return os.getenv("COLIVARA_API_KEY", "").strip()


def colivara_api_base_url() -> str:
    return os.getenv("COLIVARA_API_BASE_URL", "https://api.colivara.com").strip()


def colivara_collection_name() -> str:
    return os.getenv("COLIVARA_COLLECTION_NAME", "grid-agent-core").strip()
