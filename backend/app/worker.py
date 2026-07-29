from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import signal
import time
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone

from .batching import BatchEstimate, take_adaptive_batch
from .config import get_settings
from .db import connect, initialize_database, transaction, utc_now
from .gemini_service import (
    GeminiDailyQuotaError,
    GeminiMalformedResponseError,
    GeminiPermanentError,
    GeminiService,
    GeminiTransientError,
)
from .logging_config import configure_logging
from .repository import (
    get_job,
    list_glossary,
    list_style_rules,
    new_id,
    recover_stale_leases,
    legacy_translation_fingerprint,
    translation_fingerprint,
)
from .scanner import affected_reasons
from .style_defaults import DEFAULT_STYLE_RULES
from .tokens import (
    clean_for_glossary,
    matching_entries,
    normalize_term,
    rebuild_protected_text,
    segment_protected_text,
)


LOGGER = logging.getLogger("thaiforge.worker")
WORKER_ID = f"{os.getpid()}-{uuid.uuid4()}"


def _record_attempt(
    job_id: str,
    *,
    kind: str,
    row_ids: list[str],
    status: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    error: str | None = None,
    calls: int = 1,
    planned_input_tokens: int = 0,
    planned_output_tokens: int = 0,
    thinking_tokens: int = 0,
    cached_tokens: int = 0,
    original_row_count: int = 0,
    unique_row_count: int = 0,
    cache_hit_count: int = 0,
    finish_reason: str | None = None,
    failure_class: str | None = None,
) -> None:
    settings = get_settings()
    now = utc_now()
    safe_error = (error or "")[:1000] or None
    with transaction(immediate=True) as connection:
        connection.execute(
            """
            INSERT INTO ai_attempts(
                id, job_id, batch_id, row_ids_json, kind, model, status,
                input_tokens, output_tokens, error, created_at, request_count,
                planned_input_tokens, planned_output_tokens, thinking_tokens,
                cached_tokens, original_row_count, unique_row_count,
                cache_hit_count, finish_reason, failure_class
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_id(),
                job_id,
                new_id(),
                json.dumps(row_ids),
                kind,
                settings.gemini_model,
                status,
                input_tokens,
                output_tokens,
                safe_error,
                now,
                calls,
                planned_input_tokens,
                planned_output_tokens,
                thinking_tokens,
                cached_tokens,
                original_row_count,
                unique_row_count,
                cache_hit_count,
                finish_reason,
                failure_class,
            ),
        )
        connection.execute(
            """
            UPDATE jobs SET ai_calls = ai_calls + ?, input_tokens = input_tokens + ?,
                output_tokens = output_tokens + ?, updated_at = ?
            WHERE id = ?
            """,
            (calls, input_tokens, output_tokens, now, job_id),
        )


def _source_chunks(job_id: str) -> list[list[str]]:
    settings = get_settings()
    chunks: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    seen: set[str] = set()
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT source_text FROM translation_rows
            WHERE job_id = ? AND TRIM(source_text) != ''
            ORDER BY row_index
            """,
            (job_id,),
        )
        for row in rows:
            text = clean_for_glossary(row["source_text"])
            if not text:
                continue
            key = normalize_term(text)
            if key in seen:
                continue
            seen.add(key)
            if current and (
                len(current) >= settings.glossary_chunk_rows
                or current_chars + len(text) > settings.glossary_chunk_chars
            ):
                chunks.append(current)
                current = []
                current_chars = 0
            current.append(text)
            current_chars += len(text)
    if current:
        chunks.append(current)
    return chunks


