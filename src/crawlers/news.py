import feedparser
from bs4 import BeautifulSoup

from src.utils.http import AsyncFetcher, FetchError
from src.utils.logging import get_logger

log = get_logger("news")

NEWS_FEEDS = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "MIT Technology Review": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Ars Technica": "https://arstechnica.com/ai/feed/",
    "Wired": "https://www.wired.com/feed/tag/ai/latest/rss",
}


def article_text(html) -> str:
    """Main article text from a page (bytes or str)."""
    soup = BeautifulSoup(html, "lxml")
    for t in soup(["script", "style", "noscript", "svg", "nav", "footer", "aside", "form", "iframe", "header"]):
        t.decompose()
    node = soup.find("article") or soup.find("main") or soup.body or soup
    parts = [p.get_text(" ", strip=True) for p in node.find_all(["p", "h2", "h3", "li"])]
    text = "\n".join(p for p in parts if len(p) > 1)
    return text or node.get_text("\n", strip=True)


async def fetch_feed(fetcher: AsyncFetcher, name: str, url: str) -> list[dict]:
    try:
        r = await fetcher.get(url)
    except FetchError as exc:
        log.warning("feed_failed", source=name, error=str(exc)[:120])
        return []
    if r.status_code != 200:
        log.warning("feed_status", source=name, status=r.status_code)
        return []
    items = []
    for e in feedparser.parse(r.text).entries:
        link, title = e.get("link"), e.get("title")
        if not link or not title:
            continue
        content = e.content[0].get("value", "") if e.get("content") else ""
        items.append({
            "source": name,
            "url": link,
            "title": " ".join(title.split()),
            "raw_date": e.get("published") or e.get("updated"),
            "feed_html": content or e.get("summary", ""),
            "feed_has_full": bool(content),
        })
    return items


async def fetch_article_text(fetcher: AsyncFetcher, url: str) -> str:
    try:
        r = await fetcher.get(url)
    except Exception:
        return ""
    if r.status_code != 200 or "html" not in r.headers.get("content-type", "").lower():
        return ""
    return article_text(r.content[:3_000_000])[:100_000]