# FrontierAtlas Ingest

Async ingestion pipeline for an AI-ecosystem intelligence graph: startups, products, research papers, jobs and news, with LLM-based extraction, a multi-tier fallback chain and deterministic entity resolution.

**Core rule: nothing is invented.** Every record carries a `source.url`. Papers, startups and jobs come from structured sources with no LLM. The LLM is used only for products, and its output is rejected unless the product name appears verbatim in the fetched page text.

## Results (measured)

| Vertical | Records | Source | LLM? |
|---|---|---|---|
| Startups | 1,500 | Y Combinator directory (yc-oss JSON), AI-filtered | No |
| Products | TBD (target 1,000+) | Startup websites (homepage + /pricing) | Yes, grounded |
| Research papers | 1,000 | arXiv API + GitHub REST API (live star counts) | No |
| Jobs | all 24h-fresh found | Greenhouse, Ashby, Lever, RemoteOK, Remotive | No |
| News | all 24h-fresh found | TechCrunch, The Verge, MIT Tech Review, Ars Technica, Wired (RSS) | No |

- **Paper to repo links:** 850 of 1,000 have a release phrase ("code is available at...") next to the link (`github_link_confidence = high`); 150 are `low` (repo only mentioned, possibly a cited tool). The column is exported so users can filter.
- **Products:** pricing was extracted for about 40% of products. It is kept only when the model also returns a sentence that appears verbatim on the page.
- **Browser fallback:** on a 15-site test, Playwright recovered 6 sites (40%) that plain HTTP could not read. Four were still blocked and were not bypassed.
- **Dedup across runs:** a second run of the signals pipeline processed 0 items; all were reported as `already_seen`.
- **Tests:** 35 unit tests, no network or API keys needed.

## Architecture

```
sources -> crawlers (async httpx / Playwright) -> text cleaning -> [LLM orchestrator -> grounding validator]
        -> entity resolver -> pydantic schemas -> JSONL -> CSV export -> Google Sheet
```

- `src/utils/http.py`: shared async client with a concurrency semaphore, exponential backoff with full jitter, `Retry-After` and GitHub rate-limit handling.
- `src/llm/orchestrator.py`: fallback chain Gemini -> Groq (primary model) -> Groq (secondary model) -> DeepSeek. Providers without a key are skipped.
  - **429:** retries with jittered backoff; after retries are exhausted the provider goes on a 15 s cooldown and other workers skip it.
  - **413 / context overflow:** the payload is cut to a per-provider token budget by `chunker.py` (keeps the page opening plus the most pricing/product-dense paragraphs); on a 413 the budget is halved and the call retried.
- `src/llm/grounding.py`: rejects any product name not found in the text the model saw; drops pricing without verbatim evidence.
- `src/resolver/resolver.py`: deterministic entity resolution (normalize, exact, alias, strict fuzzy with an ambiguity margin). Uncertain names stay unresolved rather than guessed. Seeded with 50 AI startups.
- `src/utils/dates.py`: normalizes ISO-8601, RFC-2822, epoch seconds/milliseconds and relative dates ("2 hours ago") to UTC.
- `src/utils/seen.py`: SQLite seen-set with an atomic `INSERT OR IGNORE` claim. At scale this becomes a Postgres unique constraint or Redis `SETNX`, so distributed nodes never process an item twice.
- `src/crawlers/browser.py`: async Playwright pool used only for sites that returned 403 or too little text.

### Freshness rule

Items with a source date must fall within the last 24 hours. Greenhouse uses `first_published` (not `updated_at`, which changes on edits). Items with no date use a first-seen heuristic: a source's first sighting only records a baseline, and later new URLs are treated as new. The export step re-checks the 24-hour window at export time.

### Anti-bot strategy

1. Plain async HTTP first, robots.txt respected, polite per-domain concurrency.
2. Prefer official APIs and feeds over scraping.
3. Playwright only for blocked or JS-rendered pages.
4. Challenge pages (Cloudflare, Datadome) are detected and skipped, not defeated. At production scale the documented approach is a residential proxy pool, per-domain rate budgets, session reuse and a managed unblocking service as a paid last resort.

## Setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env        # then fill in keys
python -m pytest tests -q
```

Keys: `GITHUB_TOKEN` (required for star counts), `GROQ_API_KEY` (and optionally `GEMINI_API_KEY`, `DEEPSEEK_API_KEY`). Model names are overridable in `.env`.

## Run order

```powershell
python -m src.pipeline.papers --target 1000
python -m src.pipeline.startups --target 1500
python -m src.pipeline.products --target 1100 --workers 4 --llm-concurrency 1 --page-tokens 700
python -m src.pipeline.products_browser --limit 60
python -m src.pipeline.signals --reset-seen
python -m src.export.csv_export
```

Products is resumable: rerun the same command to continue after a rate-limit stop.

## Known limitations

- Only the Groq tiers were exercised live. The Gemini and DeepSeek tiers are implemented but untested live; the fallback logic itself is covered by unit tests with fake providers.
- Product extraction is bounded by free-tier LLM rate limits, not by the crawler.
- 24-hour jobs and news counts are small by nature: company job boards post few roles per day.
- The paper-to-repo link is taken from the paper's own abstract; `low`-confidence links may point to a tool the paper uses.
- Some sites still block a real browser; those are logged, not bypassed.
- Pages are currently decoded via `response.text`, which can garble non-UTF-8 sites (visible as "â€”" in a few evidence strings).