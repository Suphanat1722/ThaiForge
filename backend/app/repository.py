from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from .config import get_settings
from .csv_service import iter_csv_rows
from .db import connect, transaction, utc_now
from .glossary_rules import clean_glossary_rules
from .row_context import decode_context_columns, row_context
from .tokens import extract_protected_tokens


JOB_STATUSES = {
    "uploaded",
    "configured",
    "generating_glossary",
    "awaiting_review",
    "running",
    "paused",
    "completed",
    "completed_with_errors",
    "failed",
}


def new_id() -> str:
    return str(uuid.uuid4())


def _decode_job(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    job = dict(row)
    job["headers"] = json.loads(job.pop("headers_json"))
    job["preview"] = json.loads(job.pop("preview_json"))
    job["context_columns"] = decode_context_columns(
        job.pop("context_columns_json", "[]")
    )
    return job


def get_job(job_id: str, connection: sqlite3.Connection | None = None) -> dict | None:
    owns = connection is None
    connection = connection or connect()
    try:
        return _decode_job(connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone())
    finally:
        if owns:
            connection.close()


def list_jobs() -> list[dict]:
    with connect() as connection:
        return [
            _decode_job(row)
            for row in connection.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC"
            ).fetchall()
        ]


def create_uploaded_job(
    filename: str,
    stored_path: Path,
    inspection: dict,
) -> dict:
    job_id = stored_path.parent.name
    now = utc_now()
    with transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO jobs(
                id, filename, stored_path, status, encoding, delimiter,
                headers_json, preview_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'uploaded', ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                filename,
                str(stored_path),
                inspection["encoding"],
                inspection["delimiter"],
                json.dumps(inspection["headers"], ensure_ascii=False),
                json.dumps(inspection["preview"], ensure_ascii=False),
                now,
                now,
            ),
        )
    return get_job(job_id)  # type: ignore[return-value]


