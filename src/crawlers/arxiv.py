import re

import feedparser

from src.utils.http import AsyncFetcher

ARXIV_API = "https://export.arxiv.org/api/query"
GITHUB_RE = re.compile(r"https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)", re.I)
NOT_REPOS = {"features", "topics", "sponsors", "orgs", "marketplace", "about", "settings"}

RELEASE_CUES = (
    "available at", "available on", "available here", "code is", "code at",
    "released at", "released on", "publicly available", "open-source", "open source",
    "our code", "we release", "we open", "project page", "implementation", "source code",
)


def extract_github(*texts: str) -> tuple[str, str, str] | None:
    """Return (owner, repo, confidence). 'high' if a release phrase precedes the link."""
    fallback = None
    for text in texts:
        text = text or ""
        for m in GITHUB_RE.finditer(text):
            owner, repo = m.group(1), m.group(2).rstrip(".,;:)")
            if repo.lower().endswith(".git"):
                repo = repo[:-4]
            if owner.lower() in NOT_REPOS or not repo:
                continue
            window = text[max(0, m.start() - 100):m.start()].lower()
            if any(cue in window for cue in RELEASE_CUES):
                return owner, repo, "high"
            if fallback is None:
                fallback = (owner, repo, "low")
    return fallback


async def fetch_page(fetcher: AsyncFetcher, query: str, start: int, page_size: int):
    resp = await fetcher.get(ARXIV_API, params={
        "search_query": query,
        "start": start,
        "max_results": page_size,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    resp.raise_for_status()
    return feedparser.parse(resp.text)


def parse_entries(feed) -> list[dict]:
    """Keep only papers whose own text links to a GitHub repo."""
    out = []
    for e in feed.entries:
        arxiv_id = re.sub(r"v\d+$", "", e.id.split("/abs/")[-1])
        summary = " ".join((e.get("summary") or "").split())
        comment = e.get("arxiv_comment", "")
        gh = extract_github(summary, comment)
        if not gh:
            continue
        out.append({
            "arxiv_id": arxiv_id,
            "title": " ".join(e.title.split()),
            "authors": [a.get("name", "").strip() for a in e.get("authors", []) if a.get("name")],
            "published": e.published,
            "paper_url": f"https://arxiv.org/abs/{arxiv_id}",
            "owner": gh[0],
            "repo": gh[1],
            "link_confidence": gh[2],
        })
    return out