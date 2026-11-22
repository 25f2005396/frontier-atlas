import httpx

UA = {"User-Agent": "FrontierAtlasBot/1.0 (+https://github.com/25f2005396/frontier-atlas)"}
CANDIDATES = {
    "greenhouse": ["anthropic", "databricks", "scaleai", "stabilityai", "cerebrassystems", "togetherai",
                   "glean", "pinecone", "anyscale", "samsara", "figma", "airtable", "cloudflare"],
    "ashby": ["openai", "cohere", "perplexity", "runway", "elevenlabs", "modal", "replit", "sierra",
              "harvey", "notion", "ramp", "linear"],
    "lever": ["palantir", "mistral", "weightsandbiases", "wandb", "spotify", "plaid"],
}
URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{}",
    "lever": "https://api.lever.co/v0/postings/{}?mode=json",
}

with httpx.Client(headers=UA, follow_redirects=True, timeout=60) as c:
    for kind, slugs in CANDIDATES.items():
        for s in slugs:
            try:
                r = c.get(URLS[kind].format(s))
                n = "-"
                if r.status_code == 200:
                    d = r.json()
                    n = len(d.get("jobs", [])) if isinstance(d, dict) else len(d)
                print(f"{kind:11} {s:18} {r.status_code}  jobs={n}")
            except Exception as e:
                print(f"{kind:11} {s:18} ERR {e!r}"[:100])