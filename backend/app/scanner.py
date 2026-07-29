from __future__ import annotations

import json

from .db import connect, transaction, utc_now
from .repository import get_job, list_glossary, new_id
from .tokens import term_matches


def affected_reasons(
    source_text: str,
    usages: list[dict],
    current_entries: dict[str, dict],
) -> list[dict]:
    reasons: dict[str, dict] = {}
    usage_by_entry = {usage["entry_id"]: usage for usage in usages}

    for usage in usages:
        current = current_entries.get(usage["entry_id"])
        if current is None or current["is_deleted"] or not current["is_active"]:
            reasons[usage["entry_id"]] = {
                "entry_id": usage["entry_id"],
                "source_term": usage["source_term"],
                "reason": "คำถูกปิดหรือลบหลังจากแปลแถวนี้",
            }
        elif current["revision"] != usage["entry_revision"]:
            reasons[usage["entry_id"]] = {
                "entry_id": usage["entry_id"],
                "source_term": current["source_term"],
                "reason": "คำแปลหรือกฎของ Glossary เปลี่ยนแล้ว",
            }

    for entry_id, entry in current_entries.items():
        if entry["is_deleted"] or not entry["is_active"]:
            continue
        if entry_id not in usage_by_entry and term_matches(source_text, entry["source_term"]):
            reasons[entry_id] = {
                "entry_id": entry_id,
                "source_term": entry["source_term"],
                "reason": "พบคำใหม่ที่ยังไม่เคยใช้กับแถวนี้",
            }

    return list(reasons.values())


def create_scan(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise KeyError(job_id)
    if job["status"] in {"uploaded", "configured", "generating_glossary"}:
        raise ValueError("ต้องสร้าง Glossary และเริ่มแปลก่อนจึงจะสแกนได้")

    entries = {entry["id"]: entry for entry in list_glossary(job_id, include_deleted=True)}
    scan_id = new_id()
    items: list[tuple[str, str, str]] = []
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT id, source_text FROM translation_rows
            WHERE job_id = ? AND translated_text IS NOT NULL
            ORDER BY row_index
            """,
            (job_id,),
        ).fetchall()
        for row in rows:
            usages = [
                dict(usage)
                for usage in connection.execute(
                    "SELECT * FROM row_glossary_usage WHERE row_id = ?", (row["id"],)
                ).fetchall()
            ]
            reasons = affected_reasons(row["source_text"], usages, entries)
            if reasons:
                items.append((scan_id, row["id"], json.dumps(reasons, ensure_ascii=False)))

    now = utc_now()
    with transaction(immediate=True) as connection:
        current = get_job(job_id, connection)
        if not current or current["glossary_revision"] != job["glossary_revision"]:
            raise ValueError("Glossary เปลี่ยนระหว่างสแกน กรุณาสแกนใหม่")
        connection.execute(
            """
            INSERT INTO retranslation_scans(
                id, job_id, glossary_revision, status, candidate_count, created_at
            ) VALUES (?, ?, ?, 'ready', ?, ?)
            """,
            (scan_id, job_id, job["glossary_revision"], len(items), now),
        )
        connection.executemany(
            """
            INSERT INTO retranslation_scan_items(scan_id, row_id, reasons_json)
            VALUES (?, ?, ?)
            """,
            items,
        )
    return get_scan(scan_id, page=1, page_size=50)


def get_scan(scan_id: str, page: int = 1, page_size: int = 50) -> dict:
    offset = (page - 1) * page_size
    with connect() as connection:
        scan = connection.execute(
            "SELECT * FROM retranslation_scans WHERE id = ?", (scan_id,)
        ).fetchone()
        if not scan:
            raise KeyError(scan_id)
        items = [
            {
                **dict(row),
                "reasons": json.loads(row["reasons_json"]),
            }
            for row in connection.execute(
                """
                SELECT i.row_id, i.reasons_json, r.row_index, r.source_text,
                       r.translated_text
                FROM retranslation_scan_items i
                JOIN translation_rows r ON r.id = i.row_id
                WHERE i.scan_id = ?
                ORDER BY r.row_index LIMIT ? OFFSET ?
                """,
                (scan_id, page_size, offset),
            ).fetchall()
        ]
    return {
        **dict(scan),
        "items": items,
        "page": page,
        "page_size": page_size,
    }


def confirm_scan(job_id: str, scan_id: str, row_ids: list[str] | None) -> dict:
    now = utc_now()
    queued = 0
    with transaction(immediate=True) as connection:
        job = get_job(job_id, connection)
        scan = connection.execute(
            "SELECT * FROM retranslation_scans WHERE id = ? AND job_id = ?",
            (scan_id, job_id),
        ).fetchone()
        if not job or not scan:
            raise KeyError(scan_id)
        if scan["status"] != "ready":
            raise ValueError("ผลสแกนนี้ถูกยืนยันไปแล้ว")
        if scan["glossary_revision"] != job["glossary_revision"]:
            raise ValueError("Glossary เปลี่ยนหลังสแกน กรุณาสแกนใหม่")

        candidates = {
            row["row_id"]
            for row in connection.execute(
                "SELECT row_id FROM retranslation_scan_items WHERE scan_id = ?",
                (scan_id,),
            ).fetchall()
        }
        selected = candidates if row_ids is None else set(row_ids)
        if not selected.issubset(candidates):
            raise ValueError("มี row_id ที่ไม่อยู่ในผลสแกน")

        for row_id in selected:
            existing = connection.execute(
                """
                SELECT 1 FROM retranslation_requests
                WHERE job_id = ? AND row_id = ? AND status IN ('pending', 'in_progress')
                """,
                (job_id, row_id),
            ).fetchone()
            if existing:
                continue
            connection.execute(
                """
                INSERT INTO retranslation_requests(
                    id, job_id, row_id, scan_id, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'pending', ?, ?)
                """,
                (new_id(), job_id, row_id, scan_id, now, now),
            )
            queued += 1

        connection.execute(
            """
            UPDATE retranslation_scans
            SET status = 'confirmed', confirmed_at = ? WHERE id = ?
            """,
            (now, scan_id),
        )
        if selected and job["status"] in {"completed", "completed_with_errors"}:
            connection.execute(
                "UPDATE jobs SET status = 'paused', updated_at = ? WHERE id = ?",
                (now, job_id),
            )
    return {"queued": queued, "selected": len(selected)}
