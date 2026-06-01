"""Shared indexing package for Apertus data sources."""

from .es_indexer import (
    ElasticsearchConfig,
    ElasticsearchIndexingError,
    bulk_index_records,
    check_elasticsearch_connection,
    ensure_index_aliases,
    ensure_index_templates,
    ensure_web_index_aliases,
    ensure_web_index_templates,
    fetch_by_document_id,
    load_es_config_from_env,
    query_chunks,
    query_web_chunks,
    refresh_alias,
)

__all__ = [
    "ElasticsearchConfig",
    "ElasticsearchIndexingError",
    "bulk_index_records",
    "check_elasticsearch_connection",
    "ensure_index_aliases",
    "ensure_index_templates",
    "ensure_web_index_aliases",
    "ensure_web_index_templates",
    "fetch_by_document_id",
    "load_es_config_from_env",
    "query_chunks",
    "query_web_chunks",
    "refresh_alias",
]