def _glossary_chunk_key(job: dict, samples: list[str]) -> str:
    payload = {
        "policy": "glossary-compact-v2",
        "model": get_settings().gemini_model,
        "source_lang": job["source_lang"],
        "target_lang": job["target_lang"],
        "samples": samples,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _merge_glossary_outputs(outputs: list) -> tuple[list[tuple[str, str, str]], list[str]]:
    grouped: dict[str, dict] = {}
    for output in outputs:
        for item in output.glossary:
            source = item.source_term.strip()
            target = item.target_term.strip()
            note = item.note.strip()
            key = normalize_term(source)
            if not source or not target or not key:
                continue
            group = grouped.setdefault(
                key,
                {
                    "sources": Counter(),
                    "targets": Counter(),
                    "notes": Counter(),
                },
            )
            group["sources"][source] += 1
            group["targets"][target] += 1
            if note:
                group["notes"][note] += 1
    entries: list[tuple[str, str, str]] = []
    for group in grouped.values():
        source = group["sources"].most_common(1)[0][0]
        target = group["targets"].most_common(1)[0][0]
        note = group["notes"].most_common(1)[0][0] if group["notes"] else ""
        entries.append((source, target, note))
    entries.sort(key=lambda item: normalize_term(item[0]))
    return entries, list(DEFAULT_STYLE_RULES)


def _process_glossary_job(job: dict, service: GeminiService | None = None) -> None:
    service = service or GeminiService()
    chunks = _source_chunks(job["id"])
    if not chunks:
        with transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE jobs SET status = 'awaiting_review', last_error = NULL,
                    glossary_chunks_total = 0, glossary_chunks_completed = 0,
                    updated_at = ? WHERE id = ? AND status = 'generating_glossary'
                """,
                (utc_now(), job["id"]),
            )
        return

    with transaction(immediate=True) as connection:
        connection.execute(
            """
            UPDATE jobs SET glossary_chunks_total = ?, glossary_chunks_completed = 0,
                updated_at = ? WHERE id = ? AND status = 'generating_glossary'
            """,
            (len(chunks), utc_now(), job["id"]),
        )

    outputs: list = []
    errors: list[str] = []
    for index, samples in enumerate(chunks, start=1):
        cache_key = _glossary_chunk_key(job, samples)
        with transaction(immediate=True) as connection:
            cached = connection.execute(
                "SELECT result_json FROM glossary_chunk_cache WHERE cache_key = ?",
                (cache_key,),
            ).fetchone()
            if cached:
                from .gemini_service import GlossaryOutput

                outputs.append(GlossaryOutput.model_validate_json(cached["result_json"]))
                connection.execute(
                    """
                    UPDATE glossary_chunk_cache
                    SET hit_count = hit_count + 1, last_used_at = ?
                    WHERE cache_key = ?
                    """,
                    (utc_now(), cache_key),
                )
        if cached:
            with transaction(immediate=True) as connection:
                connection.execute(
                    """
                    UPDATE jobs SET glossary_chunks_completed = ?, updated_at = ?
                    WHERE id = ? AND status = 'generating_glossary'
                    """,
                    (index, utc_now(), job["id"]),
                )
            continue
        try:
            result = service.generate_glossary(
                samples, job["source_lang"], job["target_lang"]
            )
            outputs.append(result.value)
            now = utc_now()
            with transaction(immediate=True) as connection:
                connection.execute(
                    """
                    INSERT INTO glossary_chunk_cache(
                        cache_key, result_json, input_tokens, output_tokens,
                        created_at, last_used_at, hit_count
                    ) VALUES (?, ?, ?, ?, ?, ?, 0)
                    ON CONFLICT(cache_key) DO UPDATE SET
                        result_json = excluded.result_json,
                        input_tokens = excluded.input_tokens,
                        output_tokens = excluded.output_tokens,
                        last_used_at = excluded.last_used_at
                    """,
                    (
                        cache_key,
                        result.value.model_dump_json(),
                        result.input_tokens,
                        result.output_tokens,
                        now,
                        now,
                    ),
                )
            _record_attempt(
                job["id"],
                kind="glossary",
                row_ids=[],
                status="done",
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                calls=result.attempts,
                thinking_tokens=result.thinking_tokens,
                cached_tokens=result.cached_tokens,
                finish_reason=result.finish_reason,
            )
        except GeminiDailyQuotaError as exc:
            errors.append(str(exc))
            _record_attempt(
                job["id"],
                kind="glossary",
                row_ids=[],
                status="failed",
                error=str(exc),
                calls=exc.attempts,
            )
            break
        except Exception as exc:
            errors.append(str(exc))
            _record_attempt(
                job["id"],
                kind="glossary",
                row_ids=[],
                status="failed",
                error=str(exc),
                calls=getattr(exc, "attempts", 1),
            )
        with transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE jobs SET glossary_chunks_completed = ?, updated_at = ?
                WHERE id = ? AND status = 'generating_glossary'
                """,
                (index, utc_now(), job["id"]),
            )

    if not outputs:
        with transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE jobs SET status = 'configured', last_error = ?, updated_at = ?
                WHERE id = ? AND status = 'generating_glossary'
                """,
                ((errors[0] if errors else "สร้าง Glossary ไม่สำเร็จ")[:1000], utc_now(), job["id"]),
            )
        return

    now = utc_now()
    suggestions, merged_style_rules = _merge_glossary_outputs(outputs)

    with transaction(immediate=True) as connection:
        current = get_job(job["id"], connection)
        if not current or current["status"] != "generating_glossary":
            return
        revision = current["glossary_revision"] + 1
        connection.execute("DELETE FROM glossary_entries WHERE job_id = ?", (job["id"],))
        connection.execute(
            "DELETE FROM glossary_entry_revisions WHERE job_id = ?", (job["id"],)
        )
        for source, target, note in suggestions:
            entry_id = new_id()
            connection.execute(
                """
                INSERT INTO glossary_entries(
                    id, job_id, source_term, target_term, rule_note, is_active,
                    is_deleted, created_by, revision, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, 0, 'ai', ?, ?, ?)
                """,
                (entry_id, job["id"], source, target, note, revision, now, now),
            )
            connection.execute(
                """
                INSERT INTO glossary_entry_revisions(
                    id, job_id, entry_id, job_revision, source_term, target_term,
                    rule_note, is_active, is_deleted, changed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0, ?)
                """,
                (new_id(), job["id"], entry_id, revision, source, target, note, now),
            )

        existing_style_count = connection.execute(
            "SELECT COUNT(*) AS count FROM style_rules WHERE job_id = ?",
            (job["id"],),
        ).fetchone()["count"]
        style_revision = current["style_revision"]
        if not existing_style_count:
            style_revision += 1
            for clean in merged_style_rules:
                connection.execute(
                    """
                    INSERT INTO style_rules(
                        id, job_id, rule_text, is_active, revision, created_at, updated_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?)
                    """,
                    (new_id(), job["id"], clean, style_revision, now, now),
                )
        connection.execute(
            """
            UPDATE jobs SET status = 'awaiting_review', glossary_revision = ?,
                style_revision = ?, last_error = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                revision,
                style_revision,
                (
                    f"สร้าง Glossary ได้บางส่วน: {len(errors)} จาก {len(chunks)} ชุดล้มเหลว"
                    if errors
                    else None
                ),
                now,
                job["id"],
            ),
        )


