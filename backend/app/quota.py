from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from .config import get_settings
from .db import connect, transaction, utc_now


class LocalDailyBudgetExceeded(RuntimeError):
    def __init__(self, resume_at: str) -> None:
        super().__init__("ถึงงบคำขอ Gemini รายวันของ ThaiForge แล้ว")
        self.resume_at = resume_at


def credential_fingerprint(api_key: str) -> str:
    if not api_key:
        return "unconfigured"
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:24]


def _nth_sunday(year: int, month: int, occurrence: int) -> int:
    first = datetime(year, month, 1, tzinfo=timezone.utc)
    first_sunday = 1 + ((6 - first.weekday()) % 7)
    return first_sunday + ((occurrence - 1) * 7)


def _pacific_timezone(now_utc: datetime) -> timezone:
    # US Pacific DST: second Sunday in March 10:00 UTC through
    # first Sunday in November 09:00 UTC.
    year = now_utc.year
    dst_start = datetime(
        year, 3, _nth_sunday(year, 3, 2), 10, tzinfo=timezone.utc
    )
    dst_end = datetime(
        year, 11, _nth_sunday(year, 11, 1), 9, tzinfo=timezone.utc
    )
    offset = -7 if dst_start <= now_utc < dst_end else -8
    return timezone(timedelta(hours=offset))


def quota_window(now: datetime | None = None) -> tuple[str, str]:
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)
    pacific = _pacific_timezone(now_utc)
    current = now_utc.astimezone(pacific)
    quota_day = current.date().isoformat()
    next_day = current.date() + timedelta(days=1)
    reset = datetime.combine(next_day, datetime.min.time(), tzinfo=pacific)
    return quota_day, reset.astimezone(timezone.utc).isoformat()


def reserve_request(api_key: str, model: str) -> int:
    settings = get_settings()
    fingerprint = credential_fingerprint(api_key)
    quota_day, reset_at = quota_window()
    now = utc_now()
    with transaction(immediate=True) as connection:
        row = connection.execute(
            """
            SELECT request_count FROM quota_usage
            WHERE credential_fingerprint = ? AND model = ? AND quota_day = ?
            """,
            (fingerprint, model, quota_day),
        ).fetchone()
        used = int(row["request_count"]) if row else 0
        if used >= settings.gemini_daily_request_budget:
            raise LocalDailyBudgetExceeded(reset_at)
        used += 1
        connection.execute(
            """
            INSERT INTO quota_usage(
                credential_fingerprint, model, quota_day, request_count, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(credential_fingerprint, model, quota_day) DO UPDATE SET
                request_count = excluded.request_count,
                updated_at = excluded.updated_at
            """,
            (fingerprint, model, quota_day, used, now),
        )
    return used


def quota_usage(api_key: str | None = None, model: str | None = None) -> dict:
    settings = get_settings()
    current_key = settings.gemini_api_key if api_key is None else api_key
    current_model = settings.gemini_model if model is None else model
    quota_day, reset_at = quota_window()
    fingerprint = credential_fingerprint(current_key)
    with connect() as connection:
        row = connection.execute(
            """
            SELECT request_count FROM quota_usage
            WHERE credential_fingerprint = ? AND model = ? AND quota_day = ?
            """,
            (fingerprint, current_model, quota_day),
        ).fetchone()
    used = int(row["request_count"]) if row else 0
    return {
        "used": used,
        "budget": settings.gemini_daily_request_budget,
        "warning_at": min(
            settings.gemini_daily_request_warning,
            settings.gemini_daily_request_budget,
        ),
        "reset_at": reset_at,
        "quota_day": quota_day,
    }
