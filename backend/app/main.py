from __future__ import annotations

import json
import logging
import shutil
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from .api_schemas import (
    GlossaryCreate,
    GlossaryRulesUpdate,
    GlossaryUpdate,
    JobConfiguration,
    RetryFailedRequest,
    ScanConfirm,
    StyleRulesUpdate,
)
from .config import ensure_storage, get_settings
from .csv_service import (
    CsvValidationError,
    build_error_csv,
    build_export_csv,
    inspect_csv,
)
from .db import connect, initialize_database, transaction, utc_now
from .logging_config import configure_logging
from .repository import (
    active_job,
    configure_job,
    create_glossary_entry,
    create_uploaded_job,
    delete_glossary_entry,
    get_job,
    glossary_rule_settings,
    job_counts,
    list_jobs,
    list_style_rules,
    new_id,
    paginate_glossary,
    paginate_rows,
    quota_efficiency,
    replace_glossary_rules,
    replace_style_rules,
    update_glossary_entry,
)
from .quota import quota_usage
from .scanner import confirm_scan, create_scan, get_scan
from .style_defaults import DEFAULT_STYLE_RULES


configure_logging("api")
LOGGER = logging.getLogger("thaiforge.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_storage()
    initialize_database()
    yield


app = FastAPI(
    title="ThaiForge V2 API",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _public_job(job: dict, *, include_preview: bool = True) -> dict:
    result = dict(job)
    result.pop("stored_path", None)
    if not include_preview:
        result["preview"] = []
    return result


def _require_job(job_id: str) -> dict:
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="ไม่พบงานนี้")
    return job


def _conflict(message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=409, detail={"message": message, **extra})


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "launcher_protocol": 2}


@app.get("/api/jobs")
def jobs_list() -> list[dict]:
    return [_public_job(job, include_preview=False) for job in list_jobs()]


@app.get("/api/jobs/{job_id}")
def job_detail(job_id: str) -> dict:
    job = _require_job(job_id)
    job["counts"] = job_counts(job_id)
    job["style_rules"] = list_style_rules(job_id)
    job["glossary_rule_settings"] = glossary_rule_settings(job_id)
    job["quota_usage"] = quota_usage()
    job["quota_efficiency"] = quota_efficiency(job_id)
    job["failure_summary"] = _failure_summary(job_id)
    return _public_job(
        job,
        include_preview=job["status"] in {"uploaded", "configured"},
    )


def _assert_glossary_rules_editable(job_id: str) -> dict:
    job = _require_job(job_id)
    if job["status"] not in {"configured", "awaiting_review"}:
        raise _conflict("แก้กฎสร้าง Glossary ได้ก่อนเริ่มแปลเท่านั้น")
    with connect() as connection:
        translated_count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM translation_rows
            WHERE job_id = ? AND translated_text IS NOT NULL
            """,
            (job_id,),
        ).fetchone()["count"]
    if translated_count:
        raise _conflict("งานนี้เริ่มแปลแล้ว จึงแก้กฎสร้าง Glossary ไม่ได้")
    return job


@app.put("/api/jobs/{job_id}/glossary-rules")
def glossary_rules_update(job_id: str, payload: GlossaryRulesUpdate) -> dict:
    _assert_glossary_rules_editable(job_id)
    try:
        return replace_glossary_rules(job_id, payload.rules)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _failure_summary(job_id: str) -> dict[str, int]:
    summary = {
        "quota": 0,
        "protected_format": 0,
        "temporary_service": 0,
        "permanent": 0,
    }
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT COALESCE(last_error, '') AS error, COUNT(*) AS count
            FROM translation_rows
            WHERE job_id = ? AND status = 'failed'
            GROUP BY COALESCE(last_error, '')
            """,
            (job_id,),
        ).fetchall()
    for row in rows:
        error = row["error"].casefold()
        if "429" in error and (
            "perday" in error or "free_tier_requests" in error
        ):
            key = "quota"
        elif "token" in error or "segment" in error:
            key = "protected_format"
        elif (
            "503" in error
            or "timeout" in error
            or "timed out" in error
            or "10013" in error
            or "network" in error
        ):
            key = "temporary_service"
        else:
            key = "permanent"
        summary[key] += row["count"]
    return summary


