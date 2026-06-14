from __future__ import annotations

import os
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GRID_DOCS_DIR = PROJECT_ROOT / "Grid Docs"
DEFAULT_ARTIFACT_DIR = PROJECT_ROOT / ".grid_artifacts"
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
DEFAULT_BATCH_MODEL = "claude-3-5-haiku-20241022"
RETRIEVAL_METHODS = ("vector", "pageindex", "graphrag", "colivara", "colqwen2", "find")
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


def colqwen2_endpoint_name() -> str:
    return os.getenv("COLQWEN2_ENDPOINT_NAME", "").strip()


def colqwen2_model_name() -> str:
    return os.getenv("COLQWEN2_MODEL_NAME", "vidore/colqwen2-v1.0").strip()


def colqwen2_image_dpi() -> int:
    return int(os.getenv("COLQWEN2_IMAGE_DPI", "144"))


def colqwen2_index_batch_size() -> int:
    return int(os.getenv("COLQWEN2_INDEX_BATCH_SIZE", "2"))


def gmail_intake_enabled() -> bool:
    return os.getenv("GRID_GMAIL_INTAKE", "0").strip() in ("1", "true", "True")


def gmail_token_file() -> str:
    return os.getenv("GRID_GMAIL_TOKEN_FILE", "").strip()


def gmail_token_ssm_param() -> str:
    """SSM Parameter Store SecureString holding gmail_token.json (used on EC2 so the
    token is read from AWS at runtime instead of being written to the instance disk)."""
    return os.getenv("GRID_GMAIL_TOKEN_SSM_PARAM", "").strip()


def gmail_query() -> str:
    return os.getenv("GRID_GMAIL_QUERY", "is:unread has:attachment").strip()


def gmail_poll_seconds() -> int:
    return int(os.getenv("GRID_GMAIL_POLL_SECONDS", "45"))


def gmail_send_acks() -> bool:
    return os.getenv("GRID_GMAIL_SEND_ACKS", "0").strip() in ("1", "true", "True")
