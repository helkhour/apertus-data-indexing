"""CLI entrypoint to bootstrap Elasticsearch templates and aliases."""

from __future__ import annotations

import json
import sys
from typing import Any

from apertus_indexing.es_indexer import (
    ElasticsearchIndexingError,
    check_elasticsearch_connection,
    ensure_web_index_aliases,
    ensure_web_index_templates,
    load_es_config_from_env,
)


def _error(message: str) -> None:
    print(message, file=sys.stderr)


def main() -> None:
    try:
        config = load_es_config_from_env()
        health = check_elasticsearch_connection(config)
        templates = ensure_web_index_templates(config)
        ensure_web_index_aliases(config)
    except (ValueError, ElasticsearchIndexingError) as exc:
        _error(f"Bootstrap failed: {exc}")
        raise SystemExit(1) from exc

    payload: dict[str, Any] = {
        "ok": True,
        "elasticsearch": {
            "url": config.url,
            "cluster_name": health.get("cluster_name"),
            "version": health.get("version"),
        },
        "templates": templates,
        "aliases": {
            "chunks_read": config.chunks_read_alias,
            "chunks_write": config.chunks_write_alias,
            "pages_read": config.pages_read_alias,
            "pages_write": config.pages_write_alias,
            "status_read": config.status_read_alias,
            "status_write": config.status_write_alias,
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
