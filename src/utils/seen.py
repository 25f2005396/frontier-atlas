import hashlib
import sqlite3
from datetime import datetime, timezone
from urllib.parse import parse_qsl, urlencode, urlparse

from src.config import OUTPUT_DIR

DB_PATH = OUTPUT_DIR / "seen.sqlite"


def item_key(url: str) -> str:
    """Stable id for an article/job URL: lowercase host, no fragment, no utm_* params."""
    p = urlparse(url.strip())
    q = urlencode([(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith("utm_")])
    canon = f"{p.scheme.lower()}://{p.netloc.lower()}{p.path.rstrip('/')}" + (f"?{q}" if q else "")
    return hashlib.sha1(canon.encode("utf-8")).hexdigest()


class SeenStore:
    def __init__(self, path=DB_PATH):
        self.con = sqlite3.connect(str(path))
        self.con.execute("CREATE TABLE IF NOT EXISTS seen "
                         "(key TEXT PRIMARY KEY, kind TEXT, source TEXT, url TEXT, first_seen TEXT)")
        self.con.commit()

    def add(self, key: str, kind: str, source: str, url: str) -> bool:
        """Atomically claim an item. True only for the first claimer."""
        cur = self.con.execute("INSERT OR IGNORE INTO seen VALUES (?,?,?,?,?)",
                               (key, kind, source, url, datetime.now(timezone.utc).isoformat()))
        self.con.commit()
        return cur.rowcount == 1

    def count(self, source: str) -> int:
        return self.con.execute("SELECT COUNT(*) FROM seen WHERE source = ?", (source,)).fetchone()[0]

    def reset(self) -> None:
        self.con.execute("DELETE FROM seen")
        self.con.commit()

    def close(self) -> None:
        self.con.close()