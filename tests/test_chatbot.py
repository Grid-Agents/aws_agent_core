from __future__ import annotations

import asyncio
import os

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from chatbot import ask_claude, collect_text, resolve_claude_cli_path


async def text_messages():
    yield AssistantMessage(
        content=[TextBlock("hello"), TextBlock(" world")],
        model="test-model",
    )


async def empty_messages():
    if False:
        yield None


def test_collect_text_returns_assistant_text() -> None:
    assert asyncio.run(collect_text(text_messages())) == "hello world"


def test_ask_claude_rejects_blank_prompt() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        asyncio.run(ask_claude(" "))


def test_collect_text_requires_a_response() -> None:
    with pytest.raises(RuntimeError, match="without returning text"):
        asyncio.run(collect_text(empty_messages()))


def test_resolve_claude_cli_path_restores_execute_bit(tmp_path, monkeypatch) -> None:
    package_dir = tmp_path / "claude_agent_sdk"
    bundled_dir = package_dir / "_bundled"
    bundled_dir.mkdir(parents=True)
    cli = bundled_dir / "claude"
    cli.write_text("#!/bin/sh\n", encoding="utf-8")
    cli.chmod(0o600)

    monkeypatch.setattr("chatbot.claude_agent_sdk.__file__", str(package_dir / "__init__.py"))

    resolved = resolve_claude_cli_path()

    assert resolved == str(cli)
    assert os.access(cli, os.X_OK)