@app.post("/api/jobs/upload", status_code=201)
async def upload_job(file: UploadFile = File(...)) -> dict:
    settings = get_settings()
    filename = Path(file.filename or "upload.csv").name
    if not filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="รองรับเฉพาะไฟล์ .csv")

    job_id = new_id()
    job_dir = settings.upload_dir / job_id
    job_dir.mkdir(parents=True, exist_ok=False)
    stored_path = job_dir / "source.csv"
    total = 0
    try:
        with stored_path.open("wb") as handle:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"ไฟล์ใหญ่เกิน {settings.max_upload_bytes // (1024 * 1024)} MB",
                    )
                handle.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="ไฟล์ว่าง")
        inspection = inspect_csv(stored_path)
        return _public_job(create_uploaded_job(filename, stored_path, inspection))
    except HTTPException:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    except CsvValidationError as exc:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        LOGGER.exception("upload_failed")
        raise HTTPException(status_code=500, detail="อัปโหลดไฟล์ไม่สำเร็จ")
    finally:
        await file.close()


@app.put("/api/jobs/{job_id}/configuration")
def configure(job_id: str, payload: JobConfiguration) -> dict:
    job = _require_job(job_id)
    try:
        inspection = inspect_csv(
            Path(job["stored_path"]),
            encoding=payload.encoding or job["encoding"],
            delimiter=payload.delimiter or job["delimiter"],
        )
        configured = configure_job(
            job_id,
            payload.source_column,
            payload.target_column,
            payload.source_lang,
            payload.target_lang,
            inspection["encoding"],
            inspection["delimiter"],
            inspection["headers"],
            inspection["preview"],
        )
        return _public_job(configured)
    except CsvValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise _conflict(str(exc)) from exc


@app.post("/api/jobs/{job_id}/glossary/generate", status_code=202)
def generate_glossary(job_id: str) -> dict:
    job = _require_job(job_id)
    if job["status"] not in {"configured", "awaiting_review"}:
        raise _conflict("สร้าง Glossary ได้ก่อนเริ่มแปลเท่านั้น")
    with connect() as connection:
        translated_count = connection.execute(
            """
            SELECT COUNT(*) AS count FROM translation_rows
            WHERE job_id = ? AND translated_text IS NOT NULL
            """,
            (job_id,),
        ).fetchone()["count"]
    if translated_count:
        raise _conflict("งานนี้เริ่มแปลแล้ว จึงไม่สามารถสร้าง Glossary ใหม่ทั้งชุดได้")
    if not get_settings().gemini_api_key:
        raise HTTPException(
            status_code=400,
            detail="กรุณาตั้งค่า GEMINI_API_KEY ในไฟล์ .env แล้วเปิดระบบใหม่",
        )
    with transaction(immediate=True) as connection:
        connection.execute(
            """
            UPDATE jobs SET status = 'generating_glossary', last_error = NULL,
                glossary_chunks_total = 0, glossary_chunks_completed = 0,
                updated_at = ? WHERE id = ? AND status IN ('configured', 'awaiting_review')
            """,
            (utc_now(), job_id),
        )
    return {"status": "generating_glossary"}


