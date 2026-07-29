from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.gemini_service import (
    AiResult,
    GeminiDailyQuotaError,
    GlossaryOutput,
    GlossarySuggestion,
    TranslationItem,
    TranslationOutput,
    TranslationSegment,
)
from backend.app.main import app
from backend.app.worker import run_once


class FakeGemini:
    calls = 0

    def generate_glossary(self, samples, source_lang, target_lang):
        self.calls += 1
        return AiResult(
            value=GlossaryOutput(
                glossary=[
                    GlossarySuggestion(
                        source_term="Potion", target_term="น้ำยา", note="ไอเทมฟื้นฟู"
                    )
                ],
                style_rules=["กระชับแบบข้อความเกม"],
            ),
            input_tokens=100,
            output_tokens=20,
        )

    def translate_batch(
        self, rows, source_lang, target_lang, glossary_entries, style_rules
    ):
        self.calls += 1
        return AiResult(
            value=TranslationOutput(
                translations=[
                    TranslationItem(
                        row_id=row["id"],
                        segments=[
                            TranslationSegment(
                                segment_id=segment["segment_id"],
                                translated_text=f"แปล: {segment['source_text']}",
                            )
                            for segment in row["segments"]
                        ],
                    )
                    for row in rows
                ]
            ),
            input_tokens=50,
            output_tokens=20,
        )

class BrokenTokenGemini(FakeGemini):
    def translate_batch(
        self, rows, source_lang, target_lang, glossary_entries, style_rules
    ):
        self.calls += 1
        return AiResult(
            value=TranslationOutput(
                translations=[
                    TranslationItem(
                        row_id=row["id"],
                        segments=[
                            TranslationSegment(
                                segment_id=segment["segment_id"],
                                translated_text="คำแปล",
                            )
                            for segment in row["segments"]
                        ],
                    )
                    for row in rows
                ]
            )
        )


class FailingGemini(FakeGemini):
    def translate_batch(
        self, rows, source_lang, target_lang, glossary_entries, style_rules
    ):
        self.calls += 1
        raise RuntimeError("content policy")


class QuotaGemini(FakeGemini):
    def translate_batch(
        self, rows, source_lang, target_lang, glossary_entries, style_rules
    ):
        self.calls += 1
        raise GeminiDailyQuotaError(
            "429 free_tier_requests RequestsPerDay",
            attempts=1,
            resume_at="2099-01-01T00:00:00+00:00",
        )


class MissingResultGemini(FakeGemini):
    def translate_batch(
        self, rows, source_lang, target_lang, glossary_entries, style_rules
    ):
        self.calls += 1
        return AiResult(value=TranslationOutput(translations=[]))


def create_configured_job(client: TestClient) -> str:
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("game.csv", b"id,text,target\n1,Use Potion,\n2,Hello {name},\n")},
    )
    assert response.status_code == 201, response.text
    job = response.json()
    configured = client.put(
        f"/api/jobs/{job['id']}/configuration",
        json={
            "source_column": "text",
            "target_column": "target",
            "source_lang": "อังกฤษ",
            "target_lang": "ไทย",
            "encoding": job["encoding"],
            "delimiter": job["delimiter"],
        },
    )
    assert configured.status_code == 200, configured.text
    return job["id"]


def create_large_configured_job(client: TestClient, row_count: int = 120) -> str:
    lines = ["id,text,target"]
    lines.extend(
        f"{index},Character{index} visits Mineral Town,"
        for index in range(row_count)
    )
    response = client.post(
        "/api/jobs/upload",
        files={"file": ("large.csv", ("\n".join(lines) + "\n").encode("utf-8"))},
    )
    assert response.status_code == 201, response.text
    job = response.json()
    configured = client.put(
        f"/api/jobs/{job['id']}/configuration",
        json={
            "source_column": "text",
            "target_column": "target",
            "source_lang": "อังกฤษ",
            "target_lang": "ไทย",
            "encoding": job["encoding"],
            "delimiter": job["delimiter"],
        },
    )
    assert configured.status_code == 200, configured.text
    return job["id"]


