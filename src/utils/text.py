from bs4 import BeautifulSoup

META_KEYS = {"description", "og:description", "og:title", "twitter:description"}


def html_to_text(html: str) -> str:
    """Visible page text plus title and meta description (useful for JS-heavy sites)."""
    soup = BeautifulSoup(html, "lxml")
    parts: list[str] = []
    if soup.title and soup.title.string:
        parts.append(soup.title.string.strip())
    for m in soup.find_all("meta"):
        key = (m.get("name") or m.get("property") or "").lower()
        if key in META_KEYS and m.get("content"):
            parts.append(m["content"].strip())
    for tag in soup(["script", "style", "noscript", "svg", "nav", "footer", "iframe"]):
        tag.decompose()
    parts.append(soup.get_text("\n", strip=True))
    return "\n".join(p for p in parts if p)