def _take_with_budget(rows: list[dict]) -> list[dict]:
    if rows and any(row.get("failure_class") == "batch_isolation" for row in rows):
        rows = rows[:50]
    chosen, _estimate = take_adaptive_batch(rows)
    return chosen


def _claim_work(job_id: str) -> tuple[str, list[dict]]:
    settings = get_settings()
    lease = (
        datetime.now(timezone.utc) + timedelta(seconds=settings.row_lease_seconds)
    ).isoformat()
    now = utc_now()
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        if not job or job["status"] != "running":
            return "none", []

        candidates = [
            dict(row)
            for row in connection.execute(
                """
                SELECT * FROM translation_rows
                WHERE job_id = ? AND status = 'pending'
                  AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
                ORDER BY row_index LIMIT ?
                """,
                (job_id, now, settings.translation_candidate_pool_rows),
            ).fetchall()
        ]
        chosen = _take_with_budget(candidates)
        if chosen:
            ids = [row["id"] for row in chosen]
            placeholders = ",".join("?" for _ in ids)
            connection.execute(
                f"""
                UPDATE translation_rows SET status = 'in_progress',
                    lease_expires_at = ?, next_attempt_at = NULL, updated_at = ?
                WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                [lease, now, *ids],
            )
            claimed = [
                dict(row)
                for row in connection.execute(
                    f"SELECT * FROM translation_rows WHERE id IN ({placeholders})",
                    ids,
                ).fetchall()
                if row["status"] == "in_progress"
            ]
            return "translation", sorted(claimed, key=lambda item: item["row_index"])

        request_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT r.*, q.id AS request_id
                FROM retranslation_requests q
                JOIN translation_rows r ON r.id = q.row_id
                WHERE q.job_id = ? AND q.status = 'pending'
                  AND (q.next_attempt_at IS NULL OR q.next_attempt_at <= ?)
                ORDER BY q.created_at, r.row_index LIMIT ?
                """,
                (job_id, now, settings.translation_candidate_pool_rows),
            ).fetchall()
        ]
        chosen = _take_with_budget(request_rows)
        if chosen:
            request_ids = [row["request_id"] for row in chosen]
            placeholders = ",".join("?" for _ in request_ids)
            connection.execute(
                f"""
                UPDATE retranslation_requests SET status = 'in_progress',
                    next_attempt_at = NULL, updated_at = ?
                WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                [now, *request_ids],
            )
            return "retranslation", chosen
    return "none", []


def _current_usages(connection, row_id: str) -> list[dict]:
    return [
        dict(row)
        for row in connection.execute(
            "SELECT * FROM row_glossary_usage WHERE row_id = ?", (row_id,)
        ).fetchall()
    ]


def _mark_request_noop(row: dict, entries_by_id: dict[str, dict]) -> bool:
    if "request_id" not in row:
        return False
    with transaction(immediate=True) as connection:
        reasons = affected_reasons(
            row["source_text"], _current_usages(connection, row["id"]), entries_by_id
        )
        if reasons:
            return False
        connection.execute(
            """
            UPDATE retranslation_requests SET status = 'done', last_error = NULL,
                updated_at = ? WHERE id = ?
            """,
            (utc_now(), row["request_id"]),
        )
    return True


def _save_success(
    job: dict,
    row: dict,
    translated_text: str,
    entries: list[dict],
    fingerprint: str,
    *,
    from_cache: bool = False,
) -> None:
    now = utc_now()
    with transaction(immediate=True) as connection:
        if "request_id" in row:
            request = connection.execute(
                "SELECT status FROM retranslation_requests WHERE id = ?",
                (row["request_id"],),
            ).fetchone()
            if not request or request["status"] != "in_progress":
                return
        else:
            current = connection.execute(
                "SELECT status FROM translation_rows WHERE id = ?", (row["id"],)
            ).fetchone()
            if not current or current["status"] != "in_progress":
                return

        connection.execute(
            """
            UPDATE translation_rows SET translated_text = ?, status = 'done',
                last_error = NULL, auto_retry_count = 0,
                failure_class = NULL, retryable = 1, next_attempt_at = NULL,
                total_attempts = total_attempts + ?, glossary_revision_used = ?,
                style_revision_used = ?, translation_fingerprint = ?,
                lease_expires_at = NULL, updated_at = ? WHERE id = ?
            """,
            (
                translated_text,
                0 if from_cache else 1,
                job["glossary_revision"],
                job["style_revision"],
                fingerprint,
                now,
                row["id"],
            ),
        )
        connection.execute("DELETE FROM row_glossary_usage WHERE row_id = ?", (row["id"],))
        connection.executemany(
            """
            INSERT INTO row_glossary_usage(
                row_id, entry_id, entry_revision, source_term, target_term
            ) VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    row["id"],
                    entry["id"],
                    entry["revision"],
                    entry["source_term"],
                    entry["target_term"],
                )
                for entry in entries
            ],
        )
        connection.execute(
            """
            INSERT INTO translation_cache(job_id, cache_key, translated_text, usage_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(job_id, cache_key) DO UPDATE SET
                translated_text = excluded.translated_text,
                usage_json = excluded.usage_json,
                created_at = excluded.created_at
            """,
            (
                job["id"],
                fingerprint,
                translated_text,
                json.dumps([entry["id"] for entry in entries]),
                now,
            ),
        )
        connection.execute(
            """
            INSERT INTO translation_memory(
                cache_key, translated_text, usage_json, created_at, last_used_at, hit_count
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(cache_key) DO UPDATE SET
                translated_text = excluded.translated_text,
                usage_json = excluded.usage_json,
                last_used_at = excluded.last_used_at,
                hit_count = translation_memory.hit_count + excluded.hit_count
            """,
            (
                fingerprint,
                translated_text,
                json.dumps([entry["id"] for entry in entries]),
                now,
                now,
                1 if from_cache else 0,
            ),
        )
        if "request_id" in row:
            connection.execute(
                """
                UPDATE retranslation_requests SET status = 'done', last_error = NULL,
                    failure_class = NULL, retryable = 1, next_attempt_at = NULL,
                    updated_at = ? WHERE id = ?
                """,
                (now, row["request_id"]),
            )
        completed = connection.execute(
            """
            SELECT COUNT(*) AS count FROM translation_rows
            WHERE job_id = ? AND status IN ('done', 'skipped')
            """,
            (job["id"],),
        ).fetchone()["count"]
        connection.execute(
            "UPDATE jobs SET completed_rows = ?, updated_at = ? WHERE id = ?",
            (completed, now, job["id"]),
        )


