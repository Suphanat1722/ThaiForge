ALTER TABLE jobs ADD COLUMN pause_reason TEXT;
ALTER TABLE jobs ADD COLUMN quota_resume_at TEXT;

ALTER TABLE ai_attempts ADD COLUMN request_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE retranslation_requests ADD COLUMN auto_retry_count INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS quota_usage (
    credential_fingerprint TEXT NOT NULL,
    model TEXT NOT NULL,
    quota_day TEXT NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (credential_fingerprint, model, quota_day)
);

