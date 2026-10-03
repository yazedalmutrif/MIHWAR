"""Time helpers. Asia/Riyadh is a fixed UTC+3 (no DST), so no tzdata is needed.

The Saudi working week is Sunday to Thursday; Friday and Saturday are the weekend.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

RIYADH = timezone(timedelta(hours=3), name="Asia/Riyadh")
WEEKEND = {4, 5}  # Python weekday(): Mon=0 ... Fri=4, Sat=5, Sun=6
DAY_NAMES_AR = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]


def now() -> datetime:
    return datetime.now(RIYADH)


def now_iso() -> str:
    return now().isoformat(timespec="seconds")


def today() -> date:
    return now().date()


def parse_ts(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo else dt.replace(tzinfo=RIYADH)


def parse_date(value: str) -> date:
    return date.fromisoformat(value[:10])


def is_working_day(d: date) -> bool:
    return d.weekday() not in WEEKEND


def next_working_day(d: date) -> date:
    while not is_working_day(d):
        d += timedelta(days=1)
    return d


def add_working_days(start: date, days: int) -> date:
    """End date of a task that starts on `start` and lasts `days` working days."""
    d = next_working_day(start)
    remaining = max(1, int(days)) - 1
    while remaining > 0:
        d += timedelta(days=1)
        if is_working_day(d):
            remaining -= 1
    return d


def working_days_between(start: date, end: date) -> int:
    """Inclusive count of working days between two dates."""
    if end < start:
        return 0
    n, d = 0, start
    while d <= end:
        if is_working_day(d):
            n += 1
        d += timedelta(days=1)
    return n


def subtract_working_days(end: date, days: int) -> date:
    d = end
    remaining = days
    while remaining > 0:
        d -= timedelta(days=1)
        if is_working_day(d):
            remaining -= 1
    return d


def week_start(d: date) -> date:
    """Sunday that starts the Saudi working week containing `d`."""
    return d - timedelta(days=(d.weekday() + 1) % 7)


MONTHS_AR = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو", "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


def ar_date(value, with_year: bool = True) -> str:
    """'2026-10-04' -> '4 أكتوبر 2026'. ISO dates get visually reordered inside right-to-left text, so
    every human-facing Arabic sentence uses this format instead (JSON fields stay ISO)."""
    if value is None:
        return "—"
    d = parse_date(value) if isinstance(value, str) else value
    return f"{d.day} {MONTHS_AR[d.month - 1]}" + (f" {d.year}" if with_year else "")


def ltr(token: str) -> str:
    """Wrap a code (e.g. MST012-MST-ZZ-00-DR-A-0001) in Unicode left-to-right isolates so it stays intact in Arabic text."""
    return f"⁦{token}⁩"
