# FrontierAtlas

An async data pipeline for collecting and organizing information about AI startups, products, research papers, jobs and news.

The main rule I followed while building it: **nothing gets invented.** Every record carries a `source.url`. Startups, research papers and jobs are collected from structured sources without using an LLM. The LLM is used only to extract information from product pages, and its output is discarded unless the product name can be found in the page text it was given.

## What it produced

The pipeline collected data across five areas of the AI ecosystem.

**Startups — 1,500 records**

Collected from the Y Combinator directory using the `yc-oss` JSON dataset and filtered for AI-related companies.

**Products — 1,102 records**

Collected from startup homepages and pricing pages. Gemini and Groq are used to extract product information, with a grounding check against the original page text.

**Research papers — 1,000 records**

Collected from the arXiv API. The GitHub REST API is used to retrieve live repository star counts where a GitHub link is available.

**Jobs**

Collected from Greenhouse, Ashby, Lever, RemoteOK and Remotive. Only listings from the previous 24 hours are retained.

**News**

Collected through RSS feeds from TechCrunch, The Verge, MIT Technology Review, Ars Technica and Wired. Articles are filtered to the previous 24 hours.

The pipelines save records as JSONL files. The exporter in `src/export/csv_export.py` converts them into six CSV files for the Google Sheets tabs. Importing these CSV files into Google Sheets is currently a manual step.

## A few things worth knowing

**Research papers and code links**

Out of the 1,000 collected papers, 850 have a phrase such as "code is available at" shortly before the GitHub link. These are marked `github_link_confidence = high`.

The remaining 150 are marked `low` because the repository is mentioned in the abstract, but it may be a tool used by the paper rather than its own implementation. This confidence field is retained in the export.

**Product extraction**

Of the 1,102 collected product records, 589 contain a pricing model. Each pricing entry also stores the sentence from the source page that supports it. If pricing information is not available on the page, the field is left empty rather than guessed.

**Product page fetching**

Of the 1,102 product pages, 1,096 were fetched using async HTTP and 6 through the Playwright browser fallback.

In a separate test involving 15 sites that regular HTTP could not read because of 403 responses or JavaScript-rendered content, the browser fallback recovered 6. Four remained blocked and were left alone.

**Deduplication across runs**

The jobs and news pipeline was run a second time. It processed zero new items, with every item reported as `already_seen`.

**Tests**

The project has 35 unit tests, all passing. These tests do not require network access or API keys.

## How it works

```text
Sources
   |
   v
Async crawlers (httpx / Playwright)
   |
   v
Text cleaning and extraction
   |
   v
LLM orchestration and grounding validation
   |
   v
Entity resolution and schema validation
   |
   v
JSONL storage
   |
   v
CSV export
```

**HTTP client** (`src/utils/http.py`)

A shared async HTTP client handles requests with a concurrency limit, exponential backoff with full jitter, `Retry-After` support and GitHub rate-limit header handling.

**LLM orchestrator** (`src/llm/orchestrator.py`)

The orchestrator tries providers in this order:

1. Gemini (Flash-Lite model)
2. Groq with `openai/gpt-oss-120b`
3. Groq with `openai/gpt-oss-20b`
4. DeepSeek

Providers without configured API keys are skipped. Model names are read from `.env` so they can be changed without modifying the source code.

A few implementation details:

- Gemini and Groq were both used during the live run. DeepSeek is implemented as an optional provider but was not tested against the real API.
- Both Groq models use the same API key and account. They are separate model options, not independent provider quotas.
- For HTTP 429 responses, requests are retried using jittered backoff. If retries are exhausted, the provider enters a 15-second cooldown and workers can move to the next provider.
- For HTTP 413 responses and context overflow, the input is limited using a per-provider token budget. If a provider still rejects the request, the budget is halved and the request is retried, up to three times.
- The fallback logic is covered by unit tests using fake providers.

**Chunker** (`src/llm/chunker.py`)

The chunker keeps the beginning of a page along with paragraphs containing useful product and pricing information, such as currency symbols, "plan", "per month" and similar terms. The selected paragraphs retain their original order.

**Grounding validator** (`src/llm/grounding.py`)

A product name must appear in the text supplied to the model. Pricing information is retained only when the model also returns a supporting sentence that appears verbatim in that text.

**Entity resolver** (`src/resolver/resolver.py`)

Entity resolution is deterministic and does not use an LLM. Names are normalized and checked through exact matching, alias matching and fuzzy matching with a high threshold and an ambiguity margin. If the match is uncertain, the name stays unresolved.

The resolver is seeded with 50 known AI startups in `data/seed/startups.json`. For example, "OpenAI", "OpenAI, Inc." and "Open AI" resolve to the canonical name `OpenAI`. Each resolution decision is recorded in the entity mapping log.