@app.get("/api/jobs/{job_id}/glossary")
def glossary_list(
    job_id: str,
    q: str | None = Query(None, max_length=200),
    state: str | None = Query(None, pattern="^(active|inactive)$"),
    origin: str | None = Query(None, pattern="^(ai|user)$"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    _require_job(job_id)
    result = paginate_glossary(job_id, page, page_size, q, state, origin)
    return {
        "entries": result["items"],
        "style_rules": list_style_rules(job_id),
        "glossary_rule_settings": glossary_rule_settings(job_id),
        "total": result["total"],
        "page": result["page"],
        "page_size": result["page_size"],
    }


@app.post("/api/jobs/{job_id}/glossary", status_code=201)
def glossary_create(job_id: str, payload: GlossaryCreate) -> dict:
    job = _require_job(job_id)
    if job["status"] in {"uploaded", "generating_glossary"}:
        raise _conflict("ยังแก้ Glossary ในสถานะนี้ไม่ได้")
    return create_glossary_entry(
        job_id,
        payload.source_term,
        payload.target_term,
        payload.rule_note,
        translation_mode=payload.translation_mode,
    )


@app.patch("/api/jobs/{job_id}/glossary/{entry_id}")
def glossary_update(job_id: str, entry_id: str, payload: GlossaryUpdate) -> dict:
    _require_job(job_id)
    updates = payload.model_dump(exclude_none=True)
    try:
        return update_glossary_entry(job_id, entry_id, updates)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ไม่พบ Glossary entry") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/api/jobs/{job_id}/glossary/{entry_id}", status_code=204)
def glossary_delete(job_id: str, entry_id: str) -> Response:
    _require_job(job_id)
    try:
        delete_glossary_entry(job_id, entry_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ไม่พบ Glossary entry") from exc
    return Response(status_code=204)


@app.put("/api/jobs/{job_id}/style-rules")
def style_rules_update(job_id: str, payload: StyleRulesUpdate) -> dict:
    job = _require_job(job_id)
    if job["status"] in {"uploaded", "generating_glossary"}:
        raise _conflict("ยังแก้ Style rules ในสถานะนี้ไม่ได้")
    return {"style_rules": replace_style_rules(job_id, payload.rules)}


@app.post("/api/jobs/{job_id}/style-rules/use-defaults")
def style_rules_use_defaults(job_id: str) -> dict:
    job = _require_job(job_id)
    if job["status"] in {"uploaded", "generating_glossary"}:
        raise _conflict("ยังแก้กฎสไตล์ในสถานะนี้ไม่ได้")
    return {"style_rules": replace_style_rules(job_id, DEFAULT_STYLE_RULES)}


def _ensure_no_other_active_job(job_id: str) -> None:
    active = active_job(excluding=job_id)
    if active:
        raise _conflict(
            "มีงานอื่นกำลังแปลอยู่ กรุณาหยุดหรือรอให้งานนั้นเสร็จ",
            active_job_id=active["id"],
        )


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str) -> dict:
    job = _require_job(job_id)
    if job["status"] != "awaiting_review":
        raise _conflict("เริ่มงานได้หลังตรวจ Glossary แล้วเท่านั้น")
    _ensure_no_other_active_job(job_id)
    with transaction(immediate=True) as connection:
        connection.execute(
            """
            UPDATE jobs SET status = 'running', last_error = NULL,
                pause_reason = NULL, quota_resume_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), job_id),
        )
    return {"status": "running"}


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str) -> dict:
    job = _require_job(job_id)
    if job["status"] != "running":
        raise _conflict("หยุดชั่วคราวได้เฉพาะงานที่กำลังรัน")
    with transaction(immediate=True) as connection:
        connection.execute(
            """
            UPDATE jobs SET status = 'paused', pause_reason = 'manual',
                quota_resume_at = NULL, updated_at = ? WHERE id = ?
            """,
            (utc_now(), job_id),
        )
    return {"status": "paused"}


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str) -> dict:
    job = _require_job(job_id)
    if job["status"] != "paused":
        raise _conflict("ทำต่อได้เฉพาะงานที่หยุดไว้")
    counts = job_counts(job_id)
    if not (
        counts["pending"]
        or counts["retranslation_pending"]
        or counts["in_progress"]
        or counts["retranslation_in_progress"]
    ):
        raise _conflict("ไม่มีแถวที่รอประมวลผล")
    _ensure_no_other_active_job(job_id)
    with transaction(immediate=True) as connection:
        connection.execute(
            """
            UPDATE jobs SET status = 'running', pause_reason = NULL,
                quota_resume_at = NULL, last_error = NULL, updated_at = ?
            WHERE id = ?
            """,
            (utc_now(), job_id),
        )
    return {"status": "running"}


def _retry_failed(job_id: str, row_id: str | None = None) -> tuple[int, int]:
    now = utc_now()
    with transaction(immediate=True) as connection:
        if row_id:
            skipped_permanent = connection.execute(
                """
                SELECT COUNT(*) AS count FROM translation_rows
                WHERE job_id = ? AND id = ? AND status = 'failed' AND retryable = 0
                """,
                (job_id, row_id),
            ).fetchone()["count"]
            skipped_permanent += connection.execute(
                """
                SELECT COUNT(*) AS count FROM retranslation_requests
                WHERE job_id = ? AND row_id = ? AND status = 'failed' AND retryable = 0
                """,
                (job_id, row_id),
            ).fetchone()["count"]
        else:
            skipped_permanent = connection.execute(
                """
                SELECT COUNT(*) AS count FROM translation_rows
                WHERE job_id = ? AND status = 'failed' AND retryable = 0
                """,
                (job_id,),
            ).fetchone()["count"]
            skipped_permanent += connection.execute(
                """
                SELECT COUNT(*) AS count FROM retranslation_requests
                WHERE job_id = ? AND status = 'failed' AND retryable = 0
                """,
                (job_id,),
            ).fetchone()["count"]
        if row_id:
            updated = connection.execute(
                """
                UPDATE translation_rows SET status = 'pending', auto_retry_count = 0,
                    last_error = NULL, failure_class = NULL, next_attempt_at = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE job_id = ? AND id = ? AND status = 'failed' AND retryable = 1
                """,
                (now, job_id, row_id),
            ).rowcount
            updated += connection.execute(
                """
                UPDATE retranslation_requests SET status = 'pending',
                    auto_retry_count = 0, last_error = NULL, failure_class = NULL,
                    next_attempt_at = NULL, updated_at = ?
                WHERE job_id = ? AND row_id = ? AND status = 'failed' AND retryable = 1
                """,
                (now, job_id, row_id),
            ).rowcount
        else:
            updated = connection.execute(
                """
                UPDATE translation_rows SET status = 'pending', auto_retry_count = 0,
                    last_error = NULL, failure_class = NULL, next_attempt_at = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE job_id = ? AND status = 'failed' AND retryable = 1
                """,
                (now, job_id),
            ).rowcount
            updated += connection.execute(
                """
                UPDATE retranslation_requests SET status = 'pending',
                    auto_retry_count = 0, last_error = NULL, failure_class = NULL,
                    next_attempt_at = NULL, updated_at = ?
                WHERE job_id = ? AND status = 'failed' AND retryable = 1
                """,
                (now, job_id),
            ).rowcount
        job = get_job(job_id, connection)
        if updated and job and job["status"] in {"completed", "completed_with_errors"}:
            connection.execute(
                "UPDATE jobs SET status = 'paused', updated_at = ? WHERE id = ?",
                (now, job_id),
            )
    return updated, skipped_permanent


@app.post("/api/jobs/{job_id}/retry-failed")
def retry_failed(job_id: str, payload: RetryFailedRequest | None = None) -> dict:
    _require_job(job_id)
    queued, skipped_permanent = _retry_failed(job_id)
    current = _require_job(job_id)
    should_resume = bool(payload and payload.resume)
    if should_resume and queued:
        if current["status"] == "running":
            return {
                "queued": queued,
                "skipped_permanent": skipped_permanent,
                "status": "running",
            }
        if current["status"] != "paused":
            raise _conflict("งานยังไม่พร้อมเริ่มแปลต่อ")
        _ensure_no_other_active_job(job_id)
        with transaction(immediate=True) as connection:
            connection.execute(
                """
                UPDATE jobs SET status = 'running', pause_reason = NULL,
                    quota_resume_at = NULL, last_error = NULL, updated_at = ?
                WHERE id = ? AND status = 'paused'
                """,
                (utc_now(), job_id),
            )
        return {
            "queued": queued,
            "skipped_permanent": skipped_permanent,
            "status": "running",
        }
    return {
        "queued": queued,
        "skipped_permanent": skipped_permanent,
        "status": current["status"],
    }


@app.post("/api/jobs/{job_id}/rows/{row_id}/retry")
def retry_row(job_id: str, row_id: str) -> dict:
    _require_job(job_id)
    queued, skipped_permanent = _retry_failed(job_id, row_id)
    if skipped_permanent:
        raise _conflict("ข้อผิดพลาดนี้เป็นแบบถาวรและไม่ควร Retry ซ้ำ")
    if not queued:
        raise HTTPException(status_code=404, detail="ไม่พบแถวที่ล้มเหลว")
    return {"queued": queued}


@app.get("/api/jobs/{job_id}/status")
def status(job_id: str) -> dict:
    job = _require_job(job_id)
    return {
        "id": job["id"],
        "status": job["status"],
        "total_rows": job["total_rows"],
        "completed_rows": job["completed_rows"],
        "last_error": job["last_error"],
        "ai_calls": job["ai_calls"],
        "input_tokens": job["input_tokens"],
        "output_tokens": job["output_tokens"],
        "glossary_revision": job["glossary_revision"],
        "style_revision": job["style_revision"],
        "glossary_chunks_total": job["glossary_chunks_total"],
        "glossary_chunks_completed": job["glossary_chunks_completed"],
        "counts": job_counts(job_id),
        "pause_reason": job["pause_reason"],
        "quota_resume_at": job["quota_resume_at"],
        "quota_usage": quota_usage(),
        "failure_summary": _failure_summary(job_id),
        "quota_efficiency": quota_efficiency(job_id),
    }


@app.get("/api/jobs/{job_id}/rows")
def rows(
    job_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    row_status: str | None = Query(None, alias="status"),
    q: str | None = Query(None, max_length=200),
) -> dict:
    _require_job(job_id)
    return paginate_rows(job_id, page, page_size, row_status, q)


def _download_headers(filename: str) -> dict[str, str]:
    quoted = urllib.parse.quote(filename)
    return {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted}"}


@app.get("/api/jobs/{job_id}/export")
def export_job(job_id: str) -> Response:
    job = _require_job(job_id)
    if not job["target_column"]:
        raise _conflict("งานยังไม่ได้ตั้งค่า Target column")
    with connect() as connection:
        result_rows = connection.execute(
            "SELECT * FROM translation_rows WHERE job_id = ? ORDER BY row_index",
            (job_id,),
        ).fetchall()
    content = build_export_csv(
        job["headers"], job["delimiter"], result_rows, job["target_column"]
    )
    stem = Path(job["filename"]).stem
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers=_download_headers(f"{stem}_translated.csv"),
    )


@app.get("/api/jobs/{job_id}/errors/export")
def export_errors(job_id: str) -> Response:
    job = _require_job(job_id)
    with connect() as connection:
        error_rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT r.row_index, r.source_text, r.status, r.last_error,
                       r.total_attempts,
                       GROUP_CONCAT(q.last_error, ' | ') AS retranslation_error
                FROM translation_rows r
                LEFT JOIN retranslation_requests q
                  ON q.row_id = r.id AND q.status = 'failed'
                WHERE r.job_id = ? AND (r.status = 'failed' OR q.id IS NOT NULL)
                GROUP BY r.id ORDER BY r.row_index
                """,
                (job_id,),
            ).fetchall()
        ]
    content = build_error_csv(error_rows)
    stem = Path(job["filename"]).stem
    return Response(
        content,
        media_type="text/csv; charset=utf-8",
        headers=_download_headers(f"{stem}_errors.csv"),
    )


