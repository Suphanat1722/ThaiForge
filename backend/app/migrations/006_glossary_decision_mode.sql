ALTER TABLE glossary_entries
    ADD COLUMN translation_mode TEXT NOT NULL DEFAULT 'mixed';

ALTER TABLE glossary_entry_revisions
    ADD COLUMN translation_mode TEXT NOT NULL DEFAULT 'mixed';