def test_complete_workflow_and_local_glossary_scan():
    fake = FakeGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)

        assert client.post(f"/api/jobs/{job_id}/glossary/generate").status_code == 202
        assert run_once(service=fake)
        detail = client.get(f"/api/jobs/{job_id}").json()
        assert detail["status"] == "awaiting_review"
        assert len(detail["style_rules"]) == 6

        glossary = client.get(f"/api/jobs/{job_id}/glossary").json()["entries"]
        assert glossary[0]["source_term"] == "Potion"
        assert client.post(f"/api/jobs/{job_id}/start").status_code == 200
        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=fake)

        status = client.get(f"/api/jobs/{job_id}/status").json()
        assert status["status"] == "completed"
        assert status["counts"]["done"] == 2

        updated = client.patch(
            f"/api/jobs/{job_id}/glossary/{glossary[0]['id']}",
            json={"target_term": "โพชัน"},
        )
        assert updated.status_code == 200
        calls_before_scan = fake.calls
        scan = client.post(f"/api/jobs/{job_id}/retranslation-scans").json()
        assert fake.calls == calls_before_scan
        assert scan["candidate_count"] == 1
        assert scan["items"][0]["row_index"] == 0

        confirmed = client.post(
            f"/api/jobs/{job_id}/retranslation-scans/{scan['id']}/confirm",
            json={"row_ids": [scan["items"][0]["row_id"]]},
        )
        assert confirmed.json()["queued"] == 1
        assert client.get(f"/api/jobs/{job_id}").json()["status"] == "paused"
        assert client.post(f"/api/jobs/{job_id}/resume").status_code == 200
        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=fake)
        assert client.get(f"/api/jobs/{job_id}/status").json()["status"] == "completed"

        exported = client.get(f"/api/jobs/{job_id}/export")
        assert exported.status_code == 200
        assert exported.content.startswith(b"\xef\xbb\xbf")
        assert "แปล: Use Potion" in exported.content.decode("utf-8-sig")


def test_pause_retry_and_single_active_job():
    fake = FakeGemini()
    with TestClient(app) as client:
        first = create_configured_job(client)
        second = create_configured_job(client)
        for job_id in (first, second):
            client.post(f"/api/jobs/{job_id}/glossary/generate")
            run_once(service=fake)

        assert client.post(f"/api/jobs/{first}/start").status_code == 200
        blocked = client.post(f"/api/jobs/{second}/start")
        assert blocked.status_code == 409
        assert blocked.json()["detail"]["active_job_id"] == first
        assert client.post(f"/api/jobs/{first}/pause").status_code == 200
        assert client.post(f"/api/jobs/{second}/start").status_code == 200


def test_tokens_are_rebuilt_locally_without_repair_calls():
    fake = BrokenTokenGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)
        client.post(f"/api/jobs/{job_id}/start")
        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=fake)

        rows = client.get(f"/api/jobs/{job_id}/rows").json()["items"]
        placeholder_row = next(row for row in rows if "{name}" in row["source_text"])
        assert placeholder_row["status"] == "done"
        assert "{name}" in placeholder_row["translated_text"]
        assert fake.calls == 2  # glossary and one translation batch


def test_permanent_failure_is_not_retried_and_does_not_spend_more_quota():
    good = FakeGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=good)
        client.post(f"/api/jobs/{job_id}/start")
        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=FailingGemini())

        failed = client.get(f"/api/jobs/{job_id}/status").json()
        assert failed["status"] == "completed_with_errors"
        assert failed["counts"]["failed"] == 2

        retry = client.post(
            f"/api/jobs/{job_id}/retry-failed",
            json={"resume": True},
        )
        assert retry.json()["queued"] == 0
        assert retry.json()["skipped_permanent"] == 2
        assert retry.json()["status"] == "completed_with_errors"


def test_daily_quota_pauses_and_returns_claimed_rows_to_pending():
    fake = FakeGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)
        client.post(f"/api/jobs/{job_id}/start")

        assert run_once(service=QuotaGemini())
        status = client.get(f"/api/jobs/{job_id}/status").json()
        assert status["status"] == "paused"
        assert status["pause_reason"] == "quota"
        assert status["counts"]["pending"] == 2
        assert status["counts"]["failed"] == 0