def configure_job(
    job_id: str,
    source_column: str,
    target_column: str,
    source_lang: str,
    target_lang: str,
    encoding: str,
    delimiter: str,
    headers: list[str],
    preview: list[dict],
    context_columns: list[str] | None = None,
) -> dict:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if job["status"] not in {"uploaded", "configured"}:
        raise ValueError("งานนี้ไม่สามารถเปลี่ยน mapping ได้แล้ว")
    if source_column not in headers:
        raise ValueError("ไม่พบ Source column")
    context_columns = list(dict.fromkeys(context_columns or []))
    invalid_context = [
        column
        for column in context_columns
        if column not in headers or column in {source_column, target_column}
    ]
    if invalid_context:
        raise ValueError(
            "Context Columns ต้องเป็นคอลัมน์ที่มีอยู่และห้ามซ้ำกับ Source/Target"
        )
    export_headers = list(headers)
    if target_column not in export_headers:
        export_headers.append(target_column)

    now = utc_now()
    with transaction(immediate=True) as connection:
        current = get_job(job_id, connection)
        if not current or current["status"] not in {"uploaded", "configured"}:
            raise ValueError("สถานะงานเปลี่ยนไประหว่างตั้งค่า")
        connection.execute("DELETE FROM translation_rows WHERE job_id = ?", (job_id,))

        total_rows = 0
        completed = 0
        batch: list[tuple] = []
        for row_index, original in iter_csv_rows(
            Path(job["stored_path"]), encoding, delimiter
        ):
            source = str(original.get(source_column, ""))
            target = str(original.get(target_column, ""))
            status = "skipped" if not source.strip() else "pending"
            if status == "skipped":
                completed += 1
            total_rows += 1
            batch.append(
                (
                    new_id(),
                    job_id,
                    row_index,
                    json.dumps(original, ensure_ascii=False),
                    source,
                    target,
                    status,
                    json.dumps(extract_protected_tokens(source), ensure_ascii=False),
                    now,
                )
            )
            if len(batch) >= 1000:
                connection.executemany(
                    """
                    INSERT INTO translation_rows(
                        id, job_id, row_index, original_data_json, source_text,
                        original_target, status, protected_tokens_json, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                batch.clear()
        if batch:
            connection.executemany(
                """
                INSERT INTO translation_rows(
                    id, job_id, row_index, original_data_json, source_text,
                    original_target, status, protected_tokens_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )

        connection.execute(
            """
            UPDATE jobs SET
                status = 'configured', encoding = ?, delimiter = ?,
                headers_json = ?, preview_json = ?, source_column = ?,
                target_column = ?, source_lang = ?, target_lang = ?,
                context_columns_json = ?,
                total_rows = ?, completed_rows = ?, last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (
                encoding,
                delimiter,
                json.dumps(export_headers, ensure_ascii=False),
                json.dumps(preview, ensure_ascii=False),
                source_column,
                target_column,
                source_lang,
                target_lang,
                json.dumps(context_columns, ensure_ascii=False),
                total_rows,
                completed,
                now,
                job_id,
            ),
        )
    return get_job(job_id)  # type: ignore[return-value]


def active_job(excluding: str | None = None) -> dict | None:
    with connect() as connection:
        if excluding:
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'running' AND id != ? LIMIT 1",
                (excluding,),
            ).fetchone()
        else:
            row = connection.execute(
                "SELECT * FROM jobs WHERE status = 'running' LIMIT 1"
            ).fetchone()
        return _decode_job(row)


def job_counts(job_id: str) -> dict[str, int]:
    with connect() as connection:
        counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM translation_rows WHERE job_id = ? GROUP BY status
                """,
                (job_id,),
            ).fetchall()
        }
        retranslation = {
            row["status"]: row["count"]
            for row in connection.execute(
                """
                SELECT status, COUNT(*) AS count
                FROM retranslation_requests WHERE job_id = ? GROUP BY status
                """,
                (job_id,),
            ).fetchall()
        }
        retryable_failed = connection.execute(
            """
            SELECT COUNT(*) AS count FROM translation_rows
            WHERE job_id = ? AND status = 'failed' AND retryable = 1
            """,
            (job_id,),
        ).fetchone()["count"]
        retranslation_retryable_failed = connection.execute(
            """
            SELECT COUNT(*) AS count FROM retranslation_requests
            WHERE job_id = ? AND status = 'failed' AND retryable = 1
            """,
            (job_id,),
        ).fetchone()["count"]
    return {
        "pending": counts.get("pending", 0),
        "in_progress": counts.get("in_progress", 0),
        "done": counts.get("done", 0),
        "failed": counts.get("failed", 0),
        "skipped": counts.get("skipped", 0),
        "retranslation_pending": retranslation.get("pending", 0),
        "retranslation_in_progress": retranslation.get("in_progress", 0),
        "retranslation_failed": retranslation.get("failed", 0),
        "retryable_failed": retryable_failed,
        "retranslation_retryable_failed": retranslation_retryable_failed,
    }


def paginate_rows(
    job_id: str,
    page: int,
    page_size: int,
    status: str | None = None,
    query: str | None = None,
) -> dict:
    offset = (page - 1) * page_size
    where = "job_id = ?"
    params: list[object] = [job_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    if query and query.strip():
        where += (
            " AND (source_text LIKE ? ESCAPE '\\'"
            " OR COALESCE(translated_text, '') LIKE ? ESCAPE '\\'"
            " OR COALESCE(original_target, '') LIKE ? ESCAPE '\\')"
        )
        escaped = (
            query.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        params.extend([pattern, pattern, pattern])
    with connect() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM translation_rows WHERE {where}", params
        ).fetchone()["count"]
        items = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT id, row_index, source_text, original_target, translated_text,
                       status, total_attempts, last_error, failure_class,
                       retryable, next_attempt_at, updated_at, original_data_json
                FROM translation_rows WHERE {where}
                ORDER BY row_index LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        ]
        job = get_job(job_id, connection)
        context_columns = job["context_columns"] if job else []
        for item in items:
            item["context"] = row_context(
                item.pop("original_data_json", None), context_columns
            )
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_glossary(job_id: str, include_deleted: bool = False) -> list[dict]:
    where = "job_id = ?" if include_deleted else "job_id = ? AND is_deleted = 0"
    with connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                f"SELECT * FROM glossary_entries WHERE {where} ORDER BY source_term COLLATE NOCASE",
                (job_id,),
            ).fetchall()
        ]


