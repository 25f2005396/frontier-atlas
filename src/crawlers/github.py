from datetime import datetime, timezone

from src.config import GITHUB_TOKEN
from src.utils.http import AsyncFetcher


async def fetch_repo_stats(fetcher: AsyncFetcher, owner: str, repo: str) -> dict | None:
    """Return live stats for a repo, or None if it doesn't exist (deleted/private)."""
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"

    resp = await fetcher.get(f"https://api.github.com/repos/{owner}/{repo}", headers=headers)
    if resp.status_code in (404, 410, 451):
        return None
    resp.raise_for_status()
    data = resp.json()
    return {
        "stars": data["stargazers_count"],
        "html_url": data["html_url"],
        "fetched_at": datetime.now(timezone.utc),
    }