from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import shutil
import stat
import tempfile
import time
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from .artifacts import artifact_revision, ensure_artifacts, runtime_artifact_dir
from .models import Evidence, TraceEvent
from .retrieval import GridRetrievalRepository
from .settings import (
    DEFAULT_RETRIEVAL_METHODS,
    RETRIEVAL_METHODS,
    SUBAGENT_NAME,
    aws_region,
    model_id,
)

MAX_TOOL_ACTIONS = 28
MAX_AGENT_TURNS = 18
MAX_AGENT_BUDGET_USD = 1.0
MAX_VISIBLE_SPAN_CHARS = 4200
MAX_TOOL_IMAGES = 4
MAX_TOOL_IMAGE_BYTES = 4_000_000
SDK_FILE_TOOLS = ["Read", "Glob", "Grep"]
# Tool results can carry base64 figure image blocks. The Claude Agent SDK stdio
# transport rejects any single JSON message larger than this (SDK default 1 MiB),
# which figure-bearing tool results exceed. Raise it past the worst case
# (MAX_TOOL_IMAGES * MAX_TOOL_IMAGE_BYTES, base64-inflated ~4/3) plus headroom.
SDK_MAX_BUFFER_BYTES = int(os.getenv("GRID_SDK_MAX_BUFFER_BYTES", str(32 * 1024 * 1024)))


