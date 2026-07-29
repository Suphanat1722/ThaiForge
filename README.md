# ThaiForge

A CSV file translation system for game localization, powered by Gemini, an AI Glossary, and a durable background worker.

It supports pause/resume, retries, and selective retranslation of only the rows affected by Glossary changes.

## Getting Started on Windows

1. Copy `.env.example` to `.env` and add your `GEMINI_API_KEY`.
2. Double-click `start.cmd`, or run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start.ps1
   ```

The script will set up the Python environment, install dependencies, build the web interface, and automatically open:

`http://127.0.0.1:8000`

All data is stored in the `storage/` folder.

## Workflow

1. Upload a CSV file and verify its encoding and delimiter.
2. Select the required source and target columns, optional Context Columns, and languages.
3. Have Gemini generate a Glossary, then review and edit it before starting.
4. Start the translation, monitor progress, pause or resume the job, and retry failed rows.
5. After editing the Glossary, use Local Scan to select only the rows that need to be retranslated.
6. Review and manually correct completed translations, then export UTF-8 BOM CSV
   or download an error report.

The system processes one translation job at a time. Closing the browser tab does not stop the worker. However, closing the launcher window stops both the API and the worker.

When the system is launched again, the previous job can resume from its checkpoint.

## Gemini Quota Usage

The system automatically creates batches based on token usage and deduplicates repeated text before sending requests to Gemini.

Glossary generation uses two stages. Gemini first extracts candidates from each batch. The system then gathers occurrence counts and up to four distinct usage examples per candidate from the entire source file, and sends compact context batches back to Gemini for refinement. This favors natural Thai meanings for ordinary words while reserving transliteration for proper names, brands, and fictional terms. Both extraction and refinement results are cached when the file, languages, and input data match.

Glossary decisions use four explicit modes: translate to Thai, transliterate, keep the source text, or mix modes by phrase component. Optional project-specific overrides are available for conventions unique to one game; the universal decision framework remains fixed. Changing project overrides invalidates only the relevant Glossary cache and never deletes completed translations.

By default, each request supports up to 500 unique messages within an input budget of 120,000 tokens and an output budget of 45,000 tokens.

Cached translations can be reused across jobs when the source text, row context,
languages, Glossary, and Style settings match exactly. Changing Context Columns
invalidates the affected cache mapping.

Temporary errors are retried automatically up to one time. Permanent errors are excluded from the bulk Retry queue to avoid unnecessary quota usage.

When the daily quota is exhausted, the system continues to pause and resume automatically as usual.

## Development and Testing

```powershell
.venv\Scripts\python.exe -m compileall -q backend tests
.venv\Scripts\python.exe -m pytest -q
cd frontend
npm.cmd install
npm.cmd test -- --run
npm.cmd run build
```

While the system is running, the API documentation is available at:

`http://127.0.0.1:8000/docs`

## Project Structure

```text
backend/
  app/             FastAPI routes, repository, worker, Gemini, CSV, and context logic
  app/migrations/  SQLite migrations
frontend/
  src/pages/       Dashboard and job workspace
  src/components/  Shared feedback components
  src/lib/         Formatting, navigation, and Context Column helpers
  src/styles/      Design tokens, components, and responsive rules
scripts/           Windows launcher scripts
tests/             Backend and workflow test suites
docs/              Specifications and supporting documentation
storage/           Database, job files, and logs generated during use
```

`storage/`, `.env`, virtual environments, dependencies, caches, and production
build output are local-only and excluded from Git.