def paginate_glossary(
    job_id: str,
    page: int,
    page_size: int,
    query: str | None = None,
    state: str | None = None,
    origin: str | None = None,
) -> dict:
    offset = (page - 1) * page_size
    where = "job_id = ? AND is_deleted = 0"
    params: list[object] = [job_id]
    if query and query.strip():
        where += (
            " AND (source_term LIKE ? ESCAPE '\\'"
            " OR target_term LIKE ? ESCAPE '\\'"
            " OR rule_note LIKE ? ESCAPE '\\')"
        )
        escaped = (
            query.strip()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        pattern = f"%{escaped}%"
        params.extend([pattern, pattern, pattern])
    if state == "active":
        where += " AND is_active = 1"
    elif state == "inactive":
        where += " AND is_active = 0"
    if origin in {"ai", "user"}:
        where += " AND created_by = ?"
        params.append(origin)

    with connect() as connection:
        total = connection.execute(
            f"SELECT COUNT(*) AS count FROM glossary_entries WHERE {where}", params
        ).fetchone()["count"]
        items = [
            dict(row)
            for row in connection.execute(
                f"""
                SELECT * FROM glossary_entries
                WHERE {where}
                ORDER BY source_term COLLATE NOCASE
                LIMIT ? OFFSET ?
                """,
                [*params, page_size, offset],
            ).fetchall()
        ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def list_style_rules(job_id: str) -> list[dict]:
    with connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM style_rules
                WHERE job_id = ? AND is_active = 1
                ORDER BY created_at, id
                """,
                (job_id,),
            ).fetchall()
        ]


def list_glossary_rules(job_id: str) -> list[dict]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT * FROM glossary_rules
            WHERE job_id = ? AND is_active = 1
            ORDER BY created_at, id
            """,
            (job_id,),
        ).fetchall()
        if rows:
            return [dict(row) for row in rows]
        job = get_job(job_id, connection)
        if not job:
            raise KeyError(job_id)
        return []


def glossary_rule_settings(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    return {
        "rules": [rule["rule_text"] for rule in list_glossary_rules(job_id)],
        "revision": job.get("glossary_rules_revision", 0),
        "applied_revision": job.get("glossary_rules_applied_revision", 0),
        "needs_regeneration": bool(
            job["glossary_revision"]
            and job.get("glossary_rules_revision", 0)
            != job.get("glossary_rules_applied_revision", 0)
        ),
    }


def replace_glossary_rules(job_id: str, rules: list[str]) -> dict:
    clean_rules = clean_glossary_rules(rules)
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        if not job:
            raise KeyError(job_id)
        revision = job.get("glossary_rules_revision", 0) + 1
        now = utc_now()
        connection.execute("DELETE FROM glossary_rules WHERE job_id = ?", (job_id,))
        connection.executemany(
            """
            INSERT INTO glossary_rules(
                id, job_id, rule_text, is_active, revision, created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            [(new_id(), job_id, rule, revision, now, now) for rule in clean_rules],
        )
        connection.execute(
            """
            UPDATE jobs SET glossary_rules_revision = ?, updated_at = ?
            WHERE id = ?
            """,
            (revision, now, job_id),
        )
    return glossary_rule_settings(job_id)


def _record_glossary_revision(connection: sqlite3.Connection, entry: dict, job_revision: int) -> None:
    connection.execute(
        """
        INSERT INTO glossary_entry_revisions(
            id, job_id, entry_id, job_revision, source_term, target_term,
            rule_note, is_active, is_deleted, changed_at, translation_mode
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_id(),
            entry["job_id"],
            entry["id"],
            job_revision,
            entry["source_term"],
            entry["target_term"],
            entry.get("rule_note", ""),
            int(entry.get("is_active", 1)),
            int(entry.get("is_deleted", 0)),
            utc_now(),
            entry.get("translation_mode", "mixed"),
        ),
    )


def create_glossary_entry(
    job_id: str,
    source_term: str,
    target_term: str,
    rule_note: str = "",
    created_by: str = "user",
    translation_mode: str = "mixed",
) -> dict:
    now = utc_now()
    entry_id = new_id()
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        if not job:
            raise KeyError(job_id)
        revision = job["glossary_revision"] + 1
        connection.execute(
            """
            INSERT INTO glossary_entries(
                id, job_id, source_term, target_term, rule_note, is_active,
                is_deleted, created_by, revision, created_at, updated_at,
                translation_mode
            ) VALUES (?, ?, ?, ?, ?, 1, 0, ?, ?, ?, ?, ?)
            """,
            (
                entry_id,
                job_id,
                source_term.strip(),
                target_term.strip(),
                rule_note.strip(),
                created_by,
                revision,
                now,
                now,
                translation_mode,
            ),
        )
        entry = dict(
            connection.execute(
                "SELECT * FROM glossary_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        )
        _record_glossary_revision(connection, entry, revision)
        connection.execute(
            "UPDATE jobs SET glossary_revision = ?, updated_at = ? WHERE id = ?",
            (revision, now, job_id),
        )
    return entry


def update_glossary_entry(job_id: str, entry_id: str, updates: dict) -> dict:
    allowed = {
        "source_term",
        "target_term",
        "rule_note",
        "is_active",
        "translation_mode",
    }
    changes = {key: value for key, value in updates.items() if key in allowed}
    if not changes:
        raise ValueError("ไม่มีข้อมูลที่ต้องแก้ไข")
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        row = connection.execute(
            "SELECT * FROM glossary_entries WHERE id = ? AND job_id = ? AND is_deleted = 0",
            (entry_id, job_id),
        ).fetchone()
        if not job or not row:
            raise KeyError(entry_id)
        entry = dict(row)
        for key, value in changes.items():
            entry[key] = int(value) if key == "is_active" else str(value).strip()
        revision = job["glossary_revision"] + 1
        now = utc_now()
        connection.execute(
            """
            UPDATE glossary_entries SET source_term = ?, target_term = ?, rule_note = ?,
                is_active = ?, revision = ?, updated_at = ?, translation_mode = ?
            WHERE id = ?
            """,
            (
                entry["source_term"],
                entry["target_term"],
                entry["rule_note"],
                entry["is_active"],
                revision,
                now,
                entry["translation_mode"],
                entry_id,
            ),
        )
        entry.update(revision=revision, updated_at=now)
        _record_glossary_revision(connection, entry, revision)
        connection.execute(
            "UPDATE jobs SET glossary_revision = ?, updated_at = ? WHERE id = ?",
            (revision, now, job_id),
        )
    return entry


def delete_glossary_entry(job_id: str, entry_id: str) -> None:
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        row = connection.execute(
            "SELECT * FROM glossary_entries WHERE id = ? AND job_id = ? AND is_deleted = 0",
            (entry_id, job_id),
        ).fetchone()
        if not job or not row:
            raise KeyError(entry_id)
        revision = job["glossary_revision"] + 1
        now = utc_now()
        connection.execute(
            """
            UPDATE glossary_entries SET is_active = 0, is_deleted = 1,
                revision = ?, updated_at = ? WHERE id = ?
            """,
            (revision, now, entry_id),
        )
        entry = dict(row)
        entry.update(is_active=0, is_deleted=1, revision=revision)
        _record_glossary_revision(connection, entry, revision)
        connection.execute(
            "UPDATE jobs SET glossary_revision = ?, updated_at = ? WHERE id = ?",
            (revision, now, job_id),
        )


def replace_style_rules(job_id: str, rules: list[str]) -> list[dict]:
    clean_rules = [rule.strip() for rule in rules if rule.strip()]
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        if not job:
            raise KeyError(job_id)
        revision = job["style_revision"] + 1
        now = utc_now()
        connection.execute("DELETE FROM style_rules WHERE job_id = ?", (job_id,))
        connection.executemany(
            """
            INSERT INTO style_rules(
                id, job_id, rule_text, is_active, revision, created_at, updated_at
            ) VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            [(new_id(), job_id, rule, revision, now, now) for rule in clean_rules],
        )
        connection.execute(
            "UPDATE jobs SET style_revision = ?, updated_at = ? WHERE id = ?",
            (revision, now, job_id),
        )
    return list_style_rules(job_id)


def translation_fingerprint(
    job: dict,
    source_text: str,
    entries: Iterable[dict],
    style_rules: Iterable[dict],
    context: dict[str, str] | None = None,
) -> str:
    payload = {
        "policy": "compact-v2",
        "source": source_text,
        "source_lang": job["source_lang"],
        "target_lang": job["target_lang"],
        "entries": sorted(
            [
                {
                    "source": entry["source_term"],
                    "target": entry["target_term"],
                    "note": entry["rule_note"],
                }
                for entry in entries
            ],
            key=lambda item: (
                item["source"].casefold(),
                item["target"].casefold(),
                item["note"].casefold(),
            ),
        ),
        "style": sorted(rule["rule_text"] for rule in style_rules),
    }
    if context:
        payload["context"] = context
    context_columns = job.get("context_columns", [])
    if context_columns:
        payload["context_columns"] = list(context_columns)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def legacy_translation_fingerprint(
    job: dict,
    source_text: str,
    entries: Iterable[dict],
    style_rules: Iterable[dict],
) -> str:
    payload = {
        "source": source_text,
        "source_lang": job["source_lang"],
        "target_lang": job["target_lang"],
        "entries": [
            {
                "id": entry["id"],
                "revision": entry["revision"],
                "source": entry["source_term"],
                "target": entry["target_term"],
                "note": entry["rule_note"],
            }
            for entry in entries
        ],
        "style": [
            {"revision": rule["revision"], "text": rule["rule_text"]}
            for rule in style_rules
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def quota_efficiency(job_id: str) -> dict:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT
                COALESCE(SUM(request_count), 0) AS requests,
                COALESCE(SUM(original_row_count), 0) AS original_rows,
                COALESCE(SUM(unique_row_count), 0) AS unique_rows,
                COALESCE(SUM(cache_hit_count), 0) AS cache_hits,
                COALESCE(SUM(planned_input_tokens), 0) AS planned_input_tokens,
                COALESCE(SUM(planned_output_tokens), 0) AS planned_output_tokens
            FROM ai_attempts
            WHERE job_id = ? AND kind IN ('translation', 'retranslation')
            """,
            (job_id,),
        ).fetchone()
    requests = int(row["requests"])
    original_rows = int(row["original_rows"])
    unique_rows = int(row["unique_rows"])
    cache_hits = int(row["cache_hits"])
    return {
        "requests": requests,
        "cache_hits": cache_hits,
        "deduplicated_rows": max(0, original_rows - unique_rows - cache_hits),
        "requests_saved": max(0, original_rows - requests),
        "average_rows_per_request": (
            round(original_rows / requests, 2) if requests else 0
        ),
        "planned_input_tokens": int(row["planned_input_tokens"]),
        "planned_output_tokens": int(row["planned_output_tokens"]),
    }


def recover_stale_leases() -> int:
    now = utc_now()
    with transaction(immediate=True) as connection:
        rows = connection.execute(
            """
            UPDATE translation_rows SET status = 'pending', lease_expires_at = NULL,
                last_error = 'worker หยุดระหว่างประมวลผล; นำกลับเข้าคิวแล้ว', updated_at = ?
            WHERE status = 'in_progress' AND lease_expires_at IS NOT NULL
              AND lease_expires_at < ?
            """,
            (now, now),
        ).rowcount
        connection.execute(
            """
            UPDATE retranslation_requests SET status = 'pending',
                last_error = 'worker หยุดระหว่างประมวลผล; นำกลับเข้าคิวแล้ว', updated_at = ?
            WHERE status = 'in_progress' AND updated_at < ?
            """,
            (
                now,
                (datetime.now(timezone.utc) - timedelta(seconds=get_settings().row_lease_seconds))
                .isoformat(),
            ),
        )
    return rows
