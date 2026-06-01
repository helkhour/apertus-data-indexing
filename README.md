# Apertus Indexing

This repository is now reduced to the shared Elasticsearch indexing package used by:

- `search-index` / `web-search` MCP runtime
- `rob-poc` Kubernetes deployment

Legacy SLURM indexing/search scripts and archived result artifacts were removed.

## Package

- Distribution: `apertus-indexing`
- Import path: `apertus_indexing`
- Source: `src/apertus_indexing`
- Bootstrap CLI: `apertus-indexing-es-bootstrap`

Install locally:

```bash
pip install -e .
```

## What it provides

- Elasticsearch config loading from environment
- index template + alias bootstrap
- bulk indexing with retry/batching
- chunk query helper
- fetch by document id helper

## Adding New Data Types

Current production usage is `web`, but this package is meant to be reused for other sources.

For a new data type (example: `pdf`, `github`, `docs`):

1. Build source-specific ingestion in the source module/repo (not here).
2. Emit the same canonical record families already used by web:
   - page/content records
   - chunk records
   - ingest status records
3. Include `data_type` on records so query/fetch can distinguish source origin.
4. Reuse this package for:
   - alias/template bootstrap
   - bulk indexing
   - query/fetch helpers
5. Wire the MCP tool to call the new source ingestion, then index through this package (same flow as web).

This keeps source logic separate while preserving one shared indexing standard.

## Repository layout

```text
.
├── pyproject.toml
├── README.md
├── TODO_PRODUCTION_HARDENING.md
└── src/
    └── apertus_indexing/
        ├── __init__.py
        ├── es_bootstrap_cli.py
        └── es_indexer.py
```
