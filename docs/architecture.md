# FrontierAtlas: Architecture and Production Design

## 1. Scale Strategy: 500,000 Records Without Manual Intervention

**Discovery is separated from extraction.** Producers enqueue URLs, workers consume them, and every stage is designed to be idempotent.

- **Seed sources:** Bulk directories and APIs, including arXiv OAI-PMH, GitHub GraphQL, the YC company dataset, and Greenhouse, Ashby and Lever board APIs. Structured sources reduce blocking risk and avoid unnecessary LLM calls.
- **Queue-based fan-out:** A Redis Streams or Amazon SQS frontier queue holds `(url, vertical, priority, attempt)`. Stateless asynchronous workers consume batches. Horizontal scaling means adding workers rather than changing application code.
- **Per-domain budgets:** A Redis-backed token bucket limits request rates per domain so adding workers does not overload individual websites.
- **Tiered fetching:** Plain HTTP first, followed by a headless browser for blocked or JavaScript-rendered pages. More difficult sources are handled through approved managed crawling infrastructure. In this trial, browser fallback recovered 6 of 15 sites that HTTP could not read.
- **Self-healing:** Failures are classified (`blocked_403`, `js_rendered`, `llm_failed`) and routed to retry queues with exponential backoff. Schema-validation failures can trigger alerts.
- **Incremental ingestion:** After the initial bulk acquisition, sources can be revisited using ETags, sitemap `lastmod` values and API update timestamps.

The queue, Redis coordination and distributed worker infrastructure are proposed production components, not a claim that the current local implementation has already processed 500,000 records.

## 2. Handling 413s and 429s Across Concurrent Extractions

### 413: Payload Too Large

- A token-budget chunker trims page content before sending it to an LLM.
- It preserves the page opening and information-dense paragraphs containing product and pricing signals.
- Token budgets are configurable per provider.
- If a provider still returns 413 or a context-length error, the budget is reduced and the request retried, up to a bounded number of attempts.
- If recovery fails, the extraction is rejected or passed to another configured provider.

### 429: Rate Limits

- Exponential backoff with random jitter prevents synchronized retries.
- Respect the server-provided `Retry-After` header.
- A provider-level cooldown prevents workers from repeatedly sending requests to an unavailable provider.
- At production scale, a Redis-backed global token bucket can coordinate request and token budgets across workers.
- Requests are admitted according to provider and model limits before being sent.

### LLM Provider Strategy

The orchestrator uses a provider abstraction. The currently configured and live-tested provider is Groq.

The intended production fallback order is:

1. Gemini Flash
2. Groq primary model
3. Groq secondary model
4. DeepSeek

The two Groq models share the same configured API key and must not be treated as independent quota pools. Gemini and DeepSeek are proposed fallback integrations and are not currently verified as operational.

Deterministic sources such as research papers, job boards and startup directories are processed without LLM calls wherever structured data is available.

### Hallucination Control

Every extracted product passes source-grounding validation:

- The product name must appear in the retrieved text provided to the model.
- Pricing is retained only when supported by verbatim evidence.
- Unsupported or ambiguous output is rejected and recorded in the rejection log.

## 3. Freshness Tracking and Distributed Deduplication

- **Canonical key:** SHA-1 of a normalized URL, using a lowercase hostname, removing fragments and tracking parameters such as `utm_*`.
- **Atomic claim:** PostgreSQL `INSERT ... ON CONFLICT DO NOTHING` or Redis `SET key NX` allows only one distributed worker to claim an item. The current local implementation uses SQLite `INSERT OR IGNORE`.
- **Date normalization:** Convert ISO-8601, RFC-2822, epoch seconds, epoch milliseconds and relative dates such as "2 hours ago" into UTC timestamps.
- **24-hour validation:** Jobs and news must fall within the rolling 24-hour publication window. Greenhouse uses `first_published` rather than `updated_at`, which can change when an existing job is edited.
- **Missing dates:** Use a first-seen heuristic. The first observation establishes a baseline; later unseen URLs can be treated as newly discovered, without claiming an exact publication timestamp.
- **Content changes:** A content hash can be stored alongside the canonical URL to distinguish edited content from identical records. This is a proposed production extension unless enabled in the deployed pipeline.

The existing signals pipeline has demonstrated deduplication across reruns: previously processed jobs and news were identified as already seen.

## 4. Storage Strategy

| Requirement | Technology | Rationale |
|---|---|---|
| Primary database | PostgreSQL | Transactions, unique constraints, JSONB and durable canonical records |
| Semantic search | pgvector | Vector similarity alongside relational entity data |
| Entity relationships | PostgreSQL edge tables | Relational queries and recursive CTEs; graph database can be introduced later |
| Distributed queues | Redis Streams or SQS | Durable task distribution and worker coordination |
| Rate limiting | Redis | Shared atomic token buckets and cooldown state |
| Raw source archives | S3-compatible object storage | Cost-effective storage and replayable source snapshots |

Entity resolution maintains raw-to-canonical mappings, including the canonical entity, matching method and confidence score. This makes mapping decisions auditable.

For the current local implementation, JSONL stores entity records, SQLite supports persistent deduplication, and CSV files provide export functionality. PostgreSQL, Redis, pgvector and object storage form the proposed production architecture.

## 5. Reliability and Anti-Bot Strategy

- Structured logging records retries, cooldowns, extraction failures and rejection reasons.
- robots.txt is respected, and per-domain concurrency is bounded.
- Official APIs and RSS feeds are preferred over HTML scraping.
- Playwright is used selectively for blocked and JavaScript-rendered pages.
- CAPTCHA and Cloudflare/Datadome challenge pages are detected and skipped rather than circumvented.
- Approved proxy infrastructure and managed crawling services may be evaluated for production workloads where permitted.

The browser fallback recovered 6 of 15 tested sites (40%). Four remained blocked, demonstrating that browser rendering does not guarantee access.

## 6. Current Implementation and Limitations

The current system includes asynchronous ingestion, structured source crawlers, Groq-based product extraction, token-aware chunking, retry handling, source-grounding validation, deterministic entity resolution, SQLite-based deduplication, Playwright fallback and CSV export.

The assignment datasets target at least 1,000 startups, 1,000 products and 1,000 research papers with GitHub metrics, plus fresh jobs and news.

The following are production design extensions rather than completed deployments:

- Distributed Redis/SQS worker queues.
- Global cross-worker rate limiting.
- PostgreSQL and pgvector migration.
- S3-compatible raw-page storage.
- Independent Gemini and DeepSeek provider integrations.
- Production deployment at 500,000+ records.

The system prioritizes traceable source URLs, reproducible ingestion, conservative extraction and honest reporting of unavailable data.
