from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


TEST_STORAGE = Path(tempfile.mkdtemp(prefix="thaiforge-tests-"))
os.environ["THAIFORGE_STORAGE_DIR"] = str(TEST_STORAGE)
os.environ["THAIFORGE_DATABASE_PATH"] = str(TEST_STORAGE / "test.db")
os.environ["THAIFORGE_UPLOAD_DIR"] = str(TEST_STORAGE / "jobs")
os.environ["THAIFORGE_LOG_DIR"] = str(TEST_STORAGE / "logs")
os.environ["GEMINI_API_KEY"] = "test-key"


@pytest.fixture(autouse=True)
def clean_database():
    from backend.app.config import get_settings
    from backend.app.db import initialize_database

    get_settings.cache_clear()
    settings = get_settings()
    settings.database_path.unlink(missing_ok=True)
    initialize_database()
    yield

