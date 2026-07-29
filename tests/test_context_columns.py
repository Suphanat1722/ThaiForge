from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import initialize_database
from backend.app.gemini_service import (
    AiResult,
    GlossaryOutput,
    GlossarySuggestion,
    TranslationItem,
    TranslationOutput,
    TranslationSegment,
)
from backend.app.glossary_context import build_candidate_contexts
from backend.app.main import app
from backend.app.repository import translation_fingerprint
from backend.app.row_context import row_context
from backend.app.worker import _glossary_refinement_key, run_once


class ContextCapturingFake:
    def __init__(self) -> None:
        self.translation_rows: list[dict] = []
        self.refinement_candidates: list[dict] = []

    def generate_glossary(
        self, samples, source_lang, target_lang, glossary_rules=None
    ):
        return AiResult(
            value=GlossaryOutput(
                glossary=[
                    GlossarySuggestion(
                        source_term="love",
                        target_term="รัก",
                        note="คำกริยา",
                        mode="translate",
                    )
                ]
            )
        )

    def refine_glossary(
        self, candidates, source_lang, target_lang, glossary_rules=None
    ):
        self.refinement_candidates.extend(candidates)
        return AiResult(
            value=GlossaryOutput(
                glossary=[
                    GlossarySuggestion(
                        source_term=item["s"],
                        target_term=item["t"],
                        note=item["n"],
                        mode=item["m"],
                    )
                    for item in candidates
                ]
            )
        )

    def translate_batch(
        self, rows, source_lang, target_lang, glossary_entries, style_rules
    ):
        self.translation_rows.extend(rows)
        return AiResult(
            value=TranslationOutput(
                translations=[
                    TranslationItem(
                        row_id=row["id"],
                        segments=[
                            TranslationSegment(
                                segment_id=segment["segment_id"],
                                translated_text="คำแปลเท่านั้น",
                            )
                            for segment in row["segments"]
                        ],
                    )
                    for row in rows
                ]
            )
        )


def test_row_context_supports_thai_english_numbers_and_omits_blanks():
    assert row_context(
        {
            "speaker": " Karen ",
            "scene": "งานหัวใจ",
            "event_id": 42,
            "portrait_id": "",
            "note": None,
        },
        ["speaker", "scene", "event_id", "portrait_id", "note"],
    ) == {
        "speaker": "Karen",
        "scene": "งานหัวใจ",
        "event_id": "42",
    }


def _create_job(
    client: TestClient, context_columns: list[str] | None = None
) -> str:
    csv_data = (
        "id,text,target,character,scene,note\n"
        "1,I love you.,,Karen,Heart Event,สำคัญ\n"
        "2,I love you.,,,,42\n"
    ).encode("utf-8")
    uploaded = client.post(
        "/api/jobs/upload",
        files={"file": ("dialogue.csv", csv_data)},
    ).json()
    response = client.put(
        f"/api/jobs/{uploaded['id']}/configuration",
        json={
            "source_column": "text",
            "target_column": "target",
            "context_columns": context_columns or [],
            "source_lang": "อังกฤษ",
            "target_lang": "ไทย",
            "encoding": uploaded["encoding"],
            "delimiter": uploaded["delimiter"],
        },
    )
    assert response.status_code == 200, response.text
    return uploaded["id"]


def _finish_job(client: TestClient, job_id: str, fake: ContextCapturingFake) -> None:
    assert client.post(f"/api/jobs/{job_id}/glossary/generate").status_code == 202
    assert run_once(service=fake)
    assert client.post(f"/api/jobs/{job_id}/start").status_code == 200
    while client.get(f"/api/jobs/{job_id}/status").json()["status"] == "running":
        run_once(service=fake)


def test_no_context_keeps_payload_compact_and_fingerprint_backward_compatible():
    job = {
        "source_lang": "English",
        "target_lang": "Thai",
        "context_columns": [],
    }
    assert translation_fingerprint(job, "Hello", [], []) == translation_fingerprint(
        job, "Hello", [], [], {}
    )

    fake = ContextCapturingFake()
    with TestClient(app) as client:
        job_id = _create_job(client)
        _finish_job(client, job_id, fake)
        detail = client.get(f"/api/jobs/{job_id}").json()
    assert detail["context_columns"] == []
    assert all("context" not in row for row in fake.translation_rows)


