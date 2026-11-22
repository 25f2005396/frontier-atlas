import csv
import os
import re
import sys
import time

import gspread
from gspread.exceptions import APIError

from src import config  # noqa: F401  (loads .env)
from src.config import ROOT, OUTPUT_DIR

EXPORT_DIR = OUTPUT_DIR / "export"
TABS = ["Startups", "Products", "Research Papers", "Jobs", "News", "Entity Mapping Log"]
MAX_CHARS_PER_REQUEST = 1_500_000
MAX_ROWS_PER_REQUEST = 500

csv.field_size_limit(10_000_000)


def sheet_id(value: str) -> str:
    m = re.search(r"/d/([A-Za-z0-9_-]+)", value)
    return m.group(1) if m else value.strip()


def cell(v: str):
    """Integers become numbers; everything else stays text (written RAW, so no formulas run)."""
    if re.fullmatch(r"-?[1-9]\d{0,14}|0", v):
        return int(v)
    return v


def read_csv(name: str) -> list[list]:
    path = EXPORT_DIR / f"{name}.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    return [rows[0]] + [[cell(v) for v in r] for r in rows[1:]]


def with_retry(fn, *args, **kwargs):
    for attempt in range(6):
        try:
            return fn(*args, **kwargs)
        except APIError as exc:
            code = getattr(exc.response, "status_code", 0)
            if code in (429, 500, 502, 503) and attempt < 5:
                wait = min(60, 5 * 2 ** attempt)
                print(f"  API {code}, waiting {wait}s")
                time.sleep(wait)
                continue
            raise


def batches(rows):
    batch, size = [], 0
    for r in rows:
        n = sum(len(str(v)) for v in r) + len(r)
        if batch and (size + n > MAX_CHARS_PER_REQUEST or len(batch) >= MAX_ROWS_PER_REQUEST):
            yield batch
            batch, size = [], 0
        batch.append(r)
        size += n
    if batch:
        yield batch


def main():
    cred = os.getenv("GOOGLE_SHEETS_CREDENTIALS", "credentials.json")
    cred_path = (ROOT / cred) if not os.path.isabs(cred) else cred
    raw_id = os.getenv("GOOGLE_SHEET_ID", "")
    if not raw_id:
        sys.exit("GOOGLE_SHEET_ID is not set in .env")

    gc = gspread.service_account(filename=str(cred_path))
    sh = with_retry(gc.open_by_key, sheet_id(raw_id))
    print("Opened:", sh.title)

    for name in TABS:
        rows = read_csv(name)
        n_rows, n_cols = max(len(rows), 2), max(len(rows[0]) if rows else 1, 1)
        try:
            ws = sh.worksheet(name)
            with_retry(ws.clear)
            with_retry(ws.resize, rows=n_rows, cols=n_cols)
        except gspread.WorksheetNotFound:
            ws = with_retry(sh.add_worksheet, title=name, rows=n_rows, cols=n_cols)

        start = 1
        for chunk in batches(rows):
            with_retry(ws.update, values=chunk, range_name=f"A{start}", value_input_option="RAW")
            start += len(chunk)
        if rows:
            with_retry(ws.freeze, rows=1)
        print(f"{name:20} {max(len(rows) - 1, 0):6} data rows")

    # remove the default empty tab if it is still there
    try:
        default = sh.worksheet("Sheet1")
        if len(sh.worksheets()) > 1:
            with_retry(sh.del_worksheet, default)
    except gspread.WorksheetNotFound:
        pass

    # put tabs in the assignment's order
    order = {n: i for i, n in enumerate(TABS)}
    with_retry(sh.reorder_worksheets, sorted(sh.worksheets(), key=lambda w: order.get(w.title, 99)))
    print("Done:", sh.url)


if __name__ == "__main__":
    main()