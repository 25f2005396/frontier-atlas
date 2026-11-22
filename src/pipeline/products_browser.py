import argparse
import asyncio
import collections
import json

from src.config import OUTPUT_DIR
from src.crawlers.browser import BrowserPool
from src.crawlers.yc import fetch_yc_companies
from src.llm.chunker import truncate_to_budget
from src.llm.grounding import is_grounded
from src.llm.orchestrator import AllProvidersFailed, LLMOrchestrator
from src.llm.tasks import extract_product
from src.resolver.resolver import EntityResolver
from src.schemas import ProductContent, ProductRecord, Source
from src.utils.http import AsyncFetcher
from src.utils.logging import get_logger, setup_logging
from src.utils.robots import Robots

log = get_logger("products_browser")

RETRY_REASONS = {"blocked_403", "blocked_401", "too_little_text_js_rendered"}


async def run(limit: int, pages: int, page_tokens: int) -> None:
    out_path = OUTPUT_DIR / "products.jsonl"
    rej_path = OUTPUT_DIR / "products_rejected.jsonl"
    browser_rej = OUTPUT_DIR / "products_browser_rejected.jsonl"
    done_path = OUTPUT_DIR / "products_browser_done_ids.txt"

    targets = []
    if rej_path.exists():
        for line in rej_path.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("reason") in RETRY_REASONS:
                targets.append(r)
    done = set(done_path.read_text().split()) if done_path.exists() else set()
    targets = [t for t in targets if str(t["id"]) not in done][:limit]

    companies = {c["id"]: c for c in await fetch_yc_companies()}
    seen = set()
    for line in out_path.open(encoding="utf-8"):
        c = json.loads(line)["content"]
        seen.add((c["startupName"].lower(), c["productName"].lower()))

    resolver = EntityResolver()
    reasons = collections.Counter()
    kept = 0
    log.info("start", candidates=len(targets))

    async with AsyncFetcher(concurrency=5, max_retries=1, timeout=15.0) as fetcher:
        robots = Robots(fetcher)
        async with BrowserPool(concurrency=pages) as pool, LLMOrchestrator(concurrency=2) as llm:
            with out_path.open("a", encoding="utf-8") as fo, \
                    browser_rej.open("a", encoding="utf-8") as fr, \
                    done_path.open("a", encoding="utf-8") as fd:

                async def handle(t):
                    nonlocal kept
                    c = companies.get(t["id"])
                    reason, record = None, None
                    site = (c or {}).get("website", "")
                    if not site:
                        reason = "no_website"
                    else:
                        if not site.startswith(("http://", "https://")):
                            site = "https://" + site
                        if not await robots.allowed(site):
                            reason = "robots_disallow"
                        else:
                            url, text, err = await pool.get_text(site)
                            if err:
                                reason = err
                            elif len(text) < 300:
                                reason = "still_too_little_text"
                            else:
                                body = truncate_to_budget(f"[PAGE: {url}]\n{text}", page_tokens)
                                try:
                                    clean, why, _ = await extract_product(llm, c["name"], body)
                                except AllProvidersFailed:
                                    return                      # not marked done; retried next run
                                if clean is None:
                                    reason = why
                                else:
                                    startup = resolver.resolve(c["name"]).canonical or c["name"]
                                    key = (startup.lower(), clean["product_name"].lower())
                                    if key in seen:
                                        reason = "duplicate"
                                    else:
                                        seen.add(key)
                                        record = ProductRecord(
                                            source=Source(name="Company website (browser)", url=url),
                                            content=ProductContent(
                                                startupName=startup, productName=clean["product_name"],
                                                pricingModel=clean["pricing_model"],
                                                pricing_evidence=clean["pricing_evidence"]))
                    if record:
                        fo.write(record.model_dump_json() + "\n")
                        fo.flush()
                        kept += 1
                    else:
                        reasons[reason] += 1
                        fr.write(json.dumps({"id": t["id"], "name": t["name"], "reason": reason}) + "\n")
                        fr.flush()
                    fd.write(f"{t['id']}\n")
                    fd.flush()

                await asyncio.gather(*(handle(t) for t in targets))

    log.info("done", recovered=kept, rejects=dict(reasons))


if __name__ == "__main__":
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=60)
    ap.add_argument("--pages", type=int, default=3)
    ap.add_argument("--page-tokens", type=int, default=700)
    args = ap.parse_args()
    asyncio.run(run(args.limit, args.pages, args.page_tokens))