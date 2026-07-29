from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.batching import take_adaptive_batch
from backend.app.gemini_service import (
    CompactGlossaryOutput,
    CompactGlossarySuggestion,
    CompactTranslationItem,
    CompactTranslationOutput,
    GeminiService,
)
from backend.app.main import app
from backend.app.worker import run_once

from test_workflow import FakeGemini, create_configured_job


def test_adaptive_batch_uses_aggressive_row_cap():
    rows = [
        {"id": str(index), "source_text": f"Short game text {index}"}
        for index in range(1_000)
    ]
    chosen, estimate = take_adaptive_batch(rows)
    assert len(chosen) == 500
    assert estimate.input_tokens <= 120_000
    assert estimate.output_tokens <= 45_000


def test_gemini_service_uses_compact_ids_and_maps_segments_back():
    class Usage:
        prompt_token_count = 30
        candidates_token_count = 12
        thoughts_token_count = 0
        cached_content_token_count = 5

    class Response:
        parsed = CompactTranslationOutput(
            r=[CompactTranslationItem(i=0, t=["สวัสดี"])]
        )
        text = ""
        usage_metadata = Usage()
        candidates = []

    class Models:
        contents = ""

        def generate_content(self, **kwargs):
            self.contents = kwargs["contents"]
            return Response()

    class Client:
        models = Models()

    service = GeminiService(api_key="compact-key", client=Client())
    result = service.translate_batch(
        [
            {
                "id": "very-long-row-uuid-that-must-not-enter-the-prompt",
                "segments": [{"segment_id": "s0", "source_text": "Hello"}],
            }
        ],
        "English",
        "Thai",
        [],
        [],
    )

    translated = result.value.translations[0]
    assert translated.row_id == "very-long-row-uuid-that-must-not-enter-the-prompt"
    assert translated.segments[0].segment_id == "s0"
    assert translated.segments[0].translated_text == "สวัสดี"
    assert "very-long-row-uuid" not in Client.models.contents
    assert result.cached_tokens == 5


def test_glossary_refinement_sends_corpus_context_and_rejects_new_terms():
    class Response:
        parsed = CompactGlossaryOutput(
            g=[
                CompactGlossarySuggestion(
                    s="milk", t="นม", n="วัตถุดิบ", m="translate"
                ),
                CompactGlossarySuggestion(
                    s="Invented", t="คำที่แต่งเพิ่ม", n="", m="translate"
                ),
            ]
        )
        text = ""
        usage_metadata = None
        candidates = []

    class Models:
        contents = ""
        config = None

        def generate_content(self, **kwargs):
            self.contents = kwargs["contents"]
            self.config = kwargs["config"]
            return Response()

    class Client:
        models = Models()

    service = GeminiService(api_key="context-key", client=Client())
    result = service.refine_glossary(
        [
            {
                "s": "Milk",
                "t": "มิลค์",
                "n": "ไอเทม",
                "m": "transliterate",
                "count": 4,
                "x": ["Cows produce milk", "Drink a cup of milk"],
            }
        ],
        "English",
        "Thai",
        ["ชื่อปุ่มควบคุมให้คงอักษรละติน"],
    )

    assert "Cows produce milk" in Client.models.contents
    assert "ชื่อปุ่มควบคุมให้คงอักษรละติน" in Client.models.contents
    assert "Select Button" in Client.models.contents
    assert "Turbojolt XL" in Client.models.contents
    assert "เทอร์โบจอลต์ XL" in Client.models.contents
    assert '"m":"mixed"' in Client.models.contents
    assert "ตัวพิมพ์ใหญ่" in Client.models.contents
    assert Client.models.config.thinking_config.thinking_level.value == "LOW"
    assert len(result.value.glossary) == 1
    assert result.value.glossary[0].source_term == "Milk"
    assert result.value.glossary[0].target_term == "นม"
    assert result.value.glossary[0].mode == "translate"


def test_glossary_keep_mode_forces_exact_source_text():
    class Response:
        parsed = CompactGlossaryOutput(
            g=[
                CompactGlossarySuggestion(
                    s="XL", t="เอ็กซ์แอล", n="ขนาด", m="keep"
                )
            ]
        )
        text = ""
        usage_metadata = None
        candidates = []

    class Models:
        def generate_content(self, **_kwargs):
            return Response()

    class Client:
        models = Models()

    service = GeminiService(api_key="keep-key", client=Client())
    result = service.refine_glossary(
        [{"s": "XL", "t": "เอ็กซ์แอล", "n": "", "m": "transliterate", "count": 1, "x": ["Turbojolt XL"]}],
        "English",
        "Thai",
    )
    assert result.value.glossary[0].target_term == "XL"
    assert result.value.glossary[0].mode == "keep"


def test_duplicate_rows_are_translated_once_and_fanned_out():
    class CountingGemini(FakeGemini):
        translated_api_rows = 0

        def translate_batch(self, rows, source_lang, target_lang, glossary_entries, style_rules):
            self.translated_api_rows += len(rows)
            return super().translate_batch(
                rows, source_lang, target_lang, glossary_entries, style_rules
            )

    fake = CountingGemini()
    with TestClient(app) as client:
        response = client.post(
            "/api/jobs/upload",
            files={
                "file": (
                    "duplicates.csv",
                    b"id,text,target\n1,Use Potion,\n2,Use Potion,\n3,Use Potion,\n",
                )
            },
        )
        job = response.json()
        job_id = job["id"]
        client.put(
            f"/api/jobs/{job_id}/configuration",
            json={
                "source_column": "text",
                "target_column": "target",
                "source_lang": "อังกฤษ",
                "target_lang": "ไทย",
                "encoding": job["encoding"],
                "delimiter": job["delimiter"],
            },
        )
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        run_once(service=fake)
        client.post(f"/api/jobs/{job_id}/start")
        while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
            run_once(service=fake)

        status = client.get(f"/api/jobs/{job_id}/status").json()
        assert status["counts"]["done"] == 3
        assert fake.translated_api_rows == 1
        assert status["quota_efficiency"]["deduplicated_rows"] == 2


def test_exact_semantic_cache_is_reused_across_jobs():
    fake = FakeGemini()
    with TestClient(app) as client:
        first = create_configured_job(client)
        client.post(f"/api/jobs/{first}/glossary/generate")
        run_once(service=fake)
        client.post(f"/api/jobs/{first}/start")
        while client.get(f"/api/jobs/{first}/status").json()["status"] == "running":
            run_once(service=fake)
        calls_after_first = fake.calls

        second = create_configured_job(client)
        client.post(f"/api/jobs/{second}/glossary/generate")
        run_once(service=fake)
        client.post(f"/api/jobs/{second}/start")
        while client.get(f"/api/jobs/{second}/status").json()["status"] == "running":
            run_once(service=fake)

        status = client.get(f"/api/jobs/{second}/status").json()
        assert status["counts"]["done"] == 2
        assert fake.calls == calls_after_first
        assert status["quota_efficiency"]["requests"] == 0
