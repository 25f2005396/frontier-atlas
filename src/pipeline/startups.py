import argparse
import asyncio
import csv
import json

from src.config import OUTPUT_DIR
from src.crawlers.yc import fetch_yc_companies, is_ai_company
from src.resolver.resolver import EntityResolver
from src.schemas import Source, StartupContent, StartupData, StartupRecord
from src.utils.http import AsyncFetcher
from src.utils.logging import get_logger, setup_logging

log = get_logger("startups")


async def run(target: int) -> None:
    out_path = OUTPUT_DIR / "startups.jsonl"
    map_path = OUTPUT_DIR / "entity_mapping_log.csv"
    rej_path = OUTPUT_DIR / "startups_rejected.jsonl"

    async with AsyncFetcher(concurrency=5) as fetcher:
        companies = await fetch_yc_companies(fetcher)
    log.info("fetched", total=len(companies))

    resolver = EntityResolver()
    seen: set[str] = set()
    kept = 0

    with out_path.open("w", encoding="utf-8") as fo, \
            rej_path.open("w", encoding="utf-8") as fr:
        for c in companies:
            name = (c.get("name") or "").strip()
            url = c.get("url")
            if not name or not url:
                fr.write(json.dumps({"id": c.get("id"), "reason": "missing_name_or_url"}) + "\n")
                continue
            if not is_ai_company(c):
                continue
            res = resolver.resolve(name)
            canonical = res.canonical or name
            key = canonical.lower()
            if key in seen:
                fr.write(json.dumps({"name": name, "reason": "duplicate"}) + "\n")
                continue
            seen.add(key)

            team = c.get("team_size")
            record = StartupRecord(
                source=Source(name="Y Combinator", url=url),
                content=StartupContent(
                    entityName=canonical,
                    data=StartupData(employeeCount=team if isinstance(team, int) and team >= 0 else None),
                ),
            )
            fo.write(record.model_dump_json() + "\n")
            kept += 1
            if kept >= target:
                break

    with map_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["raw", "canonical", "method", "score"])
        w.writeheader()
        for row in resolver.log_rows():
            w.writerow(row)

    matched = sum(1 for r in resolver.log if r.canonical)
    log.info("done", kept=kept, seed_matches=matched, output=str(out_path))


if __name__ == "__main__":
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1500)
    args = ap.parse_args()
    asyncio.run(run(args.target))