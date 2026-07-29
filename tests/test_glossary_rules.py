from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.config import get_settings
from backend.app.db import initialize_database
from backend.app.gemini_service import AiResult, GlossaryOutput, GlossarySuggestion
from backend.app.main import app
from backend.app.worker import _glossary_refinement_key, run_once


class ControllerGlossaryGemini:
    seen_rules: list[str]

    def generate_glossary(
        self, samples, source_lang, target_lang, glossary_rules=None
    ):
        self.seen_rules = list(glossary_rules or [])
        return AiResult(
            value=GlossaryOutput(
                glossary=[
                    GlossarySuggestion(
                        source_term="Select Button",
                        target_term="ปุ่มซีเล็กต์",
                        note="ปุ่มควบคุม",
                        mode="transliterate",
                    )
                ]
            )
        )

    def refine_glossary(
        self, candidates, source_lang, target_lang, glossary_rules=None
    ):
        self.seen_rules = list(glossary_rules or [])
        return AiResult(
            value=GlossaryOutput(
                glossary=[
                    GlossarySuggestion(
                        source_term="Select Button",
                        target_term="ปุ่ม Select",
                        note="ปุ่มควบคุม",
                        mode="mixed",
                    )
                ]
            )
        )


def _create_controller_job(client: TestClient) -> str:
    response = client.post(
        "/api/jobs/upload",
        files={
            "file": (
                "controls.csv",
                b"id,text,target\n1,Press the Select Button to open the map,\n",
            )
        },
    )
    assert response.status_code == 201
    job = response.json()
    configured = client.put(
        f"/api/jobs/{job['id']}/configuration",
        json={
            "source_column": "text",
            "target_column": "target",
            "source_lang": "English",
            "target_lang": "Thai",
            "encoding": job["encoding"],
            "delimiter": job["delimiter"],
        },
    )
    assert configured.status_code == 200
    return job["id"]


def test_project_glossary_rules_are_editable_and_mark_regeneration_needed():
    fake = ControllerGlossaryGemini()
    with TestClient(app) as client:
        job_id = _create_controller_job(client)
        initial = client.get(f"/api/jobs/{job_id}").json()
        assert initial["glossary_rule_settings"]["rules"] == []

        selected = client.put(
            f"/api/jobs/{job_id}/glossary-rules",
            json={"rules": ["ใช้การสะกดชื่อตัวละครตามภาคก่อน"]},
        )
        assert selected.status_code == 200
        settings = selected.json()
        assert settings["revision"] == 1
        assert settings["rules"] == ["ใช้การสะกดชื่อตัวละครตามภาคก่อน"]

        assert client.post(f"/api/jobs/{job_id}/glossary/generate").status_code == 202
        assert run_once(service=fake)
        assert fake.seen_rules == ["ใช้การสะกดชื่อตัวละครตามภาคก่อน"]

        detail = client.get(f"/api/jobs/{job_id}").json()
        assert not detail["glossary_rule_settings"]["needs_regeneration"]
        entries = client.get(f"/api/jobs/{job_id}/glossary").json()["entries"]
        assert entries[0]["target_term"] == "ปุ่ม Select"
        assert entries[0]["translation_mode"] == "mixed"

        changed = client.put(
            f"/api/jobs/{job_id}/glossary-rules",
            json={"rules": []},
        )
        assert changed.status_code == 200
        assert changed.json()["needs_regeneration"]
        retained = client.get(f"/api/jobs/{job_id}/glossary").json()["entries"]
        assert retained[0]["target_term"] == "ปุ่ม Select"


def test_glossary_cache_key_changes_when_project_rules_change():
    job = {
        "source_lang": "English",
        "target_lang": "Thai",
    }
    candidates = [
        {
            "s": "Select Button",
            "t": "ปุ่ม Select",
            "n": "",
            "m": "mixed",
            "count": 2,
            "x": [],
        }
    ]
    first = _glossary_refinement_key(job, candidates, ["คงชื่อปุ่ม"])
    second = _glossary_refinement_key(job, candidates, ["แปลชื่อปุ่ม"])
    assert first != second


def test_glossary_rules_migration_preserves_existing_translation():
    settings = get_settings()
    settings.database_path.unlink(missing_ok=True)
    connection = sqlite3.connect(settings.database_path)
    try:
        for migration in sorted(Path("backend/app/migrations").glob("00[1-4]_*.sql")):
            connection.executescript(migration.read_text(encoding="utf-8"))
        connection.execute(
            """
            CREATE TABLE schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )
        connection.executemany(
            "INSERT INTO schema_migrations(version, applied_at) VALUES (?, 'now')",
            [
                (migration.name,)
                for migration in sorted(
                    Path("backend/app/migrations").glob("00[1-4]_*.sql")
                )
            ],
        )
        connection.execute(
            """
            INSERT INTO jobs(
                id, filename, stored_path, status, encoding, delimiter,
                headers_json, preview_json, source_column, target_column,
                source_lang, target_lang, total_rows, completed_rows,
                created_at, updated_at
            ) VALUES (
                'legacy', 'legacy.csv', 'legacy.csv', 'completed', 'utf-8', ',',
                '[]', '[]', 'source', 'target', 'English', 'Thai', 1, 1,
                'now', 'now'
            )
            """
        )
        connection.execute(
            """
            INSERT INTO translation_rows(
                id, job_id, row_index, original_data_json, source_text,
                translated_text, status, protected_tokens_json, updated_at
            ) VALUES (
                'row-1', 'legacy', 0, '{}', 'Milk', 'นม', 'done', '[]', 'now'
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
            "SELECT translated_text FROM translation_rows WHERE id = 'row-1'"
        ).fetchone()[0]
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(jobs)").fetchall()
        }
    finally:
        connection.close()
    assert translated == "นม"
    assert "glossary_rules_revision" in columns
    assert "glossary_preset" not in columns
    assert (
        settings.storage_dir / "backups" / "thaiforge-pre-glossary-rules.db"
    ).exists()
