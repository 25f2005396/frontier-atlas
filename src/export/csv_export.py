import csv
import json
from datetime import datetime, timedelta, timezone

from src.config import OUTPUT_DIR

EXPORT_DIR = OUTPUT_DIR / "export"
EXPORT_DIR.mkdir(parents=True, exist_ok=True)
MAX_CELL = 40000
UTC = timezone.utc

TABS = [
    # tab name, source file, minimum rows, date field for the 24h filter
    ("Startups", "startups.jsonl", 1000, None),
    ("Products", "products.jsonl", 1000, None),
    ("Research Papers", "research_papers.jsonl", 1000, None),
    ("Jobs", "jobs.jsonl", 0, "content.date"),
    ("News", "news.jsonl", 0, "content.published_at"),
]


def flatten(d, prefix=""):
    out = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten(v, key + "."))
        elif isinstance(v, list):
            out[key] = "; ".join(str(x) for x in v)
        else:
            out[key] = v
    return out


def load_jsonl(name):
    path = OUTPUT_DIR / name
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return [flatten(json.loads(line)) for line in f if line.strip()]


def is_fresh(value, now):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return now - timedelta(hours=24) <= dt <= now + timedelta(minutes=10)


def write_csv(tab, rows):
    fields = []
    for r in rows:
        for k in r:
            if k not in fields:
                fields.append(k)
    path = EXPORT_DIR / f"{tab}.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: (v[:MAX_CELL] if isinstance(v, str) else v) for k, v in r.items()})


def mapping_rows():
    rows = {}
    for name in ("entity_mapping_log.csv", "entity_mapping_log_jobs.csv"):
        path = OUTPUT_DIR / name
        if path.exists():
            with path.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    rows.setdefault(r["raw"], r)
    return list(rows.values())


def main():
    now = datetime.now(UTC)
    print(f"Export time (UTC): {now.isoformat(timespec='seconds')}")
    for tab, fname, minimum, date_field in TABS:
        rows = load_jsonl(fname)
        if date_field:
            rows = [r for r in rows if is_fresh(r.get(date_field), now)]
        write_csv(tab, rows)
        flag = "" if len(rows) >= minimum else f"   <-- below minimum of {minimum}"
        print(f"{tab:16} {len(rows):6} rows{flag}")
    m = mapping_rows()
    write_csv("Entity Mapping Log", m)
    print(f"{'Entity Mapping Log':16} {len(m):6} rows")
    print(f"CSV files are in {EXPORT_DIR}")


if __name__ == "__main__":
    main()