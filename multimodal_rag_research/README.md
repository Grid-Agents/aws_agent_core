# Multimodal RAG Research Survey

Static GitHub Pages-ready report for the Grid AgentCore multimodal RAG survey.

## Files

- `index.html` - self-contained report with inline CSS and source links.
- `assets/*.png` - generated benchmark comparison charts used by the report.

## Local preview

From the repository root:

```bash
python3 -m http.server 8080 --directory multimodal_rag_research
```

Open:

```text
http://127.0.0.1:8080/
```

## GitHub Pages deployment

If GitHub Pages is configured to deploy from the repository branch root, the report will be available at:

```text
https://<owner>.github.io/<repo>/multimodal_rag_research/
```

If GitHub Pages deploys from a `docs/` folder or a `gh-pages` branch, copy the contents of this folder to that configured Pages root while preserving the `assets/` subfolder.
