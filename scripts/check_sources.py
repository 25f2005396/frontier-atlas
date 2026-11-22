import httpx

UA = {"User-Agent": "FrontierAtlasBot/1.0 (+https://github.com/25f2005396/frontier-atlas)"}
SOURCES = {
    "news: TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "news: VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "news: The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "news: MIT Tech Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "news: Hacker News (AI)": "https://hn.algolia.com/api/v1/search_by_date?query=AI&tags=story&hitsPerPage=5",
    "jobs: RemoteOK": "https://remoteok.com/api",
    "jobs: Greenhouse (anthropic)": "https://boards-api.greenhouse.io/v1/boards/anthropic/jobs",
    "jobs: Lever (mistral)": "https://api.lever.co/v0/postings/mistral?mode=json",
    "jobs: Ashby (openai)": "https://api.ashbyhq.com/posting-api/job-board/openai",
    "jobs: HN Algolia (hiring)": "https://hn.algolia.com/api/v1/search_by_date?query=hiring&tags=comment&hitsPerPage=5",
}

with httpx.Client(headers=UA, follow_redirects=True, timeout=30) as c:
    for name, url in SOURCES.items():
        try:
            r = c.get(url)
            print(f"{r.status_code}  {name}  type={r.headers.get('content-type','')[:30]}  bytes={len(r.content)}")
        except Exception as e:
            print(f"ERR  {name}  {e!r}")