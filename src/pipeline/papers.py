import argparse
import asyncio
import json

from src.config import OUTPUT_DIR
from src.crawlers.arxiv import fetch_page, parse_entries
from src.crawlers.github import fetch_repo_stats
from src.schemas import PaperContent, ResearchPaperRecord, Source
from src.utils.http import AsyncFetcher
from src.utils.logging import get_logger, setup_logging

log = get_logger("papers")

QUERY = 'abs:"github.com" AND (cat:cs.LG OR cat:cs.CL OR cat:cs.CV OR cat:cs.AI)'


async def run(target: int, page_size: int, arxiv_delay: float) -> None:
    out_path = OUTPUT_DIR / "research_papers.jsonl"
    rej_path = OUTPUT_DIR / "papers_rejected.jsonl"
    seen: set[str] = set()
    kept, start = 0, 0

    with out_path.open("w", encoding="utf-8") as fo, \
            rej_path.open("w", encoding="utf-8") as fr:
        async with AsyncFetcher(concurrency=10) as fetcher:
            while kept < target:
                feed = await fetch_page(fetcher, QUERY, start, page_size)
                if not feed.entries:
                    log.info("no_more_results", start=start)
                    break
                start += page_size

                fresh = [c for c in parse_entries(feed) if c["arxiv_id"] not in seen]
                fresh = fresh[: target - kept]
                seen.update(c["arxiv_id"] for c in fresh)

                stats = await asyncio.gather(
                    *(fetch_repo_stats(fetcher, c["owner"], c["repo"]) for c in fresh),
                    return_exceptions=True,
                )

                for c, s in zip(fresh, stats):
                    if isinstance(s, Exception) or s is None:
                        reason = repr(s) if isinstance(s, Exception) else "repo_not_found"
                        fr.write(json.dumps({**c, "reason": reason}) + "\n")
                        continue
                    record = ResearchPaperRecord(
                        source=Source(name="arXiv", url=c["paper_url"]),
                        content=PaperContent(
                            title=c["title"],
                            authors=c["authors"],
                            paper_url=c["paper_url"],
                            github_url=s["html_url"],
                            github_stars=s["stars"],
                            github_stars_fetched_at=s["fetched_at"],
                            github_link_confidence=c["link_confidence"],
                            published_date=c["published"],
                        ),
                    )
                    fo.write(record.model_dump_json() + "\n")
                    kept += 1
                    if kept >= target:
                        break

                fo.flush()
                log.info("progress", kept=kept, target=target, scanned_offset=start)
                await asyncio.sleep(arxiv_delay)  # arXiv asks for ~1 request / 3 s

    log.info("done", kept=kept, output=str(out_path))


if __name__ == "__main__":
    setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=1000)
    ap.add_argument("--page-size", type=int, default=100)
    ap.add_argument("--arxiv-delay", type=float, default=3.0)
    args = ap.parse_args()
    asyncio.run(run(args.target, args.page_size, args.arxiv_delay))