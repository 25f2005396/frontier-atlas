import httpx
import feedparser

UA = {"User-Agent": "FrontierAtlasBot/1.0 (+https://github.com/25f2005396/frontier-atlas)"}
KEYS = ("date", "time", "created", "updated", "publish", "posted", "epoch")

RSS = {
    "TechCrunch": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "MIT TR": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Ars Technica": "https://arstechnica.com/ai/feed/",
    "Wired AI": "https://www.wired.com/feed/tag/ai/latest/rss",
}
JSON_SRC = {
    "RemoteOK": ("https://remoteok.com/api", None),
    "Greenhouse anthropic": ("https://boards-api.greenhouse.io/v1/boards/anthropic/jobs", "jobs"),
    "Ashby openai": ("https://api.ashbyhq.com/posting-api/job-board/openai", "jobs"),
    "Lever palantir": ("https://api.lever.co/v0/postings/palantir?mode=json", None),
    "Remotive": ("https://remotive.com/api/remote-jobs?category=software-dev&limit=5", "jobs"),
    "HN hiring": ("https://hn.algolia.com/api/v1/search_by_date?query=hiring&tags=comment&hitsPerPage=3", "hits"),
}

with httpx.Client(headers=UA, follow_redirects=True, timeout=60) as c:
    for name, url in RSS.items():
        print("\n=== RSS", name)
        try:
            r = c.get(url)
            f = feedparser.parse(r.text)
            print("status", r.status_code, "entries", len(f.entries))
            if f.entries:
                e = f.entries[0]
                print("keys:", sorted(e.keys())[:25])
                print("published:", e.get("published"), "| has content:", bool(e.get("content")),
                      "| summary len:", len(e.get("summary", "")))
        except Exception as ex:
            print("ERR", repr(ex))

    for name, (url, key) in JSON_SRC.items():
        print("\n=== JSON", name)
        try:
            r = c.get(url)
            data = r.json()
            items = data.get(key, []) if key else data
            if isinstance(items, dict):
                items = list(items.values())
            print("status", r.status_code, "items", len(items))
            it = items[1] if name == "RemoteOK" and len(items) > 1 else items[0]
            print("keys:", sorted(it.keys()))
            for k, v in it.items():
                if any(s in k.lower() for s in KEYS):
                    print("  ", k, "=", str(v)[:60])
            for k in ("location", "isRemote", "remote", "workplaceType", "candidate_required_location", "tags", "department"):
                if k in it:
                    print("  ", k, "=", str(it[k])[:80])
        except Exception as ex:
            print("ERR", repr(ex))