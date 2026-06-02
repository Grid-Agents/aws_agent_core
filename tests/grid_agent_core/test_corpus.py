from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from grid_agent_core import corpus
from grid_agent_core import llama_parse_agentic
from grid_agent_core import multimodal_enrichment
from grid_agent_core.llama_parse_agentic import LlamaParseResult, ParsedPage
from grid_agent_core.multimodal_enrichment import VisualArtifact, _clean_description


class FakePage:
    def __init__(self, text: str) -> None:
        self._text = text

    def extract_text(self) -> str:
        return self._text


class FakeReader:
    def __init__(self, _path: str) -> None:
        self.pages = [FakePage("first page obligation"), FakePage("second page limit")]


@pytest.fixture(autouse=True)
def _disable_multimodal_enrichment_env(monkeypatch) -> None:
    monkeypatch.delenv("GRID_MULTIMODAL_ENRICH", raising=False)


def test_build_corpus_manifest_and_page_offsets(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "Grid Docs"
    category_dir = source_dir / "02 - Industry Codes"
    category_dir.mkdir(parents=True)
    pdf_path = category_dir / "Grid Code.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    monkeypatch.setattr(corpus, "PdfReader", FakeReader)

    records = corpus.build_corpus(source_dir, tmp_path / "artifacts", force=True)

    assert len(records) == 1
    record = records[0]
    assert record.document_id == "grid/02-industry-codes-grid-code.txt"
    assert record.category == "02 - Industry Codes"
    assert len(record.pages) == 2
    text = (tmp_path / "artifacts" / record.text_path).read_text(encoding="utf-8")
    assert text[record.pages[0].start_char : record.pages[0].end_char].startswith("[Page 1]")
    assert text[record.pages[1].start_char : record.pages[1].end_char].startswith("[Page 2]")
    assert "second page limit" in text[record.pages[1].start_char : record.pages[1].end_char]
    assert corpus.load_manifest(tmp_path / "artifacts")[0].source_sha256 == record.source_sha256
    metadata = tmp_path / "artifacts" / "source_document_metadata.json"
    assert metadata.exists()
    assert '"document_count": 1' in metadata.read_text(encoding="utf-8")


def test_build_corpus_can_use_llamaparse_agentic(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "Grid Docs"
    category_dir = source_dir / "02 - Industry Codes"
    category_dir.mkdir(parents=True)
    pdf_path = category_dir / "Grid Code.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")

    def fake_parse(_path: Path, **_kwargs) -> LlamaParseResult:
        return LlamaParseResult(
            pages=[
                ParsedPage(page=1, markdown="![diagram](image_0.png) Gate 2 diagram text"),
                ParsedPage(page=2, markdown="table markdown from image-heavy page"),
            ],
            raw_payload={
                "job_id": "job-1",
                "num_pages": 2,
            },
        )

    monkeypatch.setattr(corpus, "parse_pdf_agentic", fake_parse)

    records = corpus.build_corpus(
        source_dir,
        tmp_path / "artifacts",
        force=True,
        parser="llamaparse-agentic",
    )

    record = records[0]
    text = (tmp_path / "artifacts" / record.text_path).read_text(encoding="utf-8")
    raw_parse = (
        tmp_path
        / "artifacts"
        / "parse_resume_cache"
        / "llamaparse_agentic"
        / "grid"
        / "02-industry-codes-grid-code.raw.json"
    )
    assert "Gate 2 diagram text" in text
    assert len(record.pages) == 2
    assert record.figures == []
    assert raw_parse.exists()


def test_build_corpus_can_multimodal_enrich_llamaparse_output(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "Grid Docs"
    category_dir = source_dir / "02 - Industry Codes"
    category_dir.mkdir(parents=True)
    pdf_path = category_dir / "Grid Code.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    image_bytes = b"\xff\xd8\xff\xd9"

    def fake_parse(_path: Path, **_kwargs) -> LlamaParseResult:
        return LlamaParseResult(
            pages=[ParsedPage(page=1, markdown="Base parsed page")],
            raw_payload={"job_id": "job-1", "num_pages": 1},
        )

    def fake_enrich(_pdf_path, *, parsed_pages, artifact_dir, document_key, **_kwargs):
        image_path = Path("figures") / "grid" / document_key / "page-0001-visual.jpg"
        target = artifact_dir / image_path
        target.parent.mkdir(parents=True)
        target.write_bytes(image_bytes)
        return (
            [
                (
                    1,
                    (
                        "Base parsed page\n\n"
                        "### Visual context - page 1\n\n"
                        "The page contains a material connection-process diagram.\n\n"
                        f"![Page 1 visual context]({image_path.as_posix()})"
                    ),
                )
            ],
            [
                VisualArtifact(
                    page=1,
                    description="The page contains a material connection-process diagram.",
                    image_path=image_path.as_posix(),
                    image_sha256=corpus.sha256_bytes(image_bytes),
                    filename="page-0001-visual.jpg",
                    content_type="image/jpeg",
                    size_bytes=len(image_bytes),
                )
            ],
        )

    monkeypatch.setattr(corpus, "parse_pdf_agentic", fake_parse)
    monkeypatch.setattr(corpus, "enrich_page_markdown_with_visuals", fake_enrich)

    records = corpus.build_corpus(
        source_dir,
        tmp_path / "artifacts",
        force=True,
        parser="llamaparse-agentic",
        multimodal_enrich=True,
    )

    record = records[0]
    text = (tmp_path / "artifacts" / record.text_path).read_text(encoding="utf-8")
    assert "### Visual context - page 1" in text
    assert "connection-process diagram" in text
    assert len(record.figures) == 1
    assert record.figures[0].description == "The page contains a material connection-process diagram."
    assert record.figures[0].start_char == record.pages[0].start_char
    assert record.figures[0].end_char == record.pages[0].end_char
    assert (tmp_path / "artifacts" / record.figures[0].image_path).read_bytes() == image_bytes


def test_multimodal_enrichment_skips_simple_definition_tables() -> None:
    raw = (
        '{"material_visual_content": true, "description": '
        '"The page contains a structured glossary table with term names on the left '
        'and definitions on the right. The table defines key Grid Code terms."}'
    )

    assert _clean_description(raw) == ""


def test_multimodal_enrichment_page_cache_resumes_visual_and_skip_pages(
    tmp_path, monkeypatch, capsys
) -> None:
    artifact_dir = tmp_path / "artifacts"
    cache_dir = tmp_path / "cache"
    image_bytes = b"\xff\xd8\xffcached"
    calls = []

    class FakeDescriber:
        def describe_page(self, *, image_bytes, page_number, page_markdown):
            calls.append(page_number)
            if page_number == 1:
                return (
                    '{"material_visual_content": true, "description": '
                    '"The page contains a material one-line process diagram."}'
                )
            return '{"material_visual_content": false, "description": ""}'

    class RaisingDescriber:
        def describe_page(self, **_kwargs):
            raise AssertionError("VLM should not be called when visual cache is valid.")

    monkeypatch.setattr(
        multimodal_enrichment,
        "render_pdf_page_jpeg",
        lambda *_args, **_kwargs: image_bytes,
    )
    parsed_pages = [(1, "Base visual page"), (2, "Plain definition page")]

    enriched, artifacts = multimodal_enrichment.enrich_page_markdown_with_visuals(
        tmp_path / "doc.pdf",
        parsed_pages=parsed_pages,
        artifact_dir=artifact_dir,
        document_key="doc",
        describer=FakeDescriber(),
        cache_dir=cache_dir,
        show_progress=True,
    )

    assert sorted(calls) == [1, 2]
    assert len(artifacts) == 1
    assert "### Visual context - page 1" in enriched[0][1]
    assert "### Visual context" not in enriched[1][1]
    assert "VLM visual enrichment" in capsys.readouterr().err

    cached_enriched, cached_artifacts = multimodal_enrichment.enrich_page_markdown_with_visuals(
        tmp_path / "doc.pdf",
        parsed_pages=parsed_pages,
        artifact_dir=artifact_dir,
        document_key="doc",
        describer=RaisingDescriber(),
        cache_dir=cache_dir,
    )

    assert len(cached_artifacts) == 1
    assert cached_artifacts[0].image_sha256 == artifacts[0].image_sha256
    assert cached_enriched == enriched


def test_multimodal_enrichment_runs_vlm_pages_in_parallel(tmp_path, monkeypatch) -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()

    class SlowDescriber:
        def describe_page(self, *, image_bytes, page_number, page_markdown):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.05)
                return (
                    '{"material_visual_content": true, "description": '
                    f'"The page contains material diagram {page_number}."}}'
                )
            finally:
                with lock:
                    active -= 1

    monkeypatch.setattr(
        multimodal_enrichment,
        "render_pdf_page_jpeg",
        lambda *_args, **_kwargs: b"\xff\xd8\xffparallel",
    )

    enriched, artifacts = multimodal_enrichment.enrich_page_markdown_with_visuals(
        tmp_path / "doc.pdf",
        parsed_pages=[(1, "page one"), (2, "page two"), (3, "page three"), (4, "page four")],
        artifact_dir=tmp_path / "artifacts",
        document_key="doc",
        describer=SlowDescriber(),
        vlm_concurrency=4,
    )

    assert max_active > 1
    assert [page for page, _markdown in enriched] == [1, 2, 3, 4]
    assert [artifact.page for artifact in artifacts] == [1, 2, 3, 4]


def test_multimodal_enrichment_respects_shared_vlm_limiter(tmp_path, monkeypatch) -> None:
    active = 0
    max_active = 0
    lock = threading.Lock()

    class SlowDescriber:
        def describe_page(self, *, image_bytes, page_number, page_markdown):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                time.sleep(0.02)
                return (
                    '{"material_visual_content": true, "description": '
                    f'"The page contains material diagram {page_number}."}}'
                )
            finally:
                with lock:
                    active -= 1

    monkeypatch.setattr(
        multimodal_enrichment,
        "render_pdf_page_jpeg",
        lambda *_args, **_kwargs: b"\xff\xd8\xfflimited",
    )

    enriched, artifacts = multimodal_enrichment.enrich_page_markdown_with_visuals(
        tmp_path / "doc.pdf",
        parsed_pages=[(1, "page one"), (2, "page two"), (3, "page three")],
        artifact_dir=tmp_path / "artifacts",
        document_key="doc",
        describer=SlowDescriber(),
        vlm_concurrency=3,
        vlm_limiter=threading.BoundedSemaphore(1),
    )

    assert max_active == 1
    assert [page for page, _markdown in enriched] == [1, 2, 3]
    assert [artifact.page for artifact in artifacts] == [1, 2, 3]


def test_anthropic_vision_describer_uses_direct_api_and_model_max_tokens(monkeypatch) -> None:
    captured = {}

    class FakeModelInfo:
        max_tokens = 64000

    class FakeModels:
        def retrieve(self, model):
            captured["model_lookup"] = model
            return FakeModelInfo()

    class FakeMessages:
        def create(self, **kwargs):
            captured["request"] = kwargs
            return {
                "content": [
                    {
                        "text": (
                            '{"material_visual_content": false, '
                            '"description": ""}'
                        )
                    }
                ]
            }

    class FakeClient:
        def __init__(self, *, api_key):
            captured["api_key"] = api_key
            self.models = FakeModels()
            self.messages = FakeMessages()

    class FakeAnthropicModule:
        Anthropic = FakeClient

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "us.anthropic.claude-sonnet-4-5-20250929-v1:0")
    monkeypatch.setattr(
        multimodal_enrichment,
        "model_id",
        lambda: "us.anthropic.claude-sonnet-4-5-20250929-v1:0",
    )
    monkeypatch.setitem(sys.modules, "anthropic", FakeAnthropicModule)

    describer = multimodal_enrichment.AnthropicVisionDescriber()

    assert describer.describe_page(
        image_bytes=b"\xff\xd8\xffimage",
        page_number=1,
        page_markdown="plain page",
    )
    assert captured["api_key"] == "test-key"
    assert captured["model_lookup"] == "claude-sonnet-4-5-20250929"
    request = captured["request"]
    assert request["model"] == "claude-sonnet-4-5-20250929"
    assert request["max_tokens"] == 64000
    assert request["temperature"] == 0
    content = request["messages"][0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1]["type"] == "text"


