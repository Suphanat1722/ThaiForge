from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")


@dataclass(frozen=True)
class Settings:
    project_root: Path
    storage_dir: Path
    database_path: Path
    upload_dir: Path
    log_dir: Path
    frontend_dist: Path
    gemini_api_key: str
    gemini_model: str
    host: str
    port: int
    max_upload_bytes: int
    translation_batch_rows: int
    translation_batch_chars: int
    translation_batch_input_tokens: int
    translation_batch_output_tokens: int
    translation_batch_max_rows: int
    translation_candidate_pool_rows: int
    transient_retry_delay_seconds: int
    worker_poll_seconds: float
    row_lease_seconds: int
    glossary_chunk_rows: int
    glossary_chunk_chars: int
    gemini_daily_request_budget: int
    gemini_daily_request_warning: int


@lru_cache
def get_settings() -> Settings:
    storage_dir = Path(os.getenv("THAIFORGE_STORAGE_DIR", PROJECT_ROOT / "storage")).resolve()
    return Settings(
        project_root=PROJECT_ROOT,
        storage_dir=storage_dir,
        database_path=Path(
            os.getenv("THAIFORGE_DATABASE_PATH", storage_dir / "thaiforge.db")
        ).resolve(),
        upload_dir=Path(os.getenv("THAIFORGE_UPLOAD_DIR", storage_dir / "jobs")).resolve(),
        log_dir=Path(os.getenv("THAIFORGE_LOG_DIR", storage_dir / "logs")).resolve(),
        frontend_dist=Path(
            os.getenv("THAIFORGE_FRONTEND_DIST", PROJECT_ROOT / "frontend" / "dist")
        ).resolve(),
        gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-3.5-flash-lite").strip(),
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        max_upload_bytes=int(os.getenv("MAX_UPLOAD_MB", "50")) * 1024 * 1024,
        translation_batch_rows=max(1, int(os.getenv("TRANSLATION_BATCH_ROWS", "20"))),
        translation_batch_chars=max(100, int(os.getenv("TRANSLATION_BATCH_CHARS", "12000"))),
        translation_batch_input_tokens=max(
            4_000, int(os.getenv("TRANSLATION_BATCH_INPUT_TOKENS", "120000"))
        ),
        translation_batch_output_tokens=max(
            2_000, int(os.getenv("TRANSLATION_BATCH_OUTPUT_TOKENS", "45000"))
        ),
        translation_batch_max_rows=max(
            1, int(os.getenv("TRANSLATION_BATCH_MAX_ROWS", "500"))
        ),
        translation_candidate_pool_rows=max(
            1, int(os.getenv("TRANSLATION_CANDIDATE_POOL_ROWS", "2000"))
        ),
        transient_retry_delay_seconds=max(
            5, int(os.getenv("TRANSIENT_RETRY_DELAY_SECONDS", "30"))
        ),
        worker_poll_seconds=max(0.2, float(os.getenv("WORKER_POLL_SECONDS", "1"))),
        row_lease_seconds=max(30, int(os.getenv("ROW_LEASE_SECONDS", "300"))),
        glossary_chunk_rows=max(50, int(os.getenv("GLOSSARY_CHUNK_ROWS", "800"))),
        glossary_chunk_chars=max(5_000, int(os.getenv("GLOSSARY_CHUNK_CHARS", "120000"))),
        gemini_daily_request_budget=max(
            1, int(os.getenv("GEMINI_DAILY_REQUEST_BUDGET", "480"))
        ),
        gemini_daily_request_warning=max(
            1, int(os.getenv("GEMINI_DAILY_REQUEST_WARNING", "450"))
        ),
    )


def ensure_storage(settings: Settings | None = None) -> None:
    current = settings or get_settings()
    current.storage_dir.mkdir(parents=True, exist_ok=True)
    current.upload_dir.mkdir(parents=True, exist_ok=True)
    current.log_dir.mkdir(parents=True, exist_ok=True)