def _save_failure(
    row: dict,
    message: str,
    *,
    failure_class: str = "permanent",
    retryable: bool = False,
) -> None:
    now = utc_now()
    safe = message[:1000]
    with transaction(immediate=True) as connection:
        if "request_id" in row:
            connection.execute(
                """
                UPDATE retranslation_requests SET status = 'failed',
                    last_error = ?, failure_class = ?, retryable = ?,
                    next_attempt_at = NULL, updated_at = ? WHERE id = ?
                """,
                (safe, failure_class, int(retryable), now, row["request_id"]),
            )
        else:
            connection.execute(
                """
                UPDATE translation_rows SET status = 'failed',
                    total_attempts = total_attempts + 1, last_error = ?,
                    failure_class = ?, retryable = ?, next_attempt_at = NULL,
                    lease_expires_at = NULL, updated_at = ? WHERE id = ?
                """,
                (safe, failure_class, int(retryable), now, row["id"]),
            )


def _requeue_invalid_result(row: dict, message: str) -> None:
    now = utc_now()
    safe = message[:1000]
    with transaction(immediate=True) as connection:
        if "request_id" in row:
            request = connection.execute(
                """
                SELECT auto_retry_count FROM retranslation_requests
                WHERE id = ? AND status = 'in_progress'
                """,
                (row["request_id"],),
            ).fetchone()
            if request and request["auto_retry_count"] < 1:
                connection.execute(
                    """
                    UPDATE retranslation_requests SET status = 'pending',
                        auto_retry_count = auto_retry_count + 1,
                        last_error = ?, failure_class = 'malformed_output',
                        retryable = 1, next_attempt_at = NULL,
                        updated_at = ? WHERE id = ?
                    """,
                    (safe, now, row["request_id"]),
                )
                return
        else:
            current = connection.execute(
                """
                SELECT auto_retry_count FROM translation_rows
                WHERE id = ? AND status = 'in_progress'
                """,
                (row["id"],),
            ).fetchone()
            if current and current["auto_retry_count"] < 1:
                connection.execute(
                    """
                    UPDATE translation_rows SET status = 'pending',
                        auto_retry_count = auto_retry_count + 1,
                        total_attempts = total_attempts + 1, last_error = ?,
                        failure_class = 'malformed_output', retryable = 1,
                        next_attempt_at = NULL,
                        lease_expires_at = NULL, updated_at = ? WHERE id = ?
                    """,
                    (safe, now, row["id"]),
                )
                return
    _save_failure(
        row,
        safe,
        failure_class="malformed_output",
        retryable=False,
    )


