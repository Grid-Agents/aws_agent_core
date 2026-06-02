from __future__ import annotations

from grid_agent_core import artifacts


class FakePaginator:
    def paginate(self, Bucket, Prefix):  # noqa: N803 - boto3 shape
        assert Bucket == "bucket"
        assert Prefix == "prefix"
        return [{"Contents": [{"Key": "prefix/manifest.jsonl"}, {"Key": "prefix/indexes/vector/index.json"}]}]


class FakeClient:
    def __init__(self) -> None:
        self.uploaded = []
        self.downloaded = []

    def upload_file(self, source, bucket, key, **kwargs):
        self.uploaded.append((source, bucket, key, kwargs))

    def get_paginator(self, name):
        assert name == "list_objects_v2"
        return FakePaginator()

    def download_file(self, bucket, key, target):
        self.downloaded.append((bucket, key, target))
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("{}\n")


def test_upload_artifacts_uses_bucket_prefix(tmp_path, monkeypatch) -> None:
    source = tmp_path / "artifacts"
    (source / "indexes" / "vector").mkdir(parents=True)
    (source / "figures" / "grid" / "doc").mkdir(parents=True)
    (source / "parse_resume_cache" / "llamaparse_agentic").mkdir(parents=True)
    (source / "manifest.jsonl").write_text("{}", encoding="utf-8")
    (source / "indexes" / "vector" / "index.json").write_text("{}", encoding="utf-8")
    (source / "figures" / "grid" / "doc" / "figure.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (source / "parse_resume_cache" / "llamaparse_agentic" / "raw.json").write_text("{}", encoding="utf-8")
    client = FakeClient()
    monkeypatch.setattr(artifacts, "_client", lambda: client)

    uploaded = artifacts.upload_artifacts(source_dir=source, bucket="bucket", prefix="prefix")

    assert uploaded == 3
    assert ("bucket", "prefix/manifest.jsonl") in [(item[1], item[2]) for item in client.uploaded]
    figure_upload = next(item for item in client.uploaded if item[2].endswith("figure.png"))
    assert figure_upload[3]["ExtraArgs"]["ContentType"] == "image/png"
    assert not any("parse_resume_cache" in item[2] for item in client.uploaded)


def test_download_artifacts_uses_bucket_prefix(tmp_path, monkeypatch) -> None:
    client = FakeClient()
    monkeypatch.setattr(artifacts, "_client", lambda: client)

    downloaded = artifacts.download_artifacts(bucket="bucket", prefix="prefix", target_dir=tmp_path)

    assert downloaded == 2
    assert (tmp_path / "manifest.jsonl").exists()
    assert (tmp_path / "indexes" / "vector" / "index.json").exists()
