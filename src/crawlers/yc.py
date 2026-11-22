import json
import re
import time

from src.config import OUTPUT_DIR
from src.utils.http import AsyncFetcher
from src.utils.logging import get_logger

log = get_logger("yc")

YC_ALL = "https://yc-oss.github.io/api/companies/all.json"
CACHE_PATH = OUTPUT_DIR / "yc_all_cache.json"
CACHE_MAX_AGE = 24 * 3600

AI_TAGS = {"ai", "artificial intelligence", "machine learning", "generative ai",
           "llm", "deep learning", "computer vision", "nlp", "ai assistant",
           "ai-enabled services", "conversational ai", "ml"}
AI_TEXT = re.compile(r"\b(ai|a\.i\.|artificial intelligence|machine learning|llm|llms|"
                     r"generative|gpt|neural|deep learning|computer vision|agents?)\b", re.I)


def is_ai_company(c: dict) -> bool:
    labels = {t.lower() for t in (c.get("tags") or [])}
    labels |= {i.lower() for i in (c.get("industries") or [])}
    if labels & AI_TAGS:
        return True
    text = f"{c.get('one_liner') or ''} {c.get('subindustry') or ''}"
    return bool(AI_TEXT.search(text))


async def fetch_yc_companies(fetcher=None) -> list[dict]:
    """Load the YC directory from a local cache, else download it patiently.
    The `fetcher` argument is kept for compatibility and is not used."""
    if CACHE_PATH.exists() and time.time() - CACHE_PATH.stat().st_mtime < CACHE_MAX_AGE:
        log.info("yc_cache_hit", path=str(CACHE_PATH))
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    async with AsyncFetcher(concurrency=1, max_retries=6, base_delay=2.0,
                            max_delay=30.0, timeout=90.0) as f:
        resp = await f.get(YC_ALL)
    resp.raise_for_status()
    data = resp.json()
    CACHE_PATH.write_text(json.dumps(data), encoding="utf-8")
    log.info("yc_downloaded", companies=len(data))
    return data