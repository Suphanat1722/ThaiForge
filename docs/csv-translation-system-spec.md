# ThaiForge System Specification

## Scope

ThaiForge is a local-first CSV game-localization workbench. A FastAPI process
serves the React application and API while a separate worker processes durable
SQLite jobs. Closing the browser does not stop work; stopping the launcher stops
the API and worker without deleting progress.

## Data safety

- Uploaded CSV rows are stored in `translation_rows.original_data_json`.
- Every source column and untouched CSV column is preserved during export.
- A successful translation is committed per row; partial results survive pause,
  process restart, quota exhaustion, and later retries.
- Retry queues include only retryable failures and never reset completed rows.
- Additive migrations are recorded in `schema_migrations`.
- Migrations that materially change job processing create a SQLite backup before
  applying when existing jobs are present.
- Runtime data lives under `storage/` and is excluded from Git.

## Workflow

1. Upload and inspect a CSV file.
2. Select required Source and Target Columns.
3. Optionally select any number of Context Columns. Source and Target cannot also
   be context.
4. Generate and review a four-mode Glossary:
   `translate`, `transliterate`, `keep`, or `mixed`.
5. Start translation and use pause/resume or retry for remaining retryable rows.
6. Review completed rows, manually correct translations, and export CSV.
7. After a Glossary revision, run the local scan and confirm only affected rows
   for retranslation.

## Context Columns

Context is derived per row from the original CSV data. Only selected, non-empty
values are sent to Gemini. It may guide meaning, tone, speaker, or situation but
must never be translated or returned in structured output.

Translation fingerprints include the selected mapping and actual row context.
Glossary extraction/refinement cache keys include the mapping and context payload.
Jobs without Context Columns retain the original compact payload and cache
behavior.

## Gemini boundaries

- Translation requests use compact batched structured output.
- Structured output contains only row/segment identifiers and translated text.
- Protected tokens and control codes are segmented and rebuilt locally.
- Glossary generation uses candidate extraction followed by corpus-context
  refinement; no separate context-analysis request is made.
- Permanent errors are not automatically retried.
- Tests use fake services and must not call Gemini.

## Manual review

Completed rows can be edited only when a job is paused or in a completed review
state. The API validates protected tokens/control codes before saving. A manual
edit updates only that row's `translated_text`; source data, context, Glossary,
and other rows remain unchanged. Export always uses the latest saved value.

## Main API surface

```text
POST   /api/jobs/upload
PUT    /api/jobs/{job_id}/configuration
POST   /api/jobs/{job_id}/glossary/generate
GET    /api/jobs/{job_id}/glossary
POST   /api/jobs/{job_id}/start
POST   /api/jobs/{job_id}/pause
POST   /api/jobs/{job_id}/resume
POST   /api/jobs/{job_id}/retry-failed
GET    /api/jobs/{job_id}/rows
PATCH  /api/jobs/{job_id}/rows/{row_id}
POST   /api/jobs/{job_id}/retranslation-scans
GET    /api/jobs/{job_id}/export
GET    /api/jobs/{job_id}/errors/export
```

## Verification

Before release:

```powershell
.venv\Scripts\python.exe -m compileall -q backend tests
.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd test -- --run
npm.cmd run build
```
