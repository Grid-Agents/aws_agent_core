#!/usr/bin/env python3
"""Parse ONLY the not-yet-parsed Grid Docs PDFs and merge them into the manifest.

Why scoped: for llamaparse-agentic, prior manifest records don't count as parse
cache (only parse_resume_cache sidecars do, and those were never uploaded to S3),
so a --force over the full source dir would re-parse (and re-bill) the existing
docs. We instead parse new PDFs via the pdf_paths API and merge manifests after —
write_manifest() also recomputes artifact_revision.txt for the merged set.

Run from repo root:  app/GridAgentCore/.venv/bin/python scripts/parse_new_grid_docs.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "app" / "GridAgentCore"))

from grid_agent_core.corpus import (  # noqa: E402
    build_corpus,
    load_manifest,
    write_manifest,
)
from grid_agent_core.models import DocumentRecord  # noqa: E402

SOURCE_DIR = Path("/Users/kaps/Documents/Grid Docs")
ARTIFACT_DIR = REPO_ROOT / ".grid_artifacts"
BACKUP_DIR = ARTIFACT_DIR / ".backup-pre-expand"


def main() -> None:
    prior = load_manifest(ARTIFACT_DIR)
    parsed_filenames = {record.filename for record in prior}
    new_pdfs = [p for p in sorted(SOURCE_DIR.rglob("*.pdf")) if p.name not in parsed_filenames]
    if not new_pdfs:
        print("Nothing to do: all source PDFs are already in the manifest.")
        return
    print(f"Prior docs: {len(prior)} | new PDFs to parse: {len(new_pdfs)}")

    # Scoped parse: writes a manifest containing ONLY the new records (+ revision).
    new_records = build_corpus(
        SOURCE_DIR,
        ARTIFACT_DIR,
        parser="llamaparse-agentic",
        multimodal_enrich=True,
        show_progress=True,
        pdf_paths=new_pdfs,
    )
    print(f"Parsed {len(new_records)} new documents; merging manifest...")

    # Merge: prior 6 + new records, stable order, and let write_manifest recompute
    # artifact_revision.txt over the full merged set.
    by_id: dict[str, DocumentRecord] = {r.document_id: r for r in prior}
    for record in new_records:
        if record.document_id in by_id:
            print(f"  note: {record.document_id} replaced an existing record")
        by_id[record.document_id] = record
    merged = [by_id[k] for k in sorted(by_id)]
    write_manifest(ARTIFACT_DIR, merged)
    print(f"Manifest now has {len(merged)} documents.")

    # Merge source_document_metadata.json (scoped parse overwrote it with new-only).
    meta_path = ARTIFACT_DIR / "source_document_metadata.json"
    backup_meta = json.loads((BACKUP_DIR / "source_document_metadata.json").read_text())
    current_meta = json.loads(meta_path.read_text())
    docs = {d["filename"]: d for d in backup_meta.get("documents", [])}
    docs.update({d["filename"]: d for d in current_meta.get("documents", [])})
    merged_docs = [docs[k] for k in sorted(docs)]
    merged_meta = {
        **current_meta,
        "document_count": len(merged_docs),
        "known_page_count": sum(d.get("page_count") or 0 for d in merged_docs),
        "total_size_bytes": sum(d.get("size_bytes") or 0 for d in merged_docs),
        "documents": merged_docs,
    }
    meta_path.write_text(json.dumps(merged_meta, indent=2) + "\n", encoding="utf-8")
    print(f"source_document_metadata.json merged: {len(merged_docs)} documents.")
    print("DONE")


if __name__ == "__main__":
    main()