def _requeue_transient(row: dict, message: str) -> None:
    now = utc_now()
    delay = get_settings().transient_retry_delay_seconds
    retry_match = re.search(r"retry in\s+([0-9.]+)\s*(ms|s)", message, re.IGNORECASE)
    if retry_match:
        delay = float(retry_match.group(1))
        if retry_match.group(2).lower() == "ms":
            delay /= 1000
        delay = max(1.0, min(300.0, delay))
    retry_at = (
        datetime.now(timezone.utc)
        + timedelta(seconds=delay)
    ).isoformat()
    safe = message[:1000]
    with transaction(immediate=True) as connection:
        if "request_id" in row:
            current = connection.execute(
                """
                SELECT auto_retry_count FROM retranslation_requests
                WHERE id = ? AND status = 'in_progress'
                """,
                (row["request_id"],),
            ).fetchone()
            if current and current["auto_retry_count"] < 1:
                connection.execute(
                    """
                    UPDATE retranslation_requests SET status = 'pending',
                        auto_retry_count = auto_retry_count + 1,
                        last_error = ?, failure_class = 'transient',
                        retryable = 1, next_attempt_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (safe, retry_at, now, row["request_id"]),
                )
                return
        else:
            current = connection.execute(
                """
                SELECT auto_retry_count FROM translation_rows
                WHERE id = ? AND status = 'in_progress'
                """,
                (row["id"],),
            ).fetchone()
            if current and current["auto_retry_count"] < 1:
                connection.execute(
                    """
                    UPDATE translation_rows SET status = 'pending',
                        auto_retry_count = auto_retry_count + 1,
                        total_attempts = total_attempts + 1,
                        last_error = ?, failure_class = 'transient',
                        retryable = 1, next_attempt_at = ?,
                        lease_expires_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (safe, retry_at, now, row["id"]),
                )
                return
    _save_failure(row, safe, failure_class="transient", retryable=True)


