import re

KEYWORDS = re.compile(
    r"(\$|€|£|₹|\bfree\b|\bpricing\b|\bprice\b|\bplans?\b|\benterprise\b|\bper month\b|/mo\b|"
    r"\bsubscription\b|\bcontact sales\b|\bproduct\b|\bplatform\b|\bapi\b)",
    re.I,
)
MAX_PARA = 600


def approx_tokens(text: str) -> int:
    return len(text) // 4


def _split_long(p: str) -> list[str]:
    out = []
    while len(p) > MAX_PARA:
        cut = p.rfind(" ", 0, MAX_PARA)
        cut = cut if cut > 0 else MAX_PARA
        out.append(p[:cut].strip())
        p = p[cut:].strip()
    if p:
        out.append(p)
    return out


def _paragraphs(text: str) -> list[str]:
    seen, out = set(), []
    for line in text.splitlines():
        line = " ".join(line.split())
        if len(line) < 3 or line.lower() in seen:
            continue
        seen.add(line.lower())
        out.extend(_split_long(line))
    return out


def _score(p: str) -> int:
    return 0 if len(p) < 15 else 2 * len(KEYWORDS.findall(p))


def truncate_to_budget(text: str, max_tokens: int) -> str:
    """Fit text into a token budget, keeping the page opening plus the most
    product/pricing-dense paragraphs, in their original order."""
    max_chars = max(200, max_tokens * 4)
    paras = _paragraphs(text)
    if sum(len(p) + 1 for p in paras) <= max_chars:
        return "\n".join(paras)

    keep: set[int] = set()
    used = 0
    head_budget = max_chars // 4
    for i, p in enumerate(paras):
        if used + len(p) + 1 > head_budget:
            break
        keep.add(i)
        used += len(p) + 1

    ranked = sorted(((_score(p), i) for i, p in enumerate(paras) if i not in keep), reverse=True)
    for score, i in ranked:
        if score <= 0:
            break
        if used + len(paras[i]) + 1 <= max_chars:
            keep.add(i)
            used += len(paras[i]) + 1

    for i, p in enumerate(paras):  # use any remaining room
        if i not in keep and used + len(p) + 1 <= max_chars:
            keep.add(i)
            used += len(p) + 1

    return "\n".join(paras[i] for i in sorted(keep))