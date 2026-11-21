import asyncio
import json
import random
import re
from dataclasses import dataclass
from typing import Callable

import httpx

from src import config
from src.llm.chunker import truncate_to_budget
from src.utils.logging import get_logger

log = get_logger("llm")


class Retryable(Exception):
    def __init__(self, status: int, retry_after: float | None = None):
        super().__init__(f"retryable status {status}")
        self.status, self.retry_after = status, retry_after


class PayloadTooLarge(Exception):
    pass


class ProviderError(Exception):
    pass


class RateLimited(Exception):
    pass


class AllProvidersFailed(Exception):
    pass


@dataclass
class Provider:
    name: str
    kind: str          # "gemini" or "openai" (OpenAI-compatible)
    base_url: str
    model: str
    api_key: str
    max_tokens: int    # input budget for the chunker


@dataclass
class Extraction:
    data: dict
    provider: str
    text_sent: str     # the exact text the model saw (used for grounding checks)


def default_providers() -> list[Provider]:
    chain = [
        Provider("gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta/models",
                 config.GEMINI_MODEL, config.GEMINI_API_KEY, 6000),
        Provider("groq", "openai", "https://api.groq.com/openai/v1",
                 config.GROQ_MODEL, config.GROQ_API_KEY, 3000),
        Provider("deepseek", "openai", "https://api.deepseek.com",
                 config.DEEPSEEK_MODEL, config.DEEPSEEK_API_KEY, 6000),
    ]
    return [p for p in chain if p.api_key]


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.M).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        if not m:
            raise ValueError("no JSON object in model output")
        obj = json.loads(m.group(0))
    if not isinstance(obj, dict):
        raise ValueError("model output is not a JSON object")
    return obj


def _retry_after(resp: httpx.Response) -> float | None:
    ra = resp.headers.get("retry-after")
    try:
        return float(ra) if ra else None
    except ValueError:
        return None


class LLMOrchestrator:
    def __init__(self, providers: list[Provider] | None = None, concurrency: int = 8,
                 max_retries: int = 5, base_delay: float = 1.0, max_delay: float = 60.0,
                 max_shrinks: int = 3, timeout: float = 60.0):
        self.providers = providers if providers is not None else default_providers()
        if not self.providers:
            raise RuntimeError("No LLM API keys found. Fill GEMINI_API_KEY / GROQ_API_KEY in .env")
        self._sem = asyncio.Semaphore(concurrency)
        self.max_retries, self.base_delay, self.max_delay = max_retries, base_delay, max_delay
        self.max_shrinks, self.timeout = max_shrinks, timeout
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        if self._client:
            await self._client.aclose()

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    def _backoff(self, attempt: int) -> float:
        cap = min(self.max_delay, self.base_delay * (2 ** attempt))
        return random.uniform(0, cap)  # full jitter

    async def _call(self, p: Provider, system: str, user: str) -> str:
        if p.kind == "gemini":
            url = f"{p.base_url}/{p.model}:generateContent"
            headers = {"x-goog-api-key": p.api_key}
            body = {
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": 0, "responseMimeType": "application/json"},
            }
        else:
            url = f"{p.base_url}/chat/completions"
            headers = {"Authorization": f"Bearer {p.api_key}"}
            body = {
                "model": p.model, "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {"type": "json_object"},
            }
        async with self._sem:
            try:
                resp = await self._http().post(url, headers=headers, json=body)
            except httpx.TransportError as exc:
                raise Retryable(0) from exc

        code = resp.status_code
        if code == 200:
            try:
                data = resp.json()
                if p.kind == "gemini":
                    return data["candidates"][0]["content"]["parts"][0]["text"]
                return data["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError, ValueError) as exc:
                raise ProviderError(f"{p.name}: unexpected response shape") from exc
        if code == 413 or (code == 400 and "token" in resp.text.lower()):
            raise PayloadTooLarge()
        if code == 429 or code >= 500:
            raise Retryable(code, _retry_after(resp))
        raise ProviderError(f"{p.name} HTTP {code}: {resp.text[:200]}")

    async def _with_backoff(self, p: Provider, system: str, user: str) -> str:
        for attempt in range(self.max_retries + 1):
            try:
                return await self._call(p, system, user)
            except Retryable as exc:
                if attempt == self.max_retries:
                    break
                wait = min(exc.retry_after, self.max_delay) if exc.retry_after else self._backoff(attempt)
                log.warning("retrying", provider=p.name, status=exc.status,
                            attempt=attempt, wait=round(wait, 1))
                await asyncio.sleep(wait)  # sleep outside the semaphore
        raise RateLimited(p.name)

    async def extract(self, text: str, system: str, build_user: Callable[[str], str]) -> Extraction:
        errors = []
        for p in self.providers:
            budget = p.max_tokens
            for _ in range(self.max_shrinks + 1):
                payload = truncate_to_budget(text, budget)
                try:
                    raw = await self._with_backoff(p, system, build_user(payload))
                    return Extraction(parse_json(raw), p.name, payload)
                except PayloadTooLarge:
                    budget //= 2
                    log.warning("payload_too_large", provider=p.name, new_budget=budget)
                    continue
                except (RateLimited, ProviderError, ValueError) as exc:
                    errors.append(f"{p.name}: {exc!r}")
                    log.warning("provider_failed", provider=p.name, error=repr(exc))
                    break
            else:
                errors.append(f"{p.name}: still too large after shrinking")
        raise AllProvidersFailed("; ".join(errors))