def _requeue_batch_isolation(rows: list[dict], message: str) -> bool:
    if len(rows) <= 1:
        return False
    safe = message[:1000]
    now = utc_now()
    requeued = 0
    with transaction(immediate=True) as connection:
        for row in rows:
            if "request_id" in row:
                updated = connection.execute(
                    """
                    UPDATE retranslation_requests SET status = 'pending',
                        auto_retry_count = auto_retry_count + 1,
                        last_error = ?, failure_class = 'batch_isolation',
                        retryable = 1, next_attempt_at = NULL, updated_at = ?
                    WHERE id = ? AND status = 'in_progress' AND auto_retry_count < 1
                    """,
                    (safe, now, row["request_id"]),
                ).rowcount
            else:
                updated = connection.execute(
                    """
                    UPDATE translation_rows SET status = 'pending',
                        auto_retry_count = auto_retry_count + 1,
                        total_attempts = total_attempts + 1,
                        last_error = ?, failure_class = 'batch_isolation',
                        retryable = 1, next_attempt_at = NULL,
                        lease_expires_at = NULL, updated_at = ?
                    WHERE id = ? AND status = 'in_progress' AND auto_retry_count < 1
                    """,
                    (safe, now, row["id"]),
                ).rowcount
            requeued += updated
    return requeued > 0


def _pause_for_daily_quota(
    job_id: str,
    kind: str,
    rows: list[dict],
    error: GeminiDailyQuotaError,
) -> None:
    now = utc_now()
    safe = str(error)[:1000]
    with transaction(immediate=True) as connection:
        if kind == "retranslation":
            request_ids = [row["request_id"] for row in rows if "request_id" in row]
            if request_ids:
                placeholders = ",".join("?" for _ in request_ids)
                connection.execute(
                    f"""
                    UPDATE retranslation_requests SET status = 'pending',
                        last_error = ?, failure_class = 'quota', retryable = 1,
                        next_attempt_at = ?, updated_at = ?
                    WHERE id IN ({placeholders}) AND status = 'in_progress'
                    """,
                    [safe, error.resume_at, now, *request_ids],
                )
        else:
            row_ids = [row["id"] for row in rows]
            if row_ids:
                placeholders = ",".join("?" for _ in row_ids)
                connection.execute(
                    f"""
                    UPDATE translation_rows SET status = 'pending',
                        last_error = ?, failure_class = 'quota', retryable = 1,
                        next_attempt_at = ?, lease_expires_at = NULL, updated_at = ?
                    WHERE id IN ({placeholders}) AND status = 'in_progress'
                    """,
                    [safe, error.resume_at, now, *row_ids],
                )
        current = get_job(job_id, connection)
        if current and current["status"] == "running":
            connection.execute(
                """
                UPDATE jobs SET status = 'paused', pause_reason = 'quota',
                    quota_resume_at = ?, last_error = ?, updated_at = ?
                WHERE id = ?
                """,
                (error.resume_at, safe, now, job_id),
            )


