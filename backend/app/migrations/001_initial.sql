PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    status TEXT NOT NULL,
    encoding TEXT,
    delimiter TEXT,
    headers_json TEXT NOT NULL DEFAULT '[]',
    preview_json TEXT NOT NULL DEFAULT '[]',
    source_column TEXT,
    target_column TEXT,
    source_lang TEXT,
    target_lang TEXT,
    total_rows INTEGER NOT NULL DEFAULT 0,
    completed_rows INTEGER NOT NULL DEFAULT 0,
    glossary_revision INTEGER NOT NULL DEFAULT 0,
    style_revision INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    ai_calls INTEGER NOT NULL DEFAULT 0,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS translation_rows (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    original_data_json TEXT NOT NULL,
    source_text TEXT NOT NULL,
    original_target TEXT NOT NULL DEFAULT '',
    translated_text TEXT,
    status TEXT NOT NULL,
    auto_retry_count INTEGER NOT NULL DEFAULT 0,
    total_attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    protected_tokens_json TEXT NOT NULL DEFAULT '[]',
    glossary_revision_used INTEGER,
    style_revision_used INTEGER,
    translation_fingerprint TEXT,
    lease_expires_at TEXT,
    updated_at TEXT NOT NULL,
    UNIQUE(job_id, row_index)
);

CREATE TABLE IF NOT EXISTS glossary_entries (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    rule_note TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL DEFAULT 1,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS glossary_entry_revisions (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL,
    job_revision INTEGER NOT NULL,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    rule_note TEXT NOT NULL DEFAULT '',
    is_active INTEGER NOT NULL,
    is_deleted INTEGER NOT NULL,
    changed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS style_rules (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rule_text TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS row_glossary_usage (
    row_id TEXT NOT NULL REFERENCES translation_rows(id) ON DELETE CASCADE,
    entry_id TEXT NOT NULL,
    entry_revision INTEGER NOT NULL,
    source_term TEXT NOT NULL,
    target_term TEXT NOT NULL,
    PRIMARY KEY(row_id, entry_id)
);

CREATE TABLE IF NOT EXISTS translation_cache (
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    cache_key TEXT NOT NULL,
    translated_text TEXT NOT NULL,
    usage_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    PRIMARY KEY(job_id, cache_key)
);

CREATE TABLE IF NOT EXISTS retranslation_scans (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    glossary_revision INTEGER NOT NULL,
    status TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);

CREATE TABLE IF NOT EXISTS retranslation_scan_items (
    scan_id TEXT NOT NULL REFERENCES retranslation_scans(id) ON DELETE CASCADE,
    row_id TEXT NOT NULL REFERENCES translation_rows(id) ON DELETE CASCADE,
    reasons_json TEXT NOT NULL,
    PRIMARY KEY(scan_id, row_id)
);

CREATE TABLE IF NOT EXISTS retranslation_requests (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    row_id TEXT NOT NULL REFERENCES translation_rows(id) ON DELETE CASCADE,
    scan_id TEXT REFERENCES retranslation_scans(id) ON DELETE SET NULL,
    status TEXT NOT NULL,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ai_attempts (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    batch_id TEXT,
    row_ids_json TEXT NOT NULL DEFAULT '[]',
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    status TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_rows_job_status ON translation_rows(job_id, status, row_index);
CREATE INDEX IF NOT EXISTS idx_glossary_job ON glossary_entries(job_id, is_deleted, is_active);
CREATE INDEX IF NOT EXISTS idx_usage_entry ON row_glossary_usage(entry_id);
CREATE INDEX IF NOT EXISTS idx_retranslation_job_status
    ON retranslation_requests(job_id, status, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_retranslation_open_unique
    ON retranslation_requests(job_id, row_id)
    WHERE status IN ('pending', 'in_progress');

