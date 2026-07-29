from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.gemini_service import AiResult, GlossaryOutput, GlossarySuggestion
from backend.app.glossary_context import (
    build_candidate_contexts,
    chunk_candidate_contexts,
)
from backend.app.main import app
from backend.app.worker import run_once


class ContextRefiningGemini:
    extraction_calls = 0
    refinement_calls = 0
    refinement_candidates: list[dict] = []

    def generate_glossary(
        self, samples, source_lang, target_lang, glossary_rules=None
    ):
        self.extraction_calls += 1
        return AiResult(
            value=GlossaryOutput(
                glossary=[
                    GlossarySuggestion(
                        source_term="Milk",
                        target_term="มิลค์",
                        note="ไอเทม",
                    ),
                    GlossarySuggestion(
                        source_term="Karen",
                        target_term="คาเรน",
                        note="ตัวละคร",
                    ),
                    GlossarySuggestion(
                        source_term="Turbojolt XL",
                        target_term="เทอร์โบจอลต์ XL",
                        note="ไม่มีใน corpus",
                    ),
                ]
            )
        )

    def refine_glossary(
        self, candidates, source_lang, target_lang, glossary_rules=None
    ):
        self.refinement_calls += 1
        self.refinement_candidates.extend(candidates)
        refined = []
        for candidate in candidates:
            target = "นม" if candidate["s"] == "Milk" else candidate["t"]
            refined.append(
                GlossarySuggestion(
                    source_term=candidate["s"],
                    target_term=target,
                    note=candidate["n"],
                )
            )
        refined.append(
            GlossarySuggestion(
                source_term="Invented During Refinement",
                target_term="คำที่แต่งเพิ่ม",
                note="ไม่มีใน candidate หรือ corpus",
            )
        )
        return AiResult(value=GlossaryOutput(glossary=refined))


class BrokenRefinementGemini(ContextRefiningGemini):
    def refine_glossary(
        self, candidates, source_lang, target_lang, glossary_rules=None
    ):
        self.refinement_calls += 1
        raise RuntimeError("refinement unavailable")


def create_context_job(client: TestClient) -> str:
    csv_data = (
        "id,text,target\n"
        "1,I drink a cup of milk every morning,\n"
        "2,Cows produce milk every day,\n"
        "3,Use milk to make cheese,\n"
        "4,Bring three containers of Milk to Karen,\n"
    ).encode()
    uploaded = client.post(
        "/api/jobs/upload",
        files={"file": ("context.csv", csv_data)},
    ).json()
    response = client.put(
        f"/api/jobs/{uploaded['id']}/configuration",
        json={
            "source_column": "text",
            "target_column": "target",
            "source_lang": "อังกฤษ",
            "target_lang": "ไทย",
            "encoding": uploaded["encoding"],
            "delimiter": uploaded["delimiter"],
        },
    )
    assert response.status_code == 200
    return uploaded["id"]


def test_context_builder_collects_occurrences_from_the_whole_corpus():
    with TestClient(app) as client:
        job_id = create_context_job(client)
        candidates = build_candidate_contexts(
            job_id,
            [("Milk", "มิลค์", "ไอเทม", "transliterate")],
        )

    assert candidates[0]["count"] == 4
    assert len(candidates[0]["x"]) == 4
    assert any("Cows produce milk" in example for example in candidates[0]["x"])
    assert len(chunk_candidate_contexts(candidates)) == 1


def test_refinement_corrects_milk_and_is_reused_from_cache_across_jobs():
    fake = ContextRefiningGemini()
    with TestClient(app) as client:
        first = create_context_job(client)
        assert client.post(f"/api/jobs/{first}/glossary/generate").status_code == 202
        assert run_once(service=fake)

        first_entries = client.get(f"/api/jobs/{first}/glossary").json()["entries"]
        assert all(
            entry["source_term"] != "Turbojolt XL" for entry in first_entries
        )
        assert all(
            entry["source_term"] != "Invented During Refinement"
            for entry in first_entries
        )
        milk = next(entry for entry in first_entries if entry["source_term"] == "Milk")
        assert milk["target_term"] == "นม"
        sent_milk = next(
            item for item in fake.refinement_candidates if item["s"] == "Milk"
        )
        assert sent_milk["count"] == 4
        assert len(sent_milk["x"]) == 4
        assert all(
            item["s"] != "Turbojolt XL" for item in fake.refinement_candidates
        )
        assert fake.extraction_calls == 1
        assert fake.refinement_calls == 1

        second = create_context_job(client)
        client.post(f"/api/jobs/{second}/glossary/generate")
        assert run_once(service=fake)
        second_entries = client.get(f"/api/jobs/{second}/glossary").json()["entries"]
        assert all(
            entry["source_term"] != "Turbojolt XL" for entry in second_entries
        )
        assert all(
            entry["source_term"] != "Invented During Refinement"
            for entry in second_entries
        )
        second_milk = next(
            entry for entry in second_entries if entry["source_term"] == "Milk"
        )
        assert second_milk["target_term"] == "นม"
        assert fake.extraction_calls == 1
        assert fake.refinement_calls == 1


def test_refinement_failure_keeps_extracted_candidates_for_manual_review():
    fake = BrokenRefinementGemini()
    with TestClient(app) as client:
        job_id = create_context_job(client)
        client.post(f"/api/jobs/{job_id}/glossary/generate")
        assert run_once(service=fake)

        job = client.get(f"/api/jobs/{job_id}").json()
        entries = client.get(f"/api/jobs/{job_id}/glossary").json()["entries"]
        assert all(entry["source_term"] != "Turbojolt XL" for entry in entries)
        milk = next(entry for entry in entries if entry["source_term"] == "Milk")

    assert job["status"] == "awaiting_review"
    assert "ตรวจ Glossary ด้วยบริบทไม่สำเร็จ" in job["last_error"]
    assert milk["target_term"] == "มิลค์"
