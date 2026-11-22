from datetime import datetime, timedelta, timezone

from src.crawlers.jobs import role_family
from src.pipeline.signals import decide
from src.utils.dates import parse_date
from src.utils.seen import SeenStore, item_key

UTC = timezone.utc
NOW = datetime(2026, 11, 22, 12, 0, 0, tzinfo=UTC)


def test_iso_with_offset():
    assert parse_date("2026-11-21T15:03:37-05:00", NOW) == datetime(2026, 11, 21, 20, 3, 37, tzinfo=UTC)


def test_rfc2822():
    assert parse_date("Sat, 21 Nov 2026 21:37:10 +0000", NOW) == datetime(2026, 11, 21, 21, 37, 10, tzinfo=UTC)


def test_epoch_seconds_and_millis():
    assert parse_date(1795222806, NOW) == datetime.fromtimestamp(1795222806, UTC)
    assert parse_date(1786469891368, NOW) == datetime.fromtimestamp(1786469891.368, UTC)


def test_naive_is_utc():
    assert parse_date("2026-11-19T14:58:42", NOW) == datetime(2026, 11, 19, 14, 58, 42, tzinfo=UTC)


def test_relative_dates():
    d = parse_date("2 hours ago", NOW)
    assert abs((NOW - timedelta(hours=2)) - d) < timedelta(seconds=5)
    d = parse_date("3 days ago", NOW)
    assert abs((NOW - timedelta(days=3)) - d) < timedelta(seconds=5)


def test_garbage_and_empty():
    assert parse_date(None, NOW) is None
    assert parse_date("", NOW) is None
    assert parse_date("zzzz qqqq", NOW) is None


def test_item_key_ignores_tracking_and_fragment():
    assert item_key("https://X.com/a/?utm_source=t#top") == item_key("https://x.com/a")


def test_decide_flow(tmp_path):
    seen = SeenStore(tmp_path / "s.sqlite")
    fresh = (NOW - timedelta(hours=3)).isoformat()
    dt, how, why = decide(fresh, NOW, "A", "https://x.com/1", "job", seen, set())
    assert why is None and how == "source_field"
    assert decide(fresh, NOW, "A", "https://x.com/1", "job", seen, set())[2] == "already_seen"
    old = (NOW - timedelta(hours=30)).isoformat()
    assert decide(old, NOW, "A", "https://x.com/2", "job", seen, set())[2] == "stale_or_future"
    assert decide(None, NOW, "B", "https://x.com/3", "job", seen, {"B"})[2] == "baseline_no_date"
    dt, how, why = decide(None, NOW, "C", "https://x.com/4", "job", seen, set())
    assert why is None and how == "first_seen_heuristic" and dt == NOW


def test_role_family():
    assert role_family("Research Scientist, Alignment") == "Research"
    assert role_family("Senior Software Engineer") == "Engineering"
    assert role_family("Product Designer") == "Design"
    assert role_family("Account Executive, Enterprise") == "Sales"
    assert role_family("Data Engineer") == "Data"
    assert role_family("Technical Recruiter") == "People"
    assert role_family("Product Manager") == "Product"
    assert role_family("Wizard of Light") == "Other"