def _process_batch(
    job: dict,
    kind: str,
    rows: list[dict],
    service: GeminiService | None = None,
) -> None:
    service = service or GeminiService()
    current_job = get_job(job["id"])
    if not current_job:
        return
    all_entries = list_glossary(job["id"], include_deleted=False)
    active_entries = [
        entry for entry in all_entries if entry["is_active"] and not entry["is_deleted"]
    ]
    entries_by_id = {entry["id"]: entry for entry in all_entries}
    styles = list_style_rules(job["id"])
    style_text = sorted(rule["rule_text"] for rule in styles)

    row_entries: dict[str, list[dict]] = {}
    fingerprints: dict[str, str] = {}
    pending_groups: dict[str, list[dict]] = {}
    cache_hits = 0

    for row in rows:
        if kind == "retranslation" and _mark_request_noop(row, entries_by_id):
            continue
        matches = matching_entries(row["source_text"], active_entries)
        fingerprint = translation_fingerprint(current_job, row["source_text"], matches, styles)
        legacy_fingerprint = legacy_translation_fingerprint(
            current_job, row["source_text"], matches, styles
        )
        row_entries[row["id"]] = matches
        fingerprints[row["id"]] = fingerprint
        with connect() as connection:
            cache = connection.execute(
                """
                SELECT translated_text FROM translation_memory
                WHERE cache_key = ?
                """,
                (fingerprint,),
            ).fetchone()
            if not cache:
                cache = connection.execute(
                    """
                    SELECT translated_text FROM translation_cache
                    WHERE job_id = ? AND cache_key = ?
                    """,
                    (job["id"], legacy_fingerprint),
                ).fetchone()
        if cache:
            cache_hits += 1
            _save_success(
                current_job,
                row,
                cache["translated_text"],
                matches,
                fingerprint,
                from_cache=True,
            )
        else:
            pending_groups.setdefault(fingerprint, []).append(row)

    if not pending_groups:
        return

    api_rows: list[dict] = []
    rows_for_api: list[dict] = []
    groups_by_representative: dict[str, list[dict]] = {}
    for group in pending_groups.values():
        row = group[0]
        segments, _template = segment_protected_text(row["source_text"])
        if not segments:
            for member in group:
                _save_success(
                    current_job,
                    member,
                    member["source_text"],
                    row_entries[member["id"]],
                    fingerprints[member["id"]],
                )
            continue
        api_rows.append({"id": row["id"], "segments": segments})
        rows_for_api.append(row)
        groups_by_representative[row["id"]] = group

    if not rows_for_api:
        return

    union_entries: dict[str, dict] = {}
    for row in rows_for_api:
        for entry in row_entries[row["id"]]:
            union_entries[entry["id"]] = entry

    _selected, estimate = take_adaptive_batch(rows_for_api)
    row_ids = [row["id"] for row in rows_for_api]
    api_group_rows = [
        member
        for row in rows_for_api
        for member in groups_by_representative[row["id"]]
    ]
    attempt_metrics = {
        "planned_input_tokens": estimate.input_tokens,
        "planned_output_tokens": estimate.output_tokens,
        "original_row_count": len(rows),
        "unique_row_count": len(rows_for_api),
        "cache_hit_count": cache_hits,
    }
    try:
        result = service.translate_batch(
            api_rows,
            current_job["source_lang"],
            current_job["target_lang"],
            list(union_entries.values()),
            style_text,
        )
        _record_attempt(
            job["id"],
            kind=kind,
            row_ids=row_ids,
            status="done",
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            calls=result.attempts,
            thinking_tokens=result.thinking_tokens,
            cached_tokens=result.cached_tokens,
            finish_reason=result.finish_reason,
            **attempt_metrics,
        )
    except GeminiDailyQuotaError as exc:
        _record_attempt(
            job["id"],
            kind=kind,
            row_ids=row_ids,
            status="failed",
            error=str(exc),
            calls=exc.attempts,
            failure_class="quota",
            **attempt_metrics,
        )
        _pause_for_daily_quota(job["id"], kind, api_group_rows, exc)
        return
    except GeminiMalformedResponseError as exc:
        _record_attempt(
            job["id"],
            kind=kind,
            row_ids=row_ids,
            status="failed",
            error=str(exc),
            calls=exc.attempts,
            failure_class="malformed_output",
            **attempt_metrics,
        )
        for row in api_group_rows:
            _requeue_invalid_result(row, str(exc))
        return
    except GeminiTransientError as exc:
        _record_attempt(
            job["id"],
            kind=kind,
            row_ids=row_ids,
            status="failed",
            error=str(exc),
            calls=getattr(exc, "attempts", 1),
            failure_class="transient",
            **attempt_metrics,
        )
        for row in api_group_rows:
            _requeue_transient(row, str(exc))
        return
    except GeminiPermanentError as exc:
        _record_attempt(
            job["id"],
            kind=kind,
            row_ids=row_ids,
            status="failed",
            error=str(exc),
            calls=getattr(exc, "attempts", 1),
            failure_class="permanent",
            **attempt_metrics,
        )
        if _requeue_batch_isolation(api_group_rows, str(exc)):
            return
        for row in api_group_rows:
            _save_failure(row, str(exc), failure_class="permanent", retryable=False)
        return
    except Exception as exc:
        _record_attempt(
            job["id"],
            kind=kind,
            row_ids=row_ids,
            status="failed",
            error=str(exc),
            calls=getattr(exc, "attempts", 1),
            failure_class="permanent",
            **attempt_metrics,
        )
        for row in api_group_rows:
            _save_failure(row, str(exc), failure_class="permanent", retryable=False)
        return

    translations: dict[str, object] = {}
    for item in result.value.translations:
        if item.row_id in translations:
            continue
        translations[item.row_id] = item

    for row in rows_for_api:
        group = groups_by_representative[row["id"]]
        item = translations.get(row["id"])
        if item is None:
            for member in group:
                _requeue_invalid_result(member, "Gemini ไม่คืนผลลัพธ์สำหรับแถวนี้")
            continue
        try:
            translated = rebuild_protected_text(
                row["source_text"],
                [
                    segment.model_dump()
                    for segment in item.segments  # type: ignore[attr-defined]
                ],
            )
        except ValueError as exc:
            for member in group:
                _requeue_invalid_result(member, str(exc))
            continue
        for member in group:
            _save_success(
                current_job,
                member,
                translated,
                row_entries[member["id"]],
                fingerprints[member["id"]],
            )