def test_anthropic_vision_describer_retries_rate_limits(monkeypatch) -> None:
    calls = 0

    class FakeMessages:
        def create(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("rate_limit_error: Too many requests")
            return {
                "content": [
                    {
                        "text": (
                            '{"material_visual_content": false, '
                            '"description": ""}'
                        )
                    }
                ]
            }

    describer = multimodal_enrichment.AnthropicVisionDescriber.__new__(
        multimodal_enrichment.AnthropicVisionDescriber
    )
    describer.model = "test-model"
    describer.client = type("FakeClient", (), {"messages": FakeMessages()})()
    describer.max_tokens = 64000
    describer.max_retries = 1
    describer.retry_base_seconds = 0
    monkeypatch.setattr(multimodal_enrichment.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(multimodal_enrichment.random, "uniform", lambda _a, _b: 0)

    assert describer.describe_page(
        image_bytes=b"image",
        page_number=1,
        page_markdown="plain page",
    )
    assert calls == 2


def test_build_corpus_parses_documents_in_parallel_and_preserves_order(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "Grid Docs"
    category_dir = source_dir / "02 - Industry Codes"
    category_dir.mkdir(parents=True)
    first_pdf = category_dir / "A First.pdf"
    second_pdf = category_dir / "B Second.pdf"
    first_pdf.write_bytes(b"%PDF-first")
    second_pdf.write_bytes(b"%PDF-second")
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_build_document_record(pdf_path, _artifact_dir, _parse_dir, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            if pdf_path.name == "A First.pdf":
                time.sleep(0.05)
            return corpus.DocumentRecord(
                document_id=f"grid/{pdf_path.stem}.txt",
                title=pdf_path.stem,
                category=pdf_path.parent.name,
                filename=pdf_path.name,
                source_path=f"raw/{pdf_path.name}",
                text_path=f"corpus/grid/{pdf_path.stem}.txt",
                source_sha256=corpus.sha256_bytes(pdf_path.read_bytes()),
                text_sha256=corpus.sha256_text(pdf_path.name),
                pages=[],
                figures=[],
            )
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(corpus, "_build_document_record", fake_build_document_record)

    records = corpus.build_corpus(
        source_dir,
        tmp_path / "artifacts",
        force=True,
        document_concurrency=4,
    )

    assert max_active > 1
    assert [record.filename for record in records] == ["A First.pdf", "B Second.pdf"]


def test_build_corpus_resumes_completed_llamaparse_document(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "Grid Docs"
    category_dir = source_dir / "02 - Industry Codes"
    category_dir.mkdir(parents=True)
    pdf_path = category_dir / "Grid Code.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")

    calls = 0

    def fake_parse(_path: Path, **_kwargs) -> LlamaParseResult:
        nonlocal calls
        calls += 1
        return LlamaParseResult(
            pages=[ParsedPage(page=1, markdown="parsed once")],
            raw_payload={
                "job_id": "job-1",
                "num_pages": 1,
            },
        )

    monkeypatch.setattr(corpus, "parse_pdf_agentic", fake_parse)
    artifact_dir = tmp_path / "artifacts"

    corpus.build_corpus(
        artifact_dir=artifact_dir,
        source_dir=source_dir,
        force=True,
        parser="llamaparse-agentic",
    )
    corpus.build_corpus(
        artifact_dir=artifact_dir,
        source_dir=source_dir,
        force=True,
        parser="llamaparse-agentic",
    )

    assert calls == 1


def test_build_corpus_reparses_legacy_llamaparse_artifacts_for_figures(tmp_path, monkeypatch) -> None:
    source_dir = tmp_path / "Grid Docs"
    category_dir = source_dir / "02 - Industry Codes"
    category_dir.mkdir(parents=True)
    pdf_path = category_dir / "Grid Code.pdf"
    source_bytes = b"%PDF-fixture"
    pdf_path.write_bytes(source_bytes)
    artifact_dir = tmp_path / "artifacts"
    document_id = "02-industry-codes-grid-code"
    text = "[Page 1]\nlegacy parsed text\n"
    (artifact_dir / "corpus" / "grid").mkdir(parents=True)
    (artifact_dir / "corpus" / "grid" / f"{document_id}.txt").write_text(text, encoding="utf-8")
    (artifact_dir / "raw" / "02 - Industry Codes").mkdir(parents=True)
    (artifact_dir / "raw" / "02 - Industry Codes" / "Grid Code.pdf").write_bytes(source_bytes)
    (artifact_dir / "parse" / "llamaparse_agentic" / "grid").mkdir(parents=True)
    (
        artifact_dir / "parse" / "llamaparse_agentic" / "grid" / f"{document_id}.raw.json"
    ).write_text('{"job_id":"legacy"}', encoding="utf-8")

    calls = 0

    def fake_parse(_path: Path, **_kwargs) -> LlamaParseResult:
        nonlocal calls
        calls += 1
        return LlamaParseResult(
            pages=[ParsedPage(page=1, markdown="new parsebench-compatible parse")],
            raw_payload={
                "job_id": "new",
                "num_pages": 1,
            },
        )

    monkeypatch.setattr(corpus, "parse_pdf_agentic", fake_parse)

    records = corpus.build_corpus(
        artifact_dir=artifact_dir,
        source_dir=source_dir,
        force=True,
        parser="llamaparse-agentic",
    )

    assert calls == 1
    assert "new parsebench-compatible parse" in (
        artifact_dir / records[0].text_path
    ).read_text(encoding="utf-8")
    assert (artifact_dir / "manifest.jsonl").exists()
    assert (artifact_dir / "parse_resume_cache" / "llamaparse_agentic" / "grid").exists()


def test_smoke_flag_targets_full_grid_code(tmp_path, monkeypatch, capsys) -> None:
    source_dir = tmp_path / "Grid Docs"
    full_grid_code = source_dir / "02 - Industry Codes" / "00_The_Full_Grid_Code.pdf"
    full_grid_code.parent.mkdir(parents=True)
    full_grid_code.write_bytes(b"%PDF-fixture")
    captured = {}

    def fake_build_corpus(source_dir_arg, artifact_dir_arg, **kwargs):
        captured["source_dir"] = source_dir_arg
        captured["artifact_dir"] = artifact_dir_arg
        captured.update(kwargs)
        return []

    monkeypatch.setattr(corpus, "build_corpus", fake_build_corpus)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "grid-parse-documents",
            "--source-dir",
            str(source_dir),
            "--smoke-full-grid-code",
            "--smoke-page-range",
            "3-5",
            "--multimodal-enrich",
            "--no-progress",
        ],
    )

    corpus.main()

    assert captured["source_dir"] == source_dir
    assert captured["artifact_dir"] == corpus.DEFAULT_SMOKE_ARTIFACT_DIR
    assert captured["parser"] == "llamaparse-agentic"
    assert captured["pdf_paths"] == [full_grid_code]
    assert captured["llamaparse_page_range"] == (3, 5)
    assert captured["multimodal_enrich"] is True
    assert captured["show_progress"] is False
    assert "Running Full Grid Code smoke parse" in capsys.readouterr().out


def test_llamaparse_partitions_large_pdf(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "large.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    written_ranges = []

    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "test-key")
    monkeypatch.setattr(llama_parse_agentic, "_llama_client", lambda: object())
    monkeypatch.setattr(llama_parse_agentic, "_pdf_page_count", lambda _path: 1001)

    def fake_write_partition(_source_path, target_path, *, start_page: int, end_page: int) -> None:
        written_ranges.append((start_page, end_page))
        target_path.write_bytes(b"%PDF-partition")

    def fake_parse_payload(_client, path, *, timeout: float) -> dict:
        return {
            "job_id": path.stem,
            "pages": [{"page": 1, "md": f"parsed {path.stem}"}],
        }

    monkeypatch.setattr(llama_parse_agentic, "_write_pdf_partition", fake_write_partition)
    monkeypatch.setattr(llama_parse_agentic, "_parse_pdf_job_payload", fake_parse_payload)

    result = llama_parse_agentic.parse_pdf_agentic(pdf_path, max_pages_per_job=1000)

    assert written_ranges == [(1, 1000), (1001, 1001)]
    assert [page.page for page in result.pages] == [1, 1001]
    assert result.raw_payload["partition_count"] == 2


def test_llamaparse_target_page_range_parses_only_requested_pages(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "large.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    written_ranges = []

    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "test-key")
    monkeypatch.setattr(llama_parse_agentic, "_llama_client", lambda: object())
    monkeypatch.setattr(llama_parse_agentic, "_pdf_page_count", lambda _path: 20)

    def fake_write_partition(_source_path, target_path, *, start_page: int, end_page: int) -> None:
        written_ranges.append((start_page, end_page))
        target_path.write_bytes(b"%PDF-partition")

    def fake_parse_payload(_client, path, *, timeout: float) -> dict:
        assert path.name == "large.pages-3-5.pdf"
        return {
            "job_id": path.stem,
            "pages": [
                {"page": 1, "md": "parsed local page 1"},
                {"page": 2, "md": "parsed local page 2"},
            ],
        }

    monkeypatch.setattr(llama_parse_agentic, "_write_pdf_partition", fake_write_partition)
    monkeypatch.setattr(llama_parse_agentic, "_parse_pdf_job_payload", fake_parse_payload)

    result = llama_parse_agentic.parse_pdf_agentic(
        pdf_path,
        target_page_range=(3, 5),
    )

    assert written_ranges == [(3, 5)]
    assert [page.page for page in result.pages] == [3, 4]
    assert result.raw_payload["target_page_range"] == "3-5"


def test_llamaparse_job_payload_matches_parsebench_agentic(tmp_path) -> None:
    pdf_path = tmp_path / "doc.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    calls = {}

    class FakeJob:
        id = "job-1"

    class FakeResult:
        def model_dump(self, *, mode: str, by_alias: bool) -> dict:
            calls["model_dump"] = {"mode": mode, "by_alias": by_alias}
            return {
                "job": {"id": "job-1"},
                "items": {"pages": []},
                "text": {"pages": [{"page_number": 1, "text": "fallback text"}]},
                "metadata": {"pages": []},
            }

    class FakeParsing:
        def create(self, **kwargs):
            calls["create"] = kwargs
            return FakeJob()

        def wait_for_completion(self, job_id: str, *, timeout: float) -> None:
            calls["wait"] = {"job_id": job_id, "timeout": timeout}

        def get(self, job_id: str, *, expand: list[str]):
            calls["get"] = {"job_id": job_id, "expand": expand}
            return FakeResult()

    class FakeClient:
        parsing = FakeParsing()

    payload = llama_parse_agentic._parse_pdf_job_payload(FakeClient(), pdf_path, timeout=123.0)

    assert calls["create"] == {
        "upload_file": str(pdf_path),
        "tier": "agentic",
        "version": "latest",
        "disable_cache": True,
    }
    assert calls["wait"] == {"job_id": "job-1", "timeout": 123.0}
    assert calls["get"] == {
        "job_id": "job-1",
        "expand": ["items", "text", "metadata", "debug_logs"],
    }
    assert calls["model_dump"] == {"mode": "json", "by_alias": True}
    assert payload["job_id"] == "job-1"
    assert payload["cost_per_page_usd"] == llama_parse_agentic.CREDIT_RATE_USD * llama_parse_agentic.CREDITS_PER_PAGE
    assert "grid_llamaparse_image_extraction" not in payload
    assert "images_content_metadata" not in payload
    assert "markdown" not in payload


def test_llamaparse_page_normalization_matches_parsebench_rules() -> None:
    payload = {
        "items": {
            "pages": [
                {
                    "success": True,
                    "page_number": 1,
                    "items": [
                        {"type": "table", "md": "| a |", "html": "<table><tr><td>a</td></tr></table>"},
                        {
                            "type": "link",
                            "md": "[visible link](https://example.com)",
                            "text": "visible link",
                        },
                        {"type": "image", "md": "![diagram](page_1_image_1_v2.jpg)"},
                    ],
                }
            ]
        },
        "text": {"pages": [{"page_number": 1, "text": "fallback text"}]},
        "metadata": {"pages": [{"page_number": 1, "original_orientation_angle": 0}]},
    }

    pages = llama_parse_agentic._pages_from_payload(payload)

    assert pages == [
        ParsedPage(
            page=1,
            markdown=(
                "<table><tr><td>a</td></tr></table>\n\n"
                "visible link\n\n"
                "![diagram](page_1_image_1_v2.jpg)"
            ),
        )
    ]


def test_llamaparse_reuses_partition_cache(tmp_path, monkeypatch) -> None:
    pdf_path = tmp_path / "large.pdf"
    pdf_path.write_bytes(b"%PDF-fixture")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "pages-1-1.raw.json").write_text(
        '{"job_id":"cached","pages":[{"page":1,"md":"cached page"}]}',
        encoding="utf-8",
    )
    (cache_dir / "pages-2-2.raw.json").write_text(
        '{"job_id":"cached-2","pages":[{"page":1,"md":"cached page 2"}]}',
        encoding="utf-8",
    )

    monkeypatch.setenv("LLAMA_CLOUD_API_KEY", "test-key")
    monkeypatch.setattr(llama_parse_agentic, "_llama_client", lambda: object())
    monkeypatch.setattr(llama_parse_agentic, "_pdf_page_count", lambda _path: 2)

    def fail_parse_payload(*_args, **_kwargs) -> dict:
        raise AssertionError("expected cached partition to be reused")

    monkeypatch.setattr(llama_parse_agentic, "_parse_pdf_job_payload", fail_parse_payload)

    result = llama_parse_agentic.parse_pdf_agentic(
        pdf_path,
        max_pages_per_job=1,
        cache_dir=cache_dir,
    )

    assert result.pages == [
        ParsedPage(page=1, markdown="cached page"),
        ParsedPage(page=2, markdown="cached page 2"),
    ]
