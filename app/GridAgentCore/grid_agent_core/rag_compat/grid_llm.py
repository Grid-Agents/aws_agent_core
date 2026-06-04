from __future__ import annotations

import json
import os
from typing import Any

from .llm import AnthropicLLM
from .types import LLMResponse, Usage
from ..settings import aws_region, model_id


class BedrockLLM:
    """PageIndex-compatible LLM wrapper backed by Amazon Bedrock."""

    def __init__(self, cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        self.model = str(cfg.get("model") or model_id())
        self.max_tokens = int(cfg.get("max_tokens", 700))
        self.temperature = float(cfg.get("temperature", 0.0))
        self.client = _bedrock_client()

    def complete(
        self,
        *,
        system: str,
        user: str,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": self.temperature if temperature is None else temperature,
            "system": system,
            "messages": [{"role": "user", "content": [{"type": "text", "text": user}]}],
        }
        response = self.client.invoke_model(
            modelId=self.model,
            body=json.dumps(body).encode("utf-8"),
            contentType="application/json",
            accept="application/json",
        )
        payload = json.loads(response["body"].read())
        text = "".join(
            str(block.get("text", ""))
            for block in payload.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        usage = payload.get("usage") or {}
        return LLMResponse(
            text=text,
            usage=Usage(
                input_tokens=int(usage.get("input_tokens", 0) or 0),
                output_tokens=int(usage.get("output_tokens", 0) or 0),
            ),
        )


def make_pageindex_llm(cfg: dict[str, Any] | None = None) -> Any:
    if os.getenv("ANTHROPIC_API_KEY"):
        return AnthropicLLM(cfg or {})
    return BedrockLLM(cfg or {})


def _bedrock_client() -> Any:
    try:
        import boto3
    except ModuleNotFoundError as exc:  # pragma: no cover - dependency check
        raise RuntimeError("boto3 is required for Bedrock-backed PageIndex selection.") from exc
    return boto3.client("bedrock-runtime", region_name=aws_region())
