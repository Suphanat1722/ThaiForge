ALTER TABLE jobs ADD COLUMN glossary_rules_revision INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN glossary_rules_applied_revision INTEGER NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS glossary_rules (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    rule_text TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    revision INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_glossary_rules_job
    ON glossary_rules(job_id, is_active, created_at);
