import asyncio
import random
import time

import httpx

from src.config import USER_AGENT
from src.utils.logging import get_logger

log = get_logger("http")

RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(Exception):
    pass


class AsyncFetcher:
    def __init__(self, concurrency: int = 10, max_retries: int = 6,
                 base_delay: float = 1.0, max_delay: float = 60.0,
                 timeout: float = 30.0):
        self._sem = asyncio.Semaphore(concurrency)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._client = httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
            http2=True,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._client.aclose()

    def _backoff(self, attempt: int) -> float:
        # full jitter: random value between 0 and the exponential cap
        cap = min(self.max_delay, self.base_delay * (2 ** attempt))
        return random.uniform(0, cap)

    def _server_delay(self, resp: httpx.Response) -> float | None:
        ra = resp.headers.get("Retry-After")
        if ra and ra.isdigit():
            return min(float(ra), self.max_delay)
        # GitHub primary rate limit: wait until the reset time
        if resp.status_code in (403, 429) and resp.headers.get("x-ratelimit-remaining") == "0":
            reset = resp.headers.get("x-ratelimit-reset")
            if reset and reset.isdigit():
                return min(max(float(reset) - time.time(), 1.0), self.max_delay)
        return None

    async def get(self, url: str, *, params: dict | None = None,
                  headers: dict | None = None) -> httpx.Response:
        last = "unknown"
        for attempt in range(self.max_retries + 1):
            try:
                async with self._sem:
                    resp = await self._client.get(url, params=params, headers=headers)
            except httpx.TransportError as exc:
                last = repr(exc)
                delay = self._backoff(attempt)
                log.warning("transport_error", url=url, attempt=attempt, wait=round(delay, 1))
                await asyncio.sleep(delay)
                continue

            rate_limited = resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0"
            if resp.status_code in RETRY_STATUS or rate_limited:
                last = f"HTTP {resp.status_code}"
                delay = self._server_delay(resp) or self._backoff(attempt)
                log.warning("retrying", url=url, status=resp.status_code,
                            attempt=attempt, wait=round(delay, 1))
                await asyncio.sleep(delay)  # sleep outside the semaphore
                continue
            return resp
        raise FetchError(f"{url} failed after {self.max_retries + 1} attempts ({last})")