def _finish_if_idle(job_id: str) -> bool:
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        if not job or job["status"] != "running":
            return False
        pending = connection.execute(
            """
            SELECT COUNT(*) AS count FROM translation_rows
            WHERE job_id = ? AND status IN ('pending', 'in_progress')
            """,
            (job_id,),
        ).fetchone()["count"]
        retranslating = connection.execute(
            """
            SELECT COUNT(*) AS count FROM retranslation_requests
            WHERE job_id = ? AND status IN ('pending', 'in_progress')
            """,
            (job_id,),
        ).fetchone()["count"]
        if pending or retranslating:
            return False
        errors = connection.execute(
            "SELECT COUNT(*) AS count FROM translation_rows WHERE job_id = ? AND status = 'failed'",
            (job_id,),
        ).fetchone()["count"]
        errors += connection.execute(
            """
            SELECT COUNT(*) AS count FROM retranslation_requests
            WHERE job_id = ? AND status = 'failed'
            """,
            (job_id,),
        ).fetchone()["count"]
        status = "completed_with_errors" if errors else "completed"
        completed = connection.execute(
            """
            SELECT COUNT(*) AS count FROM translation_rows
            WHERE job_id = ? AND status IN ('done', 'skipped')
            """,
            (job_id,),
        ).fetchone()["count"]
        connection.execute(
            """
            UPDATE jobs SET status = ?, completed_rows = ?, pause_reason = NULL,
                quota_resume_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (status, completed, utc_now(), job_id),
        )
        return True


def _auto_resume_quota_job() -> bool:
    now = utc_now()
    with transaction(immediate=True) as connection:
        active = connection.execute(
            "SELECT id FROM jobs WHERE status = 'running' LIMIT 1"
        ).fetchone()
        if active:
            return False
        job = connection.execute(
            """
            SELECT id FROM jobs
            WHERE status = 'paused' AND pause_reason = 'quota'
                AND quota_resume_at IS NOT NULL AND quota_resume_at <= ?
            ORDER BY quota_resume_at, updated_at LIMIT 1
            """,
            (now,),
        ).fetchone()
        if not job:
            return False
        connection.execute(
            """
            UPDATE jobs SET status = 'running', pause_reason = NULL,
                quota_resume_at = NULL, last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now, job["id"]),
        )
        return True


def run_once(service: GeminiService | None = None) -> bool:
    recover_stale_leases()
    _auto_resume_quota_job()
    with connect() as connection:
        running = connection.execute(
            "SELECT * FROM jobs WHERE status = 'running' ORDER BY updated_at LIMIT 1"
        ).fetchone()
    if running:
        job = dict(running)
        kind, rows = _claim_work(job["id"])
        if rows:
            _process_batch(job, kind, rows, service=service)
            return True
        return _finish_if_idle(job["id"])

    with connect() as connection:
        glossary_job = connection.execute(
            """
            SELECT * FROM jobs WHERE status = 'generating_glossary'
            ORDER BY updated_at LIMIT 1
            """
        ).fetchone()
    if glossary_job:
        _process_glossary_job(dict(glossary_job), service=service)
        return True
    return False


def main() -> None:
    configure_logging("worker")
    initialize_database()
    recovered = recover_stale_leases()
    if recovered:
        LOGGER.info("recovered_stale_rows count=%s", recovered)
    settings = get_settings()
    should_stop = False

    def stop_handler(_signum, _frame) -> None:
        nonlocal should_stop
        should_stop = True

    signal.signal(signal.SIGINT, stop_handler)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, stop_handler)

    LOGGER.info("worker_started id=%s", WORKER_ID)
    while not should_stop:
        try:
            did_work = run_once()
        except Exception:
            LOGGER.exception("worker_iteration_failed")
            did_work = False
        if not did_work:
            time.sleep(settings.worker_poll_seconds)
    LOGGER.info("worker_stopped id=%s", WORKER_ID)


if __name__ == "__main__":
    main()
