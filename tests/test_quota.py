from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.app.config import get_settings
from backend.app.gemini_service import GeminiDailyQuotaError, GeminiService
from backend.app.quota import (
    LocalDailyBudgetExceeded,
    quota_usage,
    quota_window,
    reserve_request,
)


def test_quota_window_uses_pacific_midnight_with_dst():
    summer_day, summer_reset = quota_window(
        datetime(2026, 7, 28, 12, tzinfo=timezone.utc)
    )
    winter_day, winter_reset = quota_window(
        datetime(2026, 1, 28, 12, tzinfo=timezone.utc)
    )

    assert summer_day == "2026-07-28"
    assert summer_reset == "2026-07-29T07:00:00+00:00"
    assert winter_day == "2026-01-28"
    assert winter_reset == "2026-01-29T08:00:00+00:00"


def test_local_daily_budget_counts_every_reserved_request(monkeypatch):
    monkeypatch.setenv("GEMINI_DAILY_REQUEST_BUDGET", "2")
    monkeypatch.setenv("GEMINI_DAILY_REQUEST_WARNING", "1")
    get_settings.cache_clear()

    assert reserve_request("budget-key", "test-model") == 1
    assert reserve_request("budget-key", "test-model") == 2
    with pytest.raises(LocalDailyBudgetExceeded):
        reserve_request("budget-key", "test-model")

    usage = quota_usage("budget-key", "test-model")
    assert usage["used"] == 2
    assert usage["budget"] == 2
    assert usage["warning_at"] == 1


def test_daily_quota_error_is_not_retried():
    class Models:
        calls = 0

        def generate_content(self, **_kwargs):
            self.calls += 1
            raise RuntimeError(
                "429 RESOURCE_EXHAUSTED free_tier_requests RequestsPerDay"
            )

    class Client:
        models = Models()

    service = GeminiService(
        api_key="daily-key",
        model="test-model",
        client=Client(),
        sleep=lambda _seconds: None,
    )

    with pytest.raises(GeminiDailyQuotaError) as raised:
        service.translate_batch(
            [{"id": "r1", "segments": [{"segment_id": "s0", "source_text": "Hello"}]}],
            "English",
            "Thai",
            [],
            [],
        )

    assert Client.models.calls == 1
    assert raised.value.attempts == 1
