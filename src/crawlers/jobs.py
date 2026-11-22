import asyncio
import re

from src.utils.http import AsyncFetcher, FetchError
from src.utils.logging import get_logger

log = get_logger("jobs")

GREENHOUSE = {"anthropic": "Anthropic", "databricks": "Databricks", "scaleai": "Scale AI", "stabilityai": "Stability AI", "togetherai": "Together AI"}
ASHBY = {"openai": "OpenAI", "cohere": "Cohere", "perplexity": "Perplexity", "runway": "Runway", "elevenlabs": "ElevenLabs", "modal": "Modal", "replit": "Replit", "sierra": "Sierra", "harvey": "Harvey"}
LEVER = {"palantir": "Palantir"}

AI_RE = re.compile(r"\b(ai|a\.i\.|ml|machine learning|llm|llms|deep learning|nlp|computer vision|"
                   r"data scientist|research scientist|generative|neural|gpt|mlops)\b", re.I)
REMOTE_RE = re.compile(r"\bremote\b", re.I)

ROLE_RULES = [
    ("Legal", r"\b(legal|counsel|attorney|paralegal|compliance)\b"),
    ("Finance", r"\b(finance|financial|accounting|accountant|controller|tax|payroll)\b"),
    ("People", r"\b(recruit\w*|talent|people|hr|human resources)\b"),
    ("Research", r"\b(research\w*|scientist)\b"),
    ("Design", r"\b(design\w*|ux|ui)\b"),
    ("Data", r"\b(data|analytics|analyst)\b"),
    ("Sales", r"\b(sales|account executive|account manager|business development|solutions|partnerships?|go-to-market|gtm)\b"),
    ("Marketing", r"\b(marketing|brand|content|communications|growth|community)\b"),
    ("Customer Success", r"\b(customer|support)\b"),
    ("Engineering", r"\b(engineer\w*|developer|software|sre|devops|architect|infrastructure|security|programmer)\b"),
    ("Product", r"\b(product|program manager|technical program)\b"),
    ("Operations", r"\b(operations|ops|administrat\w*|facilities|chief of staff|strategy|office)\b"),
]
ROLE_RES = [(name, re.compile(rx, re.I)) for name, rx in ROLE_RULES]


def role_family(title: str, department: str = "") -> str:
    """Deterministic keyword rules: title first, department as fallback."""
    for text in (title or "", department or ""):
        for name, rx in ROLE_RES:
            if rx.search(text):
                return name
    return "Other"


def _job(source, company, title, url, raw_date, is_remote, department=""):
    return {"source": source, "company": company, "title": (title or "").strip(), "url": url,
            "raw_date": raw_date, "is_remote": bool(is_remote), "department": department or ""}


async def _json(fetcher: AsyncFetcher, url: str, name: str):
    try:
        r = await fetcher.get(url)
    except FetchError as exc:
        log.warning("source_failed", source=name, error=str(exc)[:120])
        return None
    if r.status_code != 200:
        log.warning("source_status", source=name, status=r.status_code)
        return None
    try:
        return r.json()
    except ValueError:
        log.warning("source_bad_json", source=name)
        return None


async def greenhouse(fetcher, slug, label):
    data = await _json(fetcher, f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", f"greenhouse:{slug}")
    out = []
    for j in (data or {}).get("jobs", []):
        loc = (j.get("location") or {}).get("name") or ""
        out.append(_job("Greenhouse", j.get("company_name") or label, j.get("title"), j.get("absolute_url"),
                        j.get("first_published"), REMOTE_RE.search(loc)))
    return out


async def ashby(fetcher, slug, label):
    data = await _json(fetcher, f"https://api.ashbyhq.com/posting-api/job-board/{slug}", f"ashby:{slug}")
    out = []
    for j in (data or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        wt = j.get("workplaceType")
        remote = (wt == "Remote") if wt else bool(j.get("isRemote"))
        out.append(_job("Ashby", label, j.get("title"), j.get("jobUrl"), j.get("publishedAt"),
                        remote or REMOTE_RE.search(j.get("location") or ""),
                        j.get("department") or j.get("team") or ""))
    return out


async def lever(fetcher, slug, label):
    data = await _json(fetcher, f"https://api.lever.co/v0/postings/{slug}?mode=json", f"lever:{slug}")
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        cats = j.get("categories") or {}
        remote = j.get("workplaceType") == "remote" or REMOTE_RE.search(cats.get("location") or "")
        out.append(_job("Lever", label, j.get("text"), j.get("hostedUrl"), j.get("createdAt"), remote,
                        cats.get("team") or cats.get("department") or ""))
    return out


async def remoteok(fetcher, *_):
    data = await _json(fetcher, "https://remoteok.com/api", "remoteok")
    out = []
    for j in data or []:
        if not isinstance(j, dict) or not j.get("position"):
            continue
        if not AI_RE.search(f"{j['position']} {' '.join(j.get('tags') or [])}"):
            continue
        out.append(_job("RemoteOK", j.get("company") or "", j["position"], j.get("url"), j.get("date"), True))
    return out


async def remotive(fetcher, *_):
    data = await _json(fetcher, "https://remotive.com/api/remote-jobs?limit=100", "remotive")
    out = []
    for j in (data or {}).get("jobs", []):
        if not AI_RE.search(f"{j.get('title', '')} {' '.join(j.get('tags') or [])} {j.get('category', '')}"):
            continue
        out.append(_job("Remotive", j.get("company_name") or "", j.get("title"), j.get("url"),
                        j.get("publication_date"), True, j.get("category") or ""))
    return out


async def fetch_all_jobs(fetcher: AsyncFetcher) -> list[dict]:
    tasks = [greenhouse(fetcher, s, n) for s, n in GREENHOUSE.items()]
    tasks += [ashby(fetcher, s, n) for s, n in ASHBY.items()]
    tasks += [lever(fetcher, s, n) for s, n in LEVER.items()]
    tasks += [remoteok(fetcher), remotive(fetcher)]
    jobs = []
    for res in await asyncio.gather(*tasks, return_exceptions=True):
        if isinstance(res, Exception):
            log.warning("adapter_error", error=repr(res)[:150])
            continue
        jobs.extend(res)
    return jobs