**Date normalization** (`src/utils/dates.py`)

The date utility handles ISO-8601, RFC-2822, Unix timestamps in seconds and milliseconds, and relative dates such as "2 hours ago", converting them to UTC.

**Seen-set and deduplication** (`src/utils/seen.py`)

The current implementation uses a SQLite table. A single `INSERT OR IGNORE` operation on a URL hash determines which worker gets to process an item.

For a distributed deployment, the architecture document proposes replacing this with a PostgreSQL unique constraint or Redis `SET NX`. This is a proposed production design, not part of the current implementation.

**Browser fallback** (`src/crawlers/browser.py`)

An asynchronous Playwright pool is used for pages that return 403 responses or contain too little text when fetched using regular HTTP.

## Freshness

Items with a source date must fall within the previous 24 hours.

For Greenhouse listings, `first_published` is used instead of `updated_at`, since `updated_at` can change whenever a posting is edited.

For sources without publication dates, the pipeline uses a first-seen heuristic. On the first run, it records a baseline. On subsequent runs, URLs that were not part of that baseline can be treated as new.

The CSV exporter checks the 24-hour window again, so stale records are not included simply because they were present in an earlier output file.

## Anti-bot approach

The crawler follows a straightforward approach:

1. Try regular async HTTP first, respecting `robots.txt` and keeping per-domain concurrency low.
2. Prefer official APIs and feeds wherever they are available.
3. Use Playwright for blocked or JavaScript-rendered pages when appropriate.
4. Detect Cloudflare and Datadome challenge pages and skip them rather than attempting to bypass them.

These four steps are implemented in the project.

For a production deployment, `architecture.pdf` discusses possible improvements such as residential proxy rotation, per-domain rate budgets, session reuse and a managed unblocking service as a paid last resort. These are proposed improvements and are not currently implemented.

## Setup

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
copy .env.example .env
python -m pytest tests -q
```

Fill in the required values in `.env`:

- `GITHUB_TOKEN` is used to retrieve GitHub star counts. No additional scopes are required.
- `GROQ_API_KEY` and `GEMINI_API_KEY` are used by the LLM provider chain.
- `DEEPSEEK_API_KEY` is optional.
- `GEMINI_MODEL`, `GROQ_MODEL`, `GROQ_MODEL_2` and `DEEPSEEK_MODEL` can be changed when a provider retires or replaces a model.

Do not commit `.env` or API credentials to the repository.

## Running it

The individual pipelines can be run using:

```powershell
python -m src.pipeline.papers --target 1000
python -m src.pipeline.startups --target 1500
python -m src.pipeline.products --target 1100 --workers 4 --llm-concurrency 1 --page-tokens 700
python -m src.pipeline.products_browser --limit 60
python -m src.pipeline.signals --reset-seen
python -m src.export.csv_export
```

The products pipeline is resumable. If a run stops because of rate limits or another interruption, running the same command again continues from the previously saved progress.

The `signals --reset-seen` command resets the seen-set state. Use it only when a fresh collection is intended and after checking its effect on the existing deduplication history. Run the signals pipeline and CSV export close to submission time so that the jobs and news datasets reflect the latest 24-hour window.

## Project layout

```text
src/
  crawlers/   arxiv, github, yc, jobs, news, browser
  llm/        orchestrator, chunker, grounding, tasks
  resolver/   entity resolver
  pipeline/   papers, startups, products, products_browser, signals
  utils/      http, dates, seen, robots, text, logging
  export/     csv_export

scripts/      helper scripts for checking source endpoints
data/seed/    the 50-startup seed list
tests/        unit tests
docs/         architecture notes (PDF is in the repository root)
```

## Known limitations

- DeepSeek is implemented as an optional provider but was not tested against the real API. Gemini and Groq were used during the live run.
- Product extraction speed was limited mainly by free-tier LLM rate limits. A significant part of the run time was spent waiting for 429 cooldowns.
- The number of jobs and news items within a 24-hour window is naturally small and depends on when the pipeline is run.
- All startup records come from the Y Combinator directory. The AI filter is deliberately broad, so some borderline companies may be included.
- GitHub links for research papers are extracted from their abstracts. Low-confidence links may point to tools mentioned by the paper rather than code written for it.
- Some websites block even browser-based requests. These are logged with a reason and skipped rather than bypassed.
- The repository generates CSV files but does not automatically upload them to Google Sheets. Importing the files into the Sheet is a manual step.
- The 500,000+ record scale described in `architecture.pdf` is a design target, not a benchmark. The current implementation was tested on a dataset containing a few thousand records.

## Author

**Neelisetty Venkata Naga Teja**  
B.Tech CSE (AI & ML), VIT Chennai | BS Data Science, IIT Madras  
[GitHub](https://github.com/25f2005396)