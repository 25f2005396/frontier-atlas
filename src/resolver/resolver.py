import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from rapidfuzz import fuzz, process

from src.config import ROOT

SEED_PATH = ROOT / "data" / "seed" / "startups.json"

LEGAL_TOKENS = {
    "inc", "incorporated", "ltd", "limited", "llc", "lp", "corp", "corporation",
    "co", "company", "gmbh", "plc", "pbc", "bv", "sa", "ag",
}

FUZZY_THRESHOLD = 92      # similarity needed for an automatic match
AMBIGUITY_MARGIN = 3      # runner-up this close to the best => refuse to guess
MIN_FUZZY_LEN = 6         # short names are exact-match only (avoids false positives)


def normalize(name: str) -> str:
    """'OpenAI, Inc.' -> 'openai'; 'Open AI' -> 'openai'; 'W&B' -> 'wandb'."""
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    tokens = [t for t in s.split() if t not in LEGAL_TOKENS]
    if tokens and tokens[0] == "the":
        tokens = tokens[1:]
    return "".join(tokens)


@dataclass
class Resolution:
    raw: str
    canonical: Optional[str]
    method: str            # exact | alias | fuzzy | unresolved
    score: float


class EntityResolver:
    def __init__(self, seed_path: Path = SEED_PATH):
        self.index: dict[str, tuple[str, str]] = {}   # key -> (canonical, "exact"|"alias")
        for entry in json.loads(Path(seed_path).read_text(encoding="utf-8")):
            canon = entry["canonical"]
            self._add(normalize(canon), canon, "exact")
            for alias in entry.get("aliases", []):
                self._add(normalize(alias), canon, "alias")
        self.keys = list(self.index)
        self.log: list[Resolution] = []

    def _add(self, key: str, canon: str, kind: str) -> None:
        existing = self.index.get(key)
        if existing and existing[0] != canon:
            raise ValueError(f"Seed collision: '{key}' maps to both {existing[0]} and {canon}")
        self.index.setdefault(key, (canon, kind))

    def resolve(self, raw: str) -> Resolution:
        key = normalize(raw)
        result = self._resolve_key(raw, key)
        self.log.append(result)
        return result

    def _resolve_key(self, raw: str, key: str) -> Resolution:
        if not key:
            return Resolution(raw, None, "unresolved", 0.0)
        if key in self.index:
            canon, kind = self.index[key]
            return Resolution(raw, canon, kind, 100.0)

        if len(key) >= MIN_FUZZY_LEN:
            matches = process.extract(key, self.keys, scorer=fuzz.ratio, limit=5)
            best_per_canon: dict[str, float] = {}
            for k, score, _ in matches:
                canon = self.index[k][0]
                best_per_canon[canon] = max(best_per_canon.get(canon, 0), score)
            ranked = sorted(best_per_canon.items(), key=lambda kv: -kv[1])
            if ranked and ranked[0][1] >= FUZZY_THRESHOLD:
                ambiguous = len(ranked) > 1 and ranked[0][1] - ranked[1][1] < AMBIGUITY_MARGIN
                if not ambiguous:
                    return Resolution(raw, ranked[0][0], "fuzzy", round(ranked[0][1], 1))
        return Resolution(raw, None, "unresolved", 0.0)

    def log_rows(self) -> list[dict]:
        return [asdict(r) for r in self.log]