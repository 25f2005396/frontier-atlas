import argparse
import asyncio
import collections
import json
from urllib.parse import urlparse

from src.config import OUTPUT_DIR
from src.crawlers.yc import fetch_yc_companies, is_ai_company
from src.llm.chunker import truncate_to_budget
from src.llm.grounding import is_grounded
from src.llm.orchestrator import AllProvidersFailed, LLMOrchestrator
from src.llm.tasks import extract_product
from src.resolver.resolver import EntityResolver
from src.schemas import ProductContent, ProductRecord, Source
from src.utils.http import AsyncFetcher, FetchError
from src.utils.logging import get_logger, setup_logging
from src.utils.robots import Robots
from src.utils.text import html_to_text

log = get_logger("products")


async def get_text(fetcher: AsyncFetcher, url: str):
    """Return (final_url, text, error_reason)."""
    try:
        r = await fetcher.get(url)
    except FetchError:
        return url, "", "fetch_failed"
    except Exception as exc:
        return url, "", f"error_{type(exc).__name__}"
    if r.status_code in (401, 403):
        return url, "", f"blocked_{r.status_code}"
    if r.status_code >= 400:
        return url, "", f"http_{r.status_code}"
    if "html" not in r.headers.get("content-type", "").lower():
        return url, "", "not_html"
    return str(r.url), html_to_text(r.text[:2_000_000]), None


def load_ids(path) -> set[int]:
    if not path.exists():
        return set()
    return {int(x) for x in path.read_text(encoding="utf-8").split() if x.isdigit()}


async def run(target: int, workers: int, page_tokens: int, llm_concurrency: int) -> None:
    out_path = OUTPUT_DIR / "products.jsonl"
    rej_path = OUTPUT_DIR / "products_rejected.jsonl"
    done_path = OUTPUT_DIR / "products_done_ids.txt"

    seen_products: set[tuple[str, str]] = set()
    kept = 0
    if out_path.exists():
        for line in out_path.open(encoding="utf-8"):
            c = json.loads(line)["content"]
            seen_products.add((c["startupName"].lower(), c["productName"].lower()))
            kept += 1
    done_ids = load_ids(done_path)

    async with AsyncFetcher(concurrency=10, max_retries=1, base_delay=1.0,
                            max_delay=8.0, timeout=15.0) as fetcher:
        companies = [c for c in await fetch_yc_companies(fetcher)
                     if c.get("website") and c.get("status") == "Active"
                     and is_ai_company(c) and c["id"] not in done_ids]
        log.info("start", todo=len(companies), already_kept=kept, target=target)

        robots = Robots(fetcher)
        resolver = EntityResolver()
        reasons: collections.Counter = collections.Counter()
        sem = asyncio.Semaphore(workers)
        processed = 0

        async with LLMOrchestrator(concurrency=llm_concurrency) as llm:

            async def process(c):
                name = c["name"].strip()
                site = c["website"].strip()
                if not site.startswith(("http://", "https://")):
                    site = "https://" + site
                if not await robots.allowed(site):
                    return None, "robots_disallow"

                home_url, home_text, err = await get_text(fetcher, site)
                if err:
                    return None, err
                pages = [(home_url, home_text)]

                p = urlparse(home_url)
                pricing_url = f"{p.scheme}://{p.netloc}/pricing"
                if await robots.allowed(pricing_url):
                    u, t, e = await get_text(fetcher, pricing_url)
                    if not e and len(t) > 100 and u.rstrip("/") != home_url.rstrip("/"):
                        pages.append((u, t))

                if sum(len(t) for _, t in pages) < 300:
                    return None, "too_little_text_js_rendered"

                combined = "\n".join(f"[PAGE: {u}]\n{t}" for u, t in pages)
                combined = truncate_to_budget(combined, page_tokens)
                try:
                    clean, reason, provider = await extract_product(llm, name, combined)
                except AllProvidersFailed as exc:
                    return None, "llm_failed"
                if clean is None:
                    return None, reason

                startup = resolver.resolve(name).canonical or name
                key = (startup.lower(), clean["product_name"].lower())
                if key in seen_products:
                    return None, "duplicate"
                seen_products.add(key)

                source_url = next((u for u, t in pages if is_grounded(clean["product_name"], t)),
                                  pages[0][0])
                return ProductRecord(
                    source=Source(name="Company website", url=source_url),
                    content=ProductContent(
                        startupName=startup,
                        productName=clean["product_name"],
                        pricingModel=clean["pricing_model"],
                        pricing_evidence=clean["pricing_evidence"],
                    ),
                ), None

            with out_path.open("a", encoding="utf-8") as fo, \
                    rej_path.open("a", encoding="utf-8") as fr, \
                    done_path.open("a", encoding="utf-8") as fd:

                async def handle(c):
                    nonlocal kept, processed
                    if kept >= target:
                        return
                    async with sem:
                        if kept >= target:
                            return
                        try:
                            record, reason = await process(c)
                        except Exception as exc:
                            record, reason = None, f"error_{type(exc).__name__}"
                    processed += 1
                    if record is not None:
                        fo.write(record.model_dump_json() + "\n")
                        fo.flush()
                        kept += 1
                    else:
                        reasons[reason] += 1
                        fr.write(json.dumps({"id": c["id"], "name": c["name"],
                                             "website": c["website"], "reason": reason}) + "\n")
                        fr.flush()
                    if reason != "llm_failed":      # llm_failed is retried on the next run
                        fd.write(f"{c['id']}\n")
                        fd.flush()
                    if processed % 25 == 0:
                        log.info("progress", processed=processed, kept=kept,
                                 rejects=dict(reasons.most_common(5)))

                await asyncio.gather(*(handle(c) for c in companies))

    log.info("done", kept=kept, processed=processed, rejects=dict(reasons))


if __name__ == "__main__":
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1100)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--page-tokens", type=int, default=1500)
    ap.add_argument("--llm-concurrency", type=int, default=3)
    args = ap.parse_args()
    asyncio.run(run(args.target, args.workers, args.page_tokens, args.llm_concurrency))