def test_missing_segments_get_one_batched_retry_then_fail():
    fake = MissingResultGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)
        client.post(f"/api/jobs/{job_id}/start")

        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=fake)

        status = client.get(f"/api/jobs/{job_id}/status").json()
        assert status["counts"]["failed"] == 2
        assert fake.calls == 3  # glossary plus two batched translation attempts


def test_scan_confirmation_rejects_changed_glossary_revision():
    fake = FakeGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)
        glossary = client.get(f"/api/jobs/{job_id}/glossary").json()["entries"]
        client.post(f"/api/jobs/{job_id}/start")
        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=fake)

        client.patch(
            f"/api/jobs/{job_id}/glossary/{glossary[0]['id']}",
            json={"target_term": "โพชัน"},
        )
        scan = client.post(f"/api/jobs/{job_id}/retranslation-scans").json()
        client.patch(
            f"/api/jobs/{job_id}/glossary/{glossary[0]['id']}",
            json={"rule_note": "ใช้เป็นชื่อไอเทม"},
        )
        rejected = client.post(
            f"/api/jobs/{job_id}/retranslation-scans/{scan['id']}/confirm",
            json={"row_ids": None},
        )
        assert rejected.status_code == 409


def test_spa_route_refresh_returns_frontend():
    with TestClient(app) as client:
        response = client.get("/jobs/example-id")
        assert response.status_code == 200
        assert "ThaiForge V2" in response.text


def test_glossary_generation_covers_multiple_chunks_and_can_regenerate(monkeypatch):
    from backend.app.config import get_settings

    monkeypatch.setenv("GLOSSARY_CHUNK_ROWS", "50")
    monkeypatch.setenv("GLOSSARY_CHUNK_CHARS", "60000")
    get_settings.cache_clear()
    fake = FakeGemini()

    with TestClient(app) as client:
        job_id = create_large_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)

        job = client.get(f"/api/jobs/{job_id}").json()
        assert job["status"] == "awaiting_review"
        assert job["glossary_chunks_total"] == 3
        assert job["glossary_chunks_completed"] == 3
        assert fake.calls == 3

        regenerated = client.post(f"/api/jobs/{job_id}/glossary/generate")
        assert regenerated.status_code == 202
        run_once(service=fake)
        refreshed = client.get(f"/api/jobs/{job_id}").json()
        assert refreshed["status"] == "awaiting_review"
        assert refreshed["glossary_revision"] == 2
        assert fake.calls == 3


def test_glossary_search_filters_and_pagination_are_backward_compatible():
    fake = FakeGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)
        client.post(
            f"/api/jobs/{job_id}/glossary",
            json={
                "source_term": "Sword",
                "target_term": "ดาบ",
                "rule_note": "อาวุธ",
            },
        )

        default_response = client.get(f"/api/jobs/{job_id}/glossary")
        assert default_response.status_code == 200
        assert "entries" in default_response.json()
        assert "style_rules" in default_response.json()
        assert default_response.json()["total"] == 2

        searched = client.get(
            f"/api/jobs/{job_id}/glossary",
            params={"q": "อาวุธ", "origin": "user", "state": "active", "page_size": 1},
        ).json()
        assert searched["total"] == 1
        assert searched["entries"][0]["source_term"] == "Sword"
        assert searched["page_size"] == 1


def test_row_search_matches_source_and_translation_without_changing_status_filter():
    fake = FakeGemini()
    with TestClient(app) as client:
        job_id = create_configured_job(client)

        source_match = client.get(
            f"/api/jobs/{job_id}/rows",
            params={"q": "Potion", "status": "pending"},
        ).json()
        assert source_match["total"] == 1
        assert source_match["items"][0]["source_text"] == "Use Potion"

        no_match = client.get(
            f"/api/jobs/{job_id}/rows",
            params={"q": "Potion", "status": "done"},
        ).json()
        assert no_match["total"] == 0
