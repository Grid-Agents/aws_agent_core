from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import claude_agent_sdk
from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)


DEFAULT_SYSTEM_PROMPT = (
    "You are a concise, helpful chatbot. Answer directly and ask clarifying "
    "questions when the user's request is unclear."
)
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def resolve_claude_cli_path() -> str | None:
    bundled_cli = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if not bundled_cli.exists():
        return None
    if os.access(bundled_cli, os.X_OK):
        return str(bundled_cli)

    try:
        executable_mode = (
            bundled_cli.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        bundled_cli.chmod(executable_mode)
        if os.access(bundled_cli, os.X_OK):
            return str(bundled_cli)
    except OSError:
        pass

    # AgentCore CodeZip can strip executable bits; /tmp is writable in the runtime.
    tmp_cli = Path(tempfile.gettempdir()) / "simple-agent-core" / "claude"
    tmp_cli.parent.mkdir(parents=True, exist_ok=True)
    if not tmp_cli.exists() or tmp_cli.stat().st_size != bundled_cli.stat().st_size:
        shutil.copyfile(bundled_cli, tmp_cli)
    tmp_cli.chmod(0o755)
    return str(tmp_cli)


def build_options() -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        system_prompt=os.getenv("AGENT_SYSTEM_PROMPT", DEFAULT_SYSTEM_PROMPT),
        model=os.getenv("ANTHROPIC_MODEL", DEFAULT_MODEL_ID),
        tools=[],
        allowed_tools=[],
        setting_sources=[],
        cli_path=resolve_claude_cli_path(),
    )


async def collect_text(messages: AsyncIterator[Any]) -> str:
    chunks: list[str] = []
    result_text = ""

    async for message in messages:
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    chunks.append(block.text)
        elif isinstance(message, ResultMessage) and message.result:
            result_text = message.result

    response = "".join(chunks).strip() or result_text.strip()
    if not response:
        raise RuntimeError("Claude Agent SDK completed without returning text.")
    return response


async def ask_claude(prompt: str) -> str:
    if not prompt or not prompt.strip():
        raise ValueError("Payload must include a non-empty 'prompt' string.")

    os.environ.setdefault("CLAUDE_CODE_USE_BEDROCK", "1")
    os.environ.setdefault("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-west-2"))

    return await collect_text(query(prompt=prompt.strip(), options=build_options()))