def resolve_claude_cli_path() -> str | None:
    import claude_agent_sdk

    bundled_cli = Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude"
    if not bundled_cli.exists():
        return None
    if os.access(bundled_cli, os.X_OK):
        return str(bundled_cli)
    try:
        bundled_cli.chmod(
            bundled_cli.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        if os.access(bundled_cli, os.X_OK):
            return str(bundled_cli)
    except OSError:
        pass
    tmp_cli = Path(tempfile.gettempdir()) / "grid-agent-core" / "claude"
    tmp_cli.parent.mkdir(parents=True, exist_ok=True)
    if not tmp_cli.exists() or tmp_cli.stat().st_size != bundled_cli.stat().st_size:
        shutil.copyfile(bundled_cli, tmp_cli)
    tmp_cli.chmod(0o755)
    return str(tmp_cli)


def normalize_methods(methods: Any) -> list[str]:
    if methods is None:
        return list(DEFAULT_RETRIEVAL_METHODS)
    if not isinstance(methods, list):
        raise ValueError("'methods' must be a list when provided.")
    selected = []
    for method in methods:
        if method not in RETRIEVAL_METHODS:
            raise ValueError(f"Unsupported retrieval method: {method}")
        if method not in selected:
            selected.append(method)
    return selected or list(DEFAULT_RETRIEVAL_METHODS)


def _search_tool_description(method: str) -> str:
    return {
        "vector": "Semantic chunk retrieval over Grid text; evidence may include optional figure metadata.",
        "pageindex": "PageIndex tree retrieval over Grid text; evidence may include optional figure metadata.",
        "graphrag": "GraphRAG retrieval over Grid entity/text-unit artifacts; evidence may include optional figure metadata.",
        "find": "Exact keyword and phrase search across Grid text; evidence may include optional figure metadata.",
    }[method]


def _system_prompt(methods: list[str], allow_sdk_file_tools: bool, enable_subagents: bool) -> str:
    subagent_note = (
        f"You may use the {SUBAGENT_NAME} subagent for independent retrieval angles. "
        "Ask it to return candidate evidence IDs and why they matter."
        if enable_subagents
        else "Subagents are disabled; perform all retrieval in the root agent."
    )
    file_note = (
        "Scoped SDK file inspection tools are enabled inside the Grid text corpus directory."
        if allow_sdk_file_tools
        else "Do not inspect arbitrary files; rely on the provided Grid retrieval tools."
    )
    return (
        "You are Grid Agents, a grounded assistant for UK grid legislation, codes, "
        "standards, engineering recommendations, and connections reform documents. "
        "Answer only from retrieved evidence. Use citations like [E1] and summarize "
        "uncertainty when evidence is weak, missing, or conflicting.\n\n"
        f"Enabled retrieval tools: {', '.join(methods)}. {subagent_note} {file_note}\n\n"
        "Before finalizing, call cite_evidence with the evidence IDs that directly "
        "support the answer. If evidence includes attached figure image blocks, use "
        "those images only when they materially clarify a chart, diagram, or figure, "
        "and cite the same evidence ID. Do not expose hidden chain-of-thought; "
        "observable tool calls and concise rationale are enough."
    )


def _text_block(text: str) -> dict[str, Any]:
    return {"type": "text", "text": text}


def _figure_text(evidence: Evidence) -> str:
    figures = evidence.metadata.get("figures")
    if not isinstance(figures, list) or not figures:
        return ""
    lines = ["", "Attached figures:"]
    for figure in figures:
        if not isinstance(figure, dict):
            continue
        location = figure.get("s3_uri") or figure.get("local_path") or figure.get("image_path") or ""
        description = str(figure.get("description") or "").strip()
        label = str(figure.get("figure_id") or figure.get("filename") or "figure")
        page = figure.get("page") or evidence.page or "?"
        lines.append(f"- {label} page {page}: {description}".rstrip())
        if location:
            lines.append(f"  image: {location}")
    return "\n" + "\n".join(lines)


def _image_blocks(evidence: Evidence, *, remaining: int) -> list[dict[str, Any]]:
    figures = evidence.metadata.get("figures")
    if not isinstance(figures, list) or remaining <= 0:
        return []
    blocks: list[dict[str, Any]] = []
    for figure in figures:
        if len(blocks) >= remaining or not isinstance(figure, dict):
            break
        path_value = figure.get("local_path") or figure.get("image_path")
        if not path_value:
            continue
        image_path = Path(str(path_value))
        if not image_path.is_absolute():
            continue
        try:
            image_bytes = image_path.read_bytes()
        except OSError:
            continue
        if not image_bytes or len(image_bytes) > MAX_TOOL_IMAGE_BYTES:
            continue
        content_type = (
            str(figure.get("content_type") or "")
            or mimetypes.guess_type(image_path.name)[0]
            or "application/octet-stream"
        )
        blocks.append(
            {
                "type": "image",
                "data": base64.b64encode(image_bytes).decode("ascii"),
                "mimeType": content_type,
            }
        )
    return blocks


class GridAgentSession:
    def __init__(
        self,
        prompt: str,
        *,
        methods: list[str] | None = None,
        allow_sdk_file_tools: bool = False,
        enable_subagents: bool = True,
        artifacts_path: Path | None = None,
        repository: GridRetrievalRepository | None = None,
    ) -> None:
        if not prompt or not prompt.strip():
            raise ValueError("Payload must include a non-empty 'prompt' string.")
        self.id = uuid.uuid4().hex
        self.prompt = prompt.strip()
        self.methods = normalize_methods(methods)
        self.allow_sdk_file_tools = allow_sdk_file_tools
        self.enable_subagents = enable_subagents
        self.artifacts_path = artifacts_path or ensure_artifacts(runtime_artifact_dir())
        self.repository = repository or GridRetrievalRepository(self.artifacts_path)
        self.revision = artifact_revision(self.artifacts_path)
        self.created_at = time.monotonic()
        self.sequence = 0
        self.trajectory: list[TraceEvent] = []
        self.evidence: dict[str, Evidence] = {}
        self.cited_ids: list[str] = []
        self.tool_actions = 0
        self.answer = ""
        self.failures: list[str] = []
        self._pending: list[dict[str, Any]] = []

    def trace(
        self,
        kind: str,
        title: str,
        detail: str,
        metadata: dict[str, Any] | None = None,
        *,
        queue: bool = False,
    ) -> dict[str, Any]:
        self.sequence += 1
        event = TraceEvent(
            id=self.sequence,
            kind=kind,
            title=title,
            detail=detail,
            metadata=metadata or {},
        )
        self.trajectory.append(event)
        payload = {"type": "trace", "entry": event.to_dict()}
        if queue:
            self._pending.append(payload)
        return payload

    def drain_pending(self) -> list[dict[str, Any]]:
        pending = self._pending
        self._pending = []
        return pending

    def final_event(self, *, status: str = "completed") -> dict[str, Any]:
        citations = [
            self.evidence[evidence_id].to_dict()
            for evidence_id in self.cited_ids
            if evidence_id in self.evidence
        ]
        return {
            "type": "result",
            "status": status,
            "answer": self.answer,
            "citations": citations,
            "evidence": [item.to_dict() for item in self.evidence.values()],
            "trajectory": [event.to_dict() for event in self.trajectory],
            "latency_ms": round((time.monotonic() - self.created_at) * 1000),
            "model": model_id(),
            "artifact_revision": self.revision,
            "methods": self.methods,
            "allow_sdk_file_tools": self.allow_sdk_file_tools,
            "enable_subagents": self.enable_subagents,
            "errors": self.failures,
        }

    def _next_evidence_id(self) -> str:
        return f"E{len(self.evidence) + 1}"

    async def search(self, method: str, query: str) -> tuple[list[dict[str, Any]], bool]:
        if self.tool_actions >= MAX_TOOL_ACTIONS:
            return [_text_block("Tool action limit reached; answer with existing evidence.")], True
        self.tool_actions += 1
        if method not in self.methods:
            return [_text_block(f"Retrieval method {method!r} is disabled for this run.")], True
        try:
            results = self.repository.search(method, query, top_k=8)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.failures.append(f"{method}: {error}")
            self.trace("error", f"{method} failed", error, queue=True)
            return [_text_block(error)], True

        visible = []
        ids = []
        image_blocks: list[dict[str, Any]] = []
        for result in results:
            evidence_id = self._next_evidence_id()
            result.id = evidence_id
            self.evidence[evidence_id] = result
            ids.append(evidence_id)
            figure_text = _figure_text(result)
            visible.append(
                f"{evidence_id} {result.title} page {result.page or '?'} "
                f"score={result.score:.3f}\n{result.span_text[:MAX_VISIBLE_SPAN_CHARS]}"
                f"{figure_text}"
            )
            if len(image_blocks) < MAX_TOOL_IMAGES:
                image_blocks.extend(
                    _image_blocks(result, remaining=MAX_TOOL_IMAGES - len(image_blocks))
                )
        self.trace(
            "retrieval",
            f"Searched {method}",
            query,
            {"evidence_ids": ids, "span_count": len(ids)},
            queue=True,
        )
        return [_text_block("\n\n".join(visible) or "No evidence found."), *image_blocks], False

    async def inspect(self, evidence_id: str) -> tuple[str, bool]:
        evidence = self.evidence.get(evidence_id.strip())
        if not evidence:
            return f"Unknown evidence ID: {evidence_id}", True
        self.trace("inspect", f"Inspected {evidence.id}", evidence.title, queue=True)
        return json.dumps(evidence.to_dict(), ensure_ascii=False), False

    async def cite(self, evidence_ids: str) -> tuple[str, bool]:
        requested = []
        for part in evidence_ids.replace(";", ",").split(","):
            part = part.strip()
            if part in self.evidence and part not in requested:
                requested.append(part)
        if not requested:
            return "Provide existing evidence IDs, such as E1,E3.", True
        self.cited_ids = requested
        self.trace("citation", "Selected final evidence", ", ".join(requested), queue=True)
        return f"Accepted citations: {', '.join(requested)}", False

    def _tools(self) -> list[Any]:
        from claude_agent_sdk import tool

        tools = []

        def make_search_tool(method: str) -> Any:
            @tool(f"{method}_search", _search_tool_description(method), {"query": str})
            async def search_tool(arguments: dict[str, Any]) -> dict[str, Any]:
                content, is_error = await self.search(method, str(arguments.get("query", "")))
                return {"content": content, "is_error": is_error}

            return search_tool

        for method in self.methods:
            tools.append(make_search_tool(method))

        @tool("inspect_evidence", "Read one retrieved evidence item in full.", {"evidence_id": str})
        async def inspect_tool(arguments: dict[str, Any]) -> dict[str, Any]:
            content, is_error = await self.inspect(str(arguments.get("evidence_id", "")))
            return {"content": [{"type": "text", "text": content}], "is_error": is_error}

        @tool("cite_evidence", "Select final citation evidence IDs, comma-separated.", {"evidence_ids": str})
        async def cite_tool(arguments: dict[str, Any]) -> dict[str, Any]:
            content, is_error = await self.cite(str(arguments.get("evidence_ids", "")))
            return {"content": [{"type": "text", "text": content}], "is_error": is_error}

        return [*tools, inspect_tool, cite_tool]

    def _mcp_tool_names(self) -> list[str]:
        return [
            *[f"mcp__grid_retrieval__{method}_search" for method in self.methods],
            "mcp__grid_retrieval__inspect_evidence",
            "mcp__grid_retrieval__cite_evidence",
        ]

    def _subagents(self) -> dict[str, Any]:
        from claude_agent_sdk import AgentDefinition

        return {
            SUBAGENT_NAME: AgentDefinition(
                description="Grid document span retrieval specialist.",
                prompt=(
                    "You are a focused Grid document retrieval subagent. Use enabled "
                    "retrieval tools to find candidate evidence IDs, pages, and exact "
                    "spans. If evidence has attached figure images, inspect them only "
                    "when they clarify a chart, diagram, or visual requirement. Return a "
                    "compact report; the root agent handles citations."
                ),
                tools=[
                    *[f"mcp__grid_retrieval__{method}_search" for method in self.methods],
                    "mcp__grid_retrieval__inspect_evidence",
                ],
                mcpServers=["grid_retrieval"],
                model=model_id(),
                maxTurns=6,
                permissionMode="dontAsk",
            )
        }

    def _options(self) -> Any:
        from claude_agent_sdk import ClaudeAgentOptions, create_sdk_mcp_server

        server = create_sdk_mcp_server(
            name="grid_retrieval", version="1.0.0", tools=self._tools()
        )
        tools = []
        allowed = self._mcp_tool_names()
        disallowed = ["Bash", "Write", "Edit", "WebFetch", "WebSearch"]
        agents = None
        if self.enable_subagents:
            tools.append("Agent")
            allowed.extend(["Agent", "Task"])
            agents = self._subagents()
        if self.allow_sdk_file_tools:
            tools.extend(SDK_FILE_TOOLS)
            allowed.extend(["Read(./**)", "Glob(./**)", "Grep(./**)"])
        else:
            disallowed.extend(SDK_FILE_TOOLS)
        return ClaudeAgentOptions(
            tools=tools,
            allowed_tools=allowed,
            disallowed_tools=disallowed,
            mcp_servers={"grid_retrieval": server},
            strict_mcp_config=True,
            permission_mode="dontAsk",
            system_prompt=_system_prompt(
                self.methods, self.allow_sdk_file_tools, self.enable_subagents
            ),
            max_turns=MAX_AGENT_TURNS,
            max_budget_usd=MAX_AGENT_BUDGET_USD,
            max_buffer_size=SDK_MAX_BUFFER_BYTES,
            model=model_id(),
            agents=agents,
            setting_sources=[],
            cwd=self.artifacts_path / "corpus" / "grid",
            cli_path=resolve_claude_cli_path(),
        )

    async def run(self) -> AsyncIterator[dict[str, Any]]:
        os.environ.setdefault("CLAUDE_CODE_USE_BEDROCK", "1")
        os.environ.setdefault("AWS_REGION", aws_region())
        yield self.trace("user", "Grid question", self.prompt)
        try:
            from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, ToolUseBlock, query

            prompt = (
                f"Question: {self.prompt}\n\n"
                f"Enabled methods: {', '.join(self.methods)}.\n"
                f"Subagents enabled: {self.enable_subagents}.\n"
                "Search, inspect, cite, then answer with inline citations."
            )
            answer_parts: list[str] = []
            async for message in query(prompt=prompt, options=self._options()):
                if isinstance(message, AssistantMessage):
                    parent_tool_use_id = str(getattr(message, "parent_tool_use_id", "") or "")
                    role = "subagent" if parent_tool_use_id else "agent"
                    for block in message.content:
                        if isinstance(block, TextBlock) and block.text.strip():
                            if not parent_tool_use_id:
                                answer_parts.append(block.text.strip())
                            yield self.trace(
                                role,
                                "Subagent" if parent_tool_use_id else "Claude",
                                block.text.strip(),
                                {"parent_tool_use_id": parent_tool_use_id} if parent_tool_use_id else {},
                            )
                        elif isinstance(block, ToolUseBlock):
                            is_subagent = block.name in {"Agent", "Task"}
                            yield self.trace(
                                "subagent-call" if is_subagent else "tool-call",
                                f"Requested {block.name}",
                                json.dumps(block.input, sort_keys=True),
                                {"tool_use_id": str(getattr(block, "id", "") or "")},
                            )
                elif isinstance(message, ResultMessage):
                    for pending in self.drain_pending():
                        yield pending
                    self.answer = "\n\n".join(answer_parts) or str(message.result or "")
                    status = "completed" if self.cited_ids and not message.is_error else "insufficient_evidence"
                    if message.is_error:
                        status = "error"
                        self.failures.append(f"SDK result subtype: {message.subtype}")
                    yield self.trace(
                        "result",
                        f"Result: {status}",
                        f"SDK subtype: {message.subtype}; turns: {message.num_turns}.",
                    )
                    yield self.final_event(status=status)
                    return
                for pending in self.drain_pending():
                    yield pending
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            self.failures.append(error)
            yield self.trace("error", "Run failed", error)
            yield self.final_event(status="error")


async def run_grid_agent_events(payload: dict[str, Any]) -> AsyncIterator[dict[str, Any]]:
    session = GridAgentSession(
        prompt=str(payload.get("prompt", "")),
        methods=normalize_methods(payload.get("methods")),
        allow_sdk_file_tools=bool(payload.get("allow_sdk_file_tools", False)),
        enable_subagents=bool(payload.get("enable_subagents", True)),
    )
    async for event in session.run():
        yield event


def run_grid_agent(payload: dict[str, Any]) -> dict[str, Any]:
    async def collect() -> dict[str, Any]:
        final: dict[str, Any] | None = None
        async for event in run_grid_agent_events(payload):
            if event.get("type") == "result":
                final = event
        if final is None:
            raise RuntimeError("Grid agent did not return a result event.")
        return final

    return asyncio.run(collect())
