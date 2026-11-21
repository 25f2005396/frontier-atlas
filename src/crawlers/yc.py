import re

from src.utils.http import AsyncFetcher

YC_ALL = "https://yc-oss.github.io/api/companies/all.json"

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


async def fetch_yc_companies(fetcher: AsyncFetcher) -> list[dict]:
    resp = await fetcher.get(YC_ALL)
    resp.raise_for_status()
    return resp.json()