"""Shared Elasticsearch indexing helpers used by MCP data-source adapters."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Sequence

import requests


class ElasticsearchIndexingError(RuntimeError):
    """Raised when Elasticsearch indexing fails."""


@dataclass(frozen=True)
class ElasticsearchConfig:
    url: str
    username: str
    password: str
    chunks_read_alias: str
    chunks_write_alias: str
    pages_read_alias: str
    pages_write_alias: str
    status_read_alias: str
    status_write_alias: str
    verify_tls: bool = False
    timeout_seconds: int = 30
    bulk_docs: int = 500
    bulk_bytes: int = 10 * 1024 * 1024


def build_content_hash(text: str) -> str:
    return sha256((text or "").encode("utf-8")).hexdigest()


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _parse_positive_int(value: str, *, env_name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer") from exc
    if parsed <= 0:
        raise ValueError(f"{env_name} must be > 0")
    return parsed


def _parse_byte_size(value: str, *, env_name: str) -> int:
    normalized = value.strip().lower()
    if not normalized:
        raise ValueError(f"{env_name} must not be empty")

    multiplier = 1
    number_part = normalized
    for suffix, factor in (("kb", 1024), ("mb", 1024 * 1024), ("gb", 1024 * 1024 * 1024)):
        if normalized.endswith(suffix):
            multiplier = factor
            number_part = normalized[: -len(suffix)].strip()
            break
    try:
        base_value = float(number_part)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be an integer or value like 10mb") from exc
    computed = int(base_value * multiplier)
    if computed <= 0:
        raise ValueError(f"{env_name} must be > 0")
    return computed


def load_es_config_from_env() -> ElasticsearchConfig:
    url = (os.environ.get("ES_URL") or "https://apertus-indexing-es-dev-es-http.rob-poc.svc.cluster.local:9200").strip()
    username = (os.environ.get("ES_USERNAME") or "elastic").strip()
    password = (os.environ.get("ES_PASSWORD") or "").strip()
    chunks_read_alias = (os.environ.get("ES_CHUNKS_READ_ALIAS") or "web-chunks-read").strip()
    chunks_write_alias = (os.environ.get("ES_CHUNKS_WRITE_ALIAS") or "web-chunks-write").strip()
    pages_read_alias = (os.environ.get("ES_PAGES_READ_ALIAS") or "web-pages-read").strip()
    pages_write_alias = (os.environ.get("ES_PAGES_WRITE_ALIAS") or "web-pages-write").strip()
    status_read_alias = (os.environ.get("ES_STATUS_READ_ALIAS") or "web-ingest-status-read").strip()
    status_write_alias = (os.environ.get("ES_STATUS_WRITE_ALIAS") or "web-ingest-status-write").strip()
    timeout_value = (os.environ.get("ES_TIMEOUT_SECONDS") or "30").strip()
    bulk_docs_value = (os.environ.get("WEB_INDEX_BULK_DOCS") or "500").strip()
    bulk_bytes_value = (os.environ.get("WEB_INDEX_BULK_BYTES") or "10mb").strip()

    missing = [
        name
        for name, value in (("ES_PASSWORD", password),)
        if not value
    ]
    if missing:
        raise ValueError(f"Missing Elasticsearch environment variables: {', '.join(missing)}")

    timeout_seconds = _parse_positive_int(timeout_value, env_name="ES_TIMEOUT_SECONDS")
    bulk_docs = _parse_positive_int(bulk_docs_value, env_name="WEB_INDEX_BULK_DOCS")
    bulk_bytes = _parse_byte_size(bulk_bytes_value, env_name="WEB_INDEX_BULK_BYTES")

    return ElasticsearchConfig(
        url=url.rstrip("/"),
        username=username,
        password=password,
        chunks_read_alias=chunks_read_alias,
        chunks_write_alias=chunks_write_alias,
        pages_read_alias=pages_read_alias,
        pages_write_alias=pages_write_alias,
        status_read_alias=status_read_alias,
        status_write_alias=status_write_alias,
        verify_tls=_env_bool("ES_VERIFY_TLS", default=False),
        timeout_seconds=timeout_seconds,
        bulk_docs=bulk_docs,
        bulk_bytes=bulk_bytes,
    )


def _build_document_id(record: dict[str, Any]) -> str:
    content_hash = record.get("content_hash")
    if isinstance(content_hash, str) and content_hash:
        return content_hash

    content = record.get("content")
    if isinstance(content, str) and content:
        return build_content_hash(content)

    canonical_record = json.dumps(record, ensure_ascii=False, sort_keys=True, default=str)
    return sha256(canonical_record.encode("utf-8")).hexdigest()


def check_elasticsearch_connection(config: ElasticsearchConfig) -> dict[str, Any]:
    response = requests.get(
        f"{config.url}",
        auth=(config.username, config.password),
        timeout=config.timeout_seconds,
        verify=config.verify_tls,
    )
    if response.status_code >= 400:
        raise ElasticsearchIndexingError(
            f"Elasticsearch health check failed with HTTP {response.status_code}: {response.text[:400]}"
        )

    try:
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:200]}

    return {
        "ok": True,
        "status_code": response.status_code,
        "name": payload.get("name"),
        "cluster_name": payload.get("cluster_name"),
        "version": (payload.get("version") or {}).get("number"),
    }


def _request_with_retry(
    *,
    method: str,
    url: str,
    config: ElasticsearchConfig,
    retries: int = 3,
    retry_statuses: set[int] | None = None,
    **kwargs: Any,
) -> requests.Response:
    retry_statuses = retry_statuses or {429, 503}
    attempt = 0
    while True:
        attempt += 1
        try:
            response = requests.request(
                method=method,
                url=url,
                auth=(config.username, config.password),
                timeout=config.timeout_seconds,
                verify=config.verify_tls,
                **kwargs,
            )
            if response.status_code not in retry_statuses or attempt >= retries:
                return response
        except requests.RequestException:
            if attempt >= retries:
                raise
        time.sleep(2 ** (attempt - 1))


def _field_mapping_type(field_name: str) -> dict[str, Any]:
    if field_name in {"date", "fetch_timestamp", "indexed_at"}:
        return {"type": "date"}
    if field_name in {"content", "text"}:
        return {
            "type": "text",
            "fields": {
                "exact": {"type": "text"},
            },
        }
    if field_name in {"robots_allowed", "status"}:
        if field_name == "robots_allowed":
            return {"type": "boolean"}
        return {"type": "keyword"}
    if field_name == "http_status":
        return {"type": "integer"}
    return {"type": "keyword"}


def _index_mapping_for_kind(kind: str) -> dict[str, Any]:
    if kind == "status":
        fields = [
            "document_id",
            "path",
            "query",
            "title",
            "lang",
            "date",
            "robots_allowed",
            "http_status",
            "fetch_timestamp",
            "redirect_url",
            "status",
            "error",
            "record_kind",
            "data_type",
        ]
    elif kind == "pages":
        fields = [
            "document_id",
            "content_hash",
            "content",
            "text",
            "url",
            "path",
            "query",
            "title",
            "lang",
            "date",
            "robots_allowed",
            "http_status",
            "fetch_timestamp",
            "record_kind",
            "data_type",
        ]
    else:  # chunks
        fields = [
            "document_id",
            "content",
            "text",
            "content_hashes",
            "path",
            "query",
            "title",
            "lang",
            "date",
            "robots_allowed",
            "http_status",
            "fetch_timestamp",
            "record_kind",
            "data_type",
        ]
    # TODO: Extend mappings with vector fields when hybrid/vector retrieval is introduced.
    return {
        "dynamic": True,
        "properties": {name: _field_mapping_type(name) for name in fields},
    }


def _alias_exists(config: ElasticsearchConfig, alias: str) -> bool:
    response = _request_with_retry(
        method="GET",
        url=f"{config.url}/_alias/{alias}",
        config=config,
        retries=2,
    )
    if response.status_code == 404:
        return False
    if response.status_code >= 400:
        raise ElasticsearchIndexingError(
            f"Failed to check alias '{alias}' with HTTP {response.status_code}: {response.text[:300]}"
        )
    return True


def _ensure_alias_pair(
    config: ElasticsearchConfig,
    *,
    read_alias: str,
    write_alias: str,
    index_prefix: str,
    kind: str,
) -> None:
    if _alias_exists(config, write_alias):
        if not _alias_exists(config, read_alias):
            aliases_response = _request_with_retry(
                method="GET",
                url=f"{config.url}/_alias/{write_alias}",
                config=config,
                retries=2,
            )
            if aliases_response.status_code >= 400:
                raise ElasticsearchIndexingError(
                    f"Failed reading write alias '{write_alias}' with HTTP {aliases_response.status_code}: "
                    f"{aliases_response.text[:300]}"
                )
            indices = list((aliases_response.json() or {}).keys())
            if not indices:
                raise ElasticsearchIndexingError(
                    f"Write alias '{write_alias}' exists but has no indices"
                )
            actions = [{"add": {"index": idx, "alias": read_alias}} for idx in indices]
            update_response = _request_with_retry(
                method="POST",
                url=f"{config.url}/_aliases",
                config=config,
                json={"actions": actions},
            )
            if update_response.status_code >= 400:
                raise ElasticsearchIndexingError(
                    f"Failed attaching read alias '{read_alias}' with HTTP {update_response.status_code}: "
                    f"{update_response.text[:300]}"
                )
        return

    concrete_index = f"{index_prefix}{time.strftime('%Y%m%d%H%M%S')}"
    body = {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": _index_mapping_for_kind(kind),
        "aliases": {
            read_alias: {},
            write_alias: {},
        },
    }
    create_response = _request_with_retry(
        method="PUT",
        url=f"{config.url}/{concrete_index}",
        config=config,
        json=body,
    )
    if create_response.status_code >= 400:
        raise ElasticsearchIndexingError(
            f"Failed creating index '{concrete_index}' with HTTP {create_response.status_code}: "
            f"{create_response.text[:500]}"
        )


def ensure_web_index_aliases(config: ElasticsearchConfig) -> None:
    _ensure_alias_pair(
        config,
        read_alias=config.chunks_read_alias,
        write_alias=config.chunks_write_alias,
        index_prefix="web-chunks-",
        kind="chunks",
    )
    _ensure_alias_pair(
        config,
        read_alias=config.pages_read_alias,
        write_alias=config.pages_write_alias,
        index_prefix="web-pages-",
        kind="pages",
    )
    _ensure_alias_pair(
        config,
        read_alias=config.status_read_alias,
        write_alias=config.status_write_alias,
        index_prefix="web-ingest-status-",
        kind="status",
    )


def _template_body_for_kind(kind: str) -> dict[str, Any]:
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "refresh_interval": "30s",
        },
        "mappings": _index_mapping_for_kind(kind),
    }


def ensure_web_index_templates(config: ElasticsearchConfig) -> dict[str, Any]:
    templates = (
        ("web-chunks-template", "web-chunks-*", "chunks"),
        ("web-pages-template", "web-pages-*", "pages"),
        ("web-ingest-status-template", "web-ingest-status-*", "status"),
    )
    applied: list[dict[str, Any]] = []
    for template_name, index_pattern, kind in templates:
        body = {
            "index_patterns": [index_pattern],
            "priority": 200,
            "template": _template_body_for_kind(kind),
        }
        response = _request_with_retry(
            method="PUT",
            url=f"{config.url}/_index_template/{template_name}",
            config=config,
            json=body,
        )
        if response.status_code >= 400:
            raise ElasticsearchIndexingError(
                f"Failed applying index template '{template_name}' with HTTP {response.status_code}: "
                f"{response.text[:400]}"
            )
        applied.append(
            {
                "template": template_name,
                "index_pattern": index_pattern,
                "kind": kind,
            }
        )
    return {"applied": applied}


def _batch_records(
    records: Sequence[dict[str, Any]],
    *,
    index_alias: str,
    max_docs: int,
    max_bytes: int,
) -> list[str]:
    batches: list[str] = []
    current_lines: list[str] = []
    current_docs = 0
    current_bytes = 0

    for record in records:
        action = {"index": {"_index": index_alias, "_id": _build_document_id(record)}}
        action_line = json.dumps(action, ensure_ascii=False)
        record_line = json.dumps(record, ensure_ascii=False, default=str)
        entry = f"{action_line}\n{record_line}\n"
        entry_bytes = len(entry.encode("utf-8"))

        if current_lines and (current_docs >= max_docs or current_bytes + entry_bytes > max_bytes):
            batches.append("".join(current_lines))
            current_lines = []
            current_docs = 0
            current_bytes = 0

        current_lines.append(entry)
        current_docs += 1
        current_bytes += entry_bytes

    if current_lines:
        batches.append("".join(current_lines))
    return batches


def bulk_index_records(
    records: Sequence[dict[str, Any]],
    *,
    index_alias: str,
    config: ElasticsearchConfig,
) -> dict[str, Any]:
    attempted = len(records)
    if attempted == 0:
        return {"attempted": 0, "indexed": 0, "failed": 0, "errors": []}

    item_errors: list[dict[str, Any]] = []
    indexed_total = 0

    for payload in _batch_records(
        records,
        index_alias=index_alias,
        max_docs=config.bulk_docs,
        max_bytes=config.bulk_bytes,
    ):
        response = _request_with_retry(
            method="POST",
            url=f"{config.url}/_bulk",
            config=config,
            params={"refresh": "false"},
            headers={"Content-Type": "application/x-ndjson"},
            data=payload.encode("utf-8"),
        )
        if response.status_code >= 400:
            raise ElasticsearchIndexingError(
                f"Elasticsearch bulk indexing failed with HTTP {response.status_code}: {response.text[:600]}"
            )

        try:
            result = response.json()
        except ValueError as exc:
            raise ElasticsearchIndexingError("Elasticsearch bulk response was not valid JSON") from exc

        indexed_in_batch = 0
        for item in result.get("items", []):
            index_result = item.get("index") or {}
            status = index_result.get("status", 500)
            if 200 <= status < 300:
                indexed_in_batch += 1
                continue
            item_errors.append(
                {
                    "status": status,
                    "id": index_result.get("_id"),
                    "error": index_result.get("error"),
                }
            )
        indexed_total += indexed_in_batch

    failed_total = attempted - indexed_total
    if item_errors and failed_total == 0:
        failed_total = len(item_errors)

    return {
        "attempted": attempted,
        "indexed": indexed_total,
        "failed": failed_total,
        "errors": item_errors,
    }


def refresh_alias(config: ElasticsearchConfig, index_alias: str) -> None:
    response = _request_with_retry(
        method="POST",
        url=f"{config.url}/{index_alias}/_refresh",
        config=config,
    )
    if response.status_code >= 400:
        raise ElasticsearchIndexingError(
            f"Failed refreshing alias '{index_alias}' with HTTP {response.status_code}: {response.text[:300]}"
        )


def query_web_chunks(
    *,
    query: str,
    top_k: int,
    config: ElasticsearchConfig,
) -> dict[str, Any]:
    search_body = {
        "size": top_k,
        "track_total_hits": False,
        "query": {
            "bool": {
                "should": [
                    {"match": {"content": {"query": query}}},
                    {"match_phrase": {"content.exact": {"query": query}}},
                ],
                "minimum_should_match": 1,
            }
        },
        "_source": [
            "document_id",
            "content_hashes",
            "path",
            "query",
            "title",
            "lang",
            "date",
            "fetch_timestamp",
            "record_kind",
        ],
        "highlight": {
            "fields": {
                "content": {
                    "fragment_size": 240,
                    "number_of_fragments": 1,
                }
            }
        },
    }
    response = _request_with_retry(
        method="POST",
        url=f"{config.url}/{config.chunks_read_alias}/_search",
        config=config,
        json=search_body,
    )
    if response.status_code >= 400:
        raise ElasticsearchIndexingError(
            f"Chunk query failed with HTTP {response.status_code}: {response.text[:400]}"
        )
    payload = response.json()
    hits = payload.get("hits", {}).get("hits", [])
    results: list[dict[str, Any]] = []
    for hit in hits:
        source = hit.get("_source", {})
        highlighted = ((hit.get("highlight") or {}).get("content") or [])
        snippet = highlighted[0] if highlighted else (source.get("content", "")[:240] if source.get("content") else "")
        results.append(
            {
                "document_id": source.get("document_id") or hit.get("_id"),
                "score": hit.get("_score"),
                "snippet": snippet,
                "content_hashes": source.get("content_hashes"),
                "path": source.get("path"),
                "query": source.get("query"),
                "title": source.get("title"),
                "lang": source.get("lang"),
                "date": source.get("date"),
                "fetch_timestamp": source.get("fetch_timestamp"),
            }
        )
    return {
        "query": query,
        "top_k": top_k,
        "count": len(results),
        "results": results,
    }


def fetch_by_document_id(
    *,
    document_id: str,
    config: ElasticsearchConfig,
) -> dict[str, Any]:
    for alias, record_type in (
        (config.chunks_read_alias, "chunk"),
        (config.pages_read_alias, "page"),
    ):
        response = _request_with_retry(
            method="GET",
            url=f"{config.url}/{alias}/_doc/{document_id}",
            config=config,
            retries=2,
        )
        if response.status_code == 404:
            continue
        if response.status_code >= 400:
            raise ElasticsearchIndexingError(
                f"Fetch failed for alias '{alias}' with HTTP {response.status_code}: {response.text[:300]}"
            )
        payload = response.json()
        if payload.get("found"):
            return {
                "found": True,
                "record_type": record_type,
                "alias": alias,
                "document_id": document_id,
                "record": payload.get("_source", {}),
            }
    return {
        "found": False,
        "document_id": document_id,
    }


# Generic aliases kept as the long-term source-agnostic API surface.
ensure_index_aliases = ensure_web_index_aliases
ensure_index_templates = ensure_web_index_templates
query_chunks = query_web_chunks
