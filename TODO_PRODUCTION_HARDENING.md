# Web Search + Indexing TODOs and Production-Hardening Next Pass

This file tracks follow-up work for:
- `search-index` (MCP + ingest + ES adapter)
- `rob-poc/web-search` (K8s deployment of MCP service)
- `rob-poc/apertus-indexing-es` (ECK Elasticsearch)
- `apertus-data-indexing` (legacy indexing repo, now mostly separate)

## Assumptions (Current State)

- Main MCP path is synchronous: crawl/fetch/extract/index happen inside the request lifecycle.
- ES target is the in-cluster ECK instance exposed as `apertus-indexing-es-dev-*`.
- Aliases are used for chunks/pages/status with bootstrap-on-demand behavior.
- Agent query path is chunk-first retrieval, then optional fetch-by-id for full content.

## Immediate TODOs (Short Term)

### 1) Deployment Correctness
- [ ] Ensure `rob-poc/web-search` image tag matches latest `search-index` implementation changes.
- [ ] Add a release checklist item: "verify deployed image digest == tested commit".
- [ ] Confirm `METASEARCH_URL` is always set in runtime env (or injected via MCP call).

### 2) Bootstrap and Startup Flow
- [ ] Decide one bootstrap strategy and keep it explicit:
  - either run `web-search-es-bootstrap` as a pre-deploy/admin step,
  - or run it in an init/admin job before traffic.
- [ ] Remove ambiguity between auto-bootstrap during read/query and explicit bootstrap phase.

### 3) Runtime Safety Controls
- [ ] Add reasonable server-side guardrails for `top_k` (even if soft/defaulted, with logging).
- [ ] Add per-request timeout budget for crawl + indexing to avoid long hanging calls.
- [ ] Add request-size/query-length validation for MCP tool inputs.

### 4) Observability
- [ ] Add structured logs with correlation/request IDs across:
  - MCP entrypoint
  - crawl/fetch/extract
  - ES bulk writes
  - query/fetch.
- [ ] Add counters: docs fetched, docs indexed, bulk failures, retries, robots-blocked URLs.
- [ ] Add latency histograms per stage (discover/fetch/extract/index/query).

### 5) Basic Operational Docs
- [ ] Add one runbook section:
  - bootstrap ES templates/aliases
  - deploy MCP
  - smoke test ingest + query + fetch.
- [ ] Add failure triage section for:
  - metasearch unreachable
  - ES auth/TLS errors
  - bulk partial failures.

## Production-Hardening Next Pass

### A) Reliability and Scale
- [ ] Move from synchronous ingest to async K8s Job execution (keep current sync tool for debug only).
- [ ] Add idempotent job submission contract and deterministic job naming/labels.
- [ ] Add queue/backpressure strategy so bursts do not overload ES or MCP workers.

### B) Elasticsearch Lifecycle and Capacity
- [ ] Add ILM/rollover policy for `web-chunks-*`, `web-pages-*`, `web-ingest-status-*`.
- [ ] Separate read/write aliases with periodic rollover playbook.
- [ ] Tune mappings for high-cardinality fields and avoid accidental dynamic field explosion.
- [ ] Reassess shard/replica policy when load tests indicate pressure.
- [ ] Keep current 4Gi/500Gi baseline until benchmark data justifies a change.

### C) Query Path Hardening
- [ ] Keep `_source` lean for search responses; fetch full content only by explicit fetch tool.
- [ ] Add pagination/cursor behavior if agent needs large result scans.
- [ ] Add query/load protections (timeouts, max clauses, sane limits) to protect ES.

### D) Security Hardening
- [ ] Replace `ES_VERIFY_TLS=false` with proper trust chain configuration where possible.
- [ ] Minimize service account/RBAC scope to exact required actions.
- [ ] Review ingress whitelist/TLS/cert rotation policy against current platform standards.
- [ ] Confirm secrets rotation procedure for ES credentials.

### E) Data Quality and Freshness
- [ ] Define re-index freshness policy (already re-fetching is good; now formalize TTL/SLA).
- [ ] Track source update timestamps where available and expose freshness metadata in results.
- [ ] Add explicit handling/reporting for failed/disallowed URLs in status index queries.

### F) Test and Validation Expansion
- [ ] Add integration tests against ephemeral ES (template bootstrap + bulk + query + fetch).
- [ ] Add tests for bootstrap CLI and alias/index creation flows.
- [ ] Add load tests:
  - concurrent ingest requests
  - concurrent query traffic
  - mixed ingest/query profile.
- [ ] Add manifest CI checks (YAML lint, schema, required secret/env presence).

### G) Repo Boundary Cleanup
- [ ] Document clear ownership:
  - `search-index`: runtime ingest/query/fetch logic
  - `rob-poc/web-search`: deployment/runtime config
  - `rob-poc/apertus-indexing-es`: ES infra
  - `apertus-data-indexing`: legacy/offline indexing workflows.
- [ ] Add a deconfliction note so operators do not mix legacy local-ES scripts with K8s ES runtime flow.

## Suggested Execution Order

1. Image/version alignment + `METASEARCH_URL` wiring + bootstrap strategy.
2. Observability and runtime safety guardrails.
3. Async Job architecture for ingest.
4. ES lifecycle/ILM/rollover and security tightening.
5. Load testing and capacity tuning.

