import asyncio

from playwright.async_api import async_playwright

from src.config import USER_AGENT
from src.utils.logging import get_logger
from src.utils.text import html_to_text

log = get_logger("browser")

CHALLENGE_MARKERS = (
    "just a moment", "checking your browser", "attention required",
    "verify you are human", "captcha", "access denied", "datadome",
    "enable javascript and cookies",
)


def looks_like_challenge(text: str) -> bool:
    head = (text or "")[:1500].lower()
    return any(m in head for m in CHALLENGE_MARKERS)


class BrowserPool:
    """Async Playwright with a bounded number of concurrent pages."""

    def __init__(self, concurrency: int = 3, timeout_ms: int = 25000):
        self._sem = asyncio.Semaphore(concurrency)
        self.timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._ctx = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        self._browser = await self._pw.chromium.launch(headless=True)
        self._ctx = await self._browser.new_context(
            user_agent=USER_AGENT, locale="en-US", viewport={"width": 1366, "height": 900})
        return self

    async def __aexit__(self, *exc):
        if self._ctx:
            await self._ctx.close()
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def get_text(self, url: str):
        """Return (final_url, text, error_reason)."""
        async with self._sem:
            page = await self._ctx.new_page()
            try:
                resp = await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_timeout(2500)          # let client-side rendering finish
                if resp is not None and resp.status in (401, 403, 429):
                    return url, "", f"blocked_{resp.status}"
                html = await page.content()
                text = html_to_text(html)
                if looks_like_challenge(text):
                    return url, "", "challenge_detected"
                return page.url, text, None
            except Exception as exc:
                return url, "", f"browser_{type(exc).__name__}"
            finally:
                await page.close()