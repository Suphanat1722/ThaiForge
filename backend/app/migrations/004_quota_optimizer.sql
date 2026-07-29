ALTER TABLE translation_rows ADD COLUMN failure_class TEXT;
ALTER TABLE translation_rows ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1;
ALTER TABLE translation_rows ADD COLUMN next_attempt_at TEXT;

ALTER TABLE retranslation_requests ADD COLUMN failure_class TEXT;
ALTER TABLE retranslation_requests ADD COLUMN retryable INTEGER NOT NULL DEFAULT 1;
ALTER TABLE retranslation_requests ADD COLUMN next_attempt_at TEXT;

ALTER TABLE ai_attempts ADD COLUMN planned_input_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN planned_output_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN thinking_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN cached_tokens INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN original_row_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN unique_row_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN cache_hit_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ai_attempts ADD COLUMN finish_reason TEXT;
ALTER TABLE ai_attempts ADD COLUMN failure_class TEXT;

CREATE TABLE IF NOT EXISTS translation_memory (
    cache_key TEXT PRIMARY KEY,
    translated_text TEXT NOT NULL,
    usage_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS glossary_chunk_cache (
    cache_key TEXT PRIMARY KEY,
    result_json TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_used_at TEXT NOT NULL,
    hit_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_rows_adaptive_queue
    ON translation_rows(job_id, status, next_attempt_at, row_index);
CREATE INDEX IF NOT EXISTS idx_retranslation_adaptive_queue
    ON retranslation_requests(job_id, status, next_attempt_at, created_at);