@app.post("/api/jobs/{job_id}/retranslation-scans", status_code=201)
def scan_create(job_id: str) -> dict:
    _require_job(job_id)
    try:
        return create_scan(job_id)
    except ValueError as exc:
        raise _conflict(str(exc)) from exc


@app.get("/api/jobs/{job_id}/retranslation-scans/{scan_id}")
def scan_detail(
    job_id: str,
    scan_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict:
    _require_job(job_id)
    try:
        scan = get_scan(scan_id, page, page_size)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ไม่พบผลสแกน") from exc
    if scan["job_id"] != job_id:
        raise HTTPException(status_code=404, detail="ไม่พบผลสแกน")
    return scan


@app.post("/api/jobs/{job_id}/retranslation-scans/{scan_id}/confirm")
def scan_confirm(job_id: str, scan_id: str, payload: ScanConfirm) -> dict:
    _require_job(job_id)
    try:
        return confirm_scan(job_id, scan_id, payload.row_ids)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="ไม่พบผลสแกน") from exc
    except ValueError as exc:
        raise _conflict(str(exc)) from exc


@app.delete("/api/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    job = _require_job(job_id)
    if job["status"] in {"running", "generating_glossary"}:
        raise _conflict("กรุณาหยุดงานก่อนลบ")

    settings = get_settings()
    stored = Path(job["stored_path"]).resolve()
    expected_parent = (settings.upload_dir / job_id).resolve()
    if stored.parent != expected_parent or expected_parent.parent != settings.upload_dir.resolve():
        raise HTTPException(status_code=500, detail="ตำแหน่งไฟล์งานไม่ปลอดภัยสำหรับการลบ")

    with transaction(immediate=True) as connection:
        connection.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    shutil.rmtree(expected_parent, ignore_errors=True)
    return Response(status_code=204)


settings = get_settings()
if settings.frontend_dist.exists():
    assets_dir = settings.frontend_dist / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="frontend-assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="ไม่พบ API endpoint")
        requested = (settings.frontend_dist / full_path).resolve()
        if (
            requested != settings.frontend_dist.resolve()
            and settings.frontend_dist.resolve() in requested.parents
            and requested.is_file()
        ):
            return FileResponse(requested)
        return FileResponse(settings.frontend_dist / "index.html")