def test_selected_context_is_row_specific_and_empty_context_is_omitted():
    fake = ContextCapturingFake()
    with TestClient(app) as client:
        job_id = _create_job(client, ["character", "scene"])
        _finish_job(client, job_id, fake)
        rows = client.get(f"/api/jobs/{job_id}/rows").json()["items"]

    sent = sorted(fake.translation_rows, key=lambda row: row["id"])
    assert len(sent) == 2
    assert [row.get("context") for row in sent].count(
        {"character": "Karen", "scene": "Heart Event"}
    ) == 1
    assert sum("context" not in row for row in sent) == 1
    assert any(
        row["context"] == {"character": "Karen", "scene": "Heart Event"}
        for row in rows
    )
    assert all(
        "Karen" not in (row["translated_text"] or "")
        and "Heart Event" not in (row["translated_text"] or "")
        for row in rows
    )


def test_context_mapping_and_values_change_translation_and_glossary_cache_keys():
    base = {"source_lang": "English", "target_lang": "Thai"}
    character_job = {**base, "context_columns": ["character"]}
    scene_job = {**base, "context_columns": ["scene"]}
    first = translation_fingerprint(
        character_job, "I love you.", [], [], {"character": "Karen"}
    )
    second = translation_fingerprint(
        scene_job, "I love you.", [], [], {"scene": "Karen"}
    )
    assert first != second

    candidates = [
        {
            "s": "love",
            "t": "รัก",
            "n": "",
            "m": "translate",
            "count": 1,
            "x": [
                {
                    "text": "I love you.",
                    "context": {"character": "Karen"},
                }
            ],
        }
    ]
    assert _glossary_refinement_key(character_job, candidates) != (
        _glossary_refinement_key(scene_job, candidates)
    )


def test_glossary_refinement_examples_include_selected_context():
    with TestClient(app) as client:
        job_id = _create_job(client, ["character", "scene"])
        candidates = build_candidate_contexts(
            job_id, [("love", "รัก", "คำกริยา", "translate")]
        )
    assert candidates[0]["x"][0] == {
        "text": "I love you.",
        "context": {"character": "Karen", "scene": "Heart Event"},
    }
    assert candidates[0]["x"][1] == "I love you."


def test_context_migration_preserves_existing_translation_and_creates_backup():
    settings = get_settings()
    settings.database_path.unlink(missing_ok=True)
    backup = settings.storage_dir / "backups" / "thaiforge-pre-context-columns.db"
    backup.unlink(missing_ok=True)
    connection = sqlite3.connect(settings.database_path)
    migrations = sorted(Path("backend/app/migrations").glob("00[1-6]_*.sql"))
    try:
        for migration in migrations:
            connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            "CREATE TABLE schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
        )
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')",
            [(migration.name,) for migration in migrations],
        )
        connection.execute(
            """
            INSERT INTO jobs(
                id, filename, stored_path, status, encoding, delimiter,
                headers_json, preview_json, source_column, target_column,
                source_lang, target_lang, total_rows, completed_rows,
                created_at, updated_at
            ) VALUES (
                'legacy-context', 'legacy.csv', 'legacy.csv', 'completed',
                'utf-8', ',', '[]', '[]', 'source', 'target',
                'English', 'Thai', 1, 1, 'now', 'now'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO translation_rows(
                id, job_id, row_index, original_data_json, source_text,
                translated_text, status, protected_tokens_json, updated_at
            ) VALUES (
                'legacy-row', 'legacy-context', 0, '{"source":"Milk","id":"1"}',
                'Milk', 'นม', 'done', '[]', 'now'
            )
            """
        )
        connection.commit()
    finally:
        connection.close()

    initialize_database()
    connection = sqlite3.connect(settings.database_path)
    try:
        translated = connection.execute(
            "SELECT translated_text FROM translation_rows WHERE id = 'legacy-row'"
        ).fetchone()[0]
        context_columns_json = connection.execute(
            "SELECT context_columns_json FROM jobs WHERE id = 'legacy-context'"
        ).fetchone()[0]
        original_data_json = connection.execute(
            "SELECT original_data_json FROM translation_rows WHERE id = 'legacy-row'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert translated == "นม"
    assert context_columns_json == "[]"
    assert '"id":"1"' in original_data_json
    assert backup.exists()
