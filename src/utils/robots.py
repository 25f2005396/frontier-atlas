from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

from src.config import USER_AGENT
from src.utils.http import AsyncFetcher


class Robots:
    """Per-domain robots.txt cache. Missing or unreadable robots.txt means allowed."""

    def __init__(self, fetcher: AsyncFetcher):
        self.fetcher = fetcher
        self.cache: dict[str, RobotFileParser] = {}

    async def allowed(self, url: str) -> bool:
        p = urlparse(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            rp = RobotFileParser()
            try:
                r = await self.fetcher.get(base + "/robots.txt")
                ctype = r.headers.get("content-type", "").lower()
                if r.status_code == 200 and "html" not in ctype:
                    rp.parse(r.text.splitlines())
                    rp.modified()
                else:
                    rp.allow_all = True
            except Exception:
                rp.allow_all = True
            self.cache[base] = rp
        return self.cache[base].can_fetch(USER_AGENT, url)