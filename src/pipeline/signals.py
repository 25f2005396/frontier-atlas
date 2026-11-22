import argparse
import asyncio
import collections
import csv
import json
from datetime import timedelta

from src.config import OUTPUT_DIR
from src.crawlers.jobs import fetch_all_jobs, role_family
from src.crawlers.news import NEWS_FEEDS, fetch_article_text, fetch_feed
from src.resolver.resolver import EntityResolver
from src.schemas import JobContent, JobRecord, NewsContent, NewsRecord, Source
from src.utils.dates import now_utc, parse_date
from src.utils.http import AsyncFetcher
from src.utils.logging import get_logger, setup_logging
from src.utils.robots import Robots
from src.utils.seen import SeenStore, item_key
from src.utils.text import html_to_text

log = get_logger("signals")

WINDOW = timedelta(hours=24)
SKEW = timedelta(minutes=10)


def decide(raw_date, now, source, url, kind, seen: SeenStore, baseline: set):
    """Return (datetime, date_source, None) if the item is fresh and new, else (None, None, reason)."""
    dt = parse_date(raw_date, now)
    if dt is not None:
        if not (now - WINDOW <= dt <= now + SKEW):
            return None, None, "stale_or_future"
        date_source = "source_field"
    else:
        date_source = "first_seen_heuristic"
    if not seen.add(item_key(url), kind, source, url):
        return None, None, "already_seen"
    if dt is None:
        if source in baseline:
            return None, None, "baseline_no_date"   # first sighting of this source: record, don't emit
        dt = now
    return dt, date_source, None


async def run(reset: bool) -> None:
    now = now_utc()
    seen = SeenStore()
    if reset:
        seen.reset()
    mode = "w" if reset else "a"
    resolver = EntityResolver()
    rejects: collections.Counter = collections.Counter()
    fresh_jobs: collections.Counter = collections.Counter()
    fresh_news: collections.Counter = collections.Counter()

    async with AsyncFetcher(concurrency=8, max_retries=3, base_delay=1.0, max_delay=20.0, timeout=30.0) as fetcher:
        feeds = await asyncio.gather(*(fetch_feed(fetcher, n, u) for n, u in NEWS_FEEDS.items()))
        news_items = [i for f in feeds for i in f]
        job_items = await fetch_all_jobs(fetcher)
        log.info("fetched", news_items=len(news_items), job_items=len(job_items))

        sources = {i["source"] for i in news_items} | {i["source"] for i in job_items}
        baseline = {s for s in sources if seen.count(s) == 0}

        with (OUTPUT_DIR / "jobs.jsonl").open(mode, encoding="utf-8") as fj:
            for it in job_items:
                if not it.get("url") or not it.get("title") or not it.get("company"):
                    rejects["job:missing_field"] += 1
                    continue
                dt, dsrc, why = decide(it["raw_date"], now, it["source"], it["url"], "job", seen, baseline)
                if why:
                    rejects[f"job:{why}"] += 1
                    continue
                company = resolver.resolve(it["company"]).canonical or it["company"]
                rec = JobRecord(
                    source=Source(name=it["source"], url=it["url"]),
                    content=JobContent(company=company, title=it["title"], date=dt, is_remote=it["is_remote"],
                                       role_family=role_family(it["title"], it["department"]), date_source=dsrc))
                fj.write(rec.model_dump_json() + "\n")
                fresh_jobs[it["source"]] += 1

        candidates = []
        for it in news_items:
            dt, dsrc, why = decide(it["raw_date"], now, it["source"], it["url"], "news", seen, baseline)
            if why:
                rejects[f"news:{why}"] += 1
                continue
            candidates.append((it, dt, dsrc))

        robots = Robots(fetcher)

        async def build(it, dt, dsrc):
            page = ""
            if await robots.allowed(it["url"]):
                page = await fetch_article_text(fetcher, it["url"])
            feed_text = html_to_text(it["feed_html"])
            if len(page) >= max(500, len(feed_text)):
                text, tsrc = page, "article_page"
            else:
                text = feed_text
                tsrc = "feed_content" if it["feed_has_full"] else "feed_summary"
            if not text.strip():
                return None
            return NewsRecord(
                source=Source(name=it["source"], url=it["url"]),
                content=NewsContent(title=it["title"], published_at=dt, full_text=text,
                                    date_source=dsrc, text_source=tsrc))

        built = await asyncio.gather(*(build(*c) for c in candidates), return_exceptions=True)
        with (OUTPUT_DIR / "news.jsonl").open(mode, encoding="utf-8") as fn:
            for (it, _, _), rec in zip(candidates, built):
                if isinstance(rec, Exception) or rec is None:
                    rejects["news:no_text"] += 1
                    continue
                fn.write(rec.model_dump_json() + "\n")
                fresh_news[it["source"]] += 1

    seen.close()
    rows = {}
    for r in resolver.log_rows():
        rows.setdefault(r["raw"], r)
    with (OUTPUT_DIR / "entity_mapping_log_jobs.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["raw", "canonical", "method", "score"])
        w.writeheader()
        w.writerows(rows.values())

    log.info("done", jobs=dict(fresh_jobs), news=dict(fresh_news))
    log.info("rejects", **{k.replace(":", "_"): v for k, v in rejects.items()})


if __name__ == "__main__":
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset-seen", action="store_true",
                    help="clear the seen-set and overwrite outputs (use for a from-scratch run)")
    args = ap.parse_args()
    asyncio.run(run(args.reset_seen))