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
2. Select the source and target columns, along with the source and target languages.
3. Have Gemini generate a Glossary, then review and edit it before starting.
4. Start the translation, monitor progress, pause or resume the job, and retry failed rows.
5. After editing the Glossary, use Local Scan to select only the rows that need to be retranslated.
6. Export the CSV with UTF-8 BOM encoding or download an error report.

The system processes one translation job at a time. Closing the browser tab does not stop the worker. However, closing the launcher window stops both the API and the worker.

When the system is launched again, the previous job can resume from its checkpoint.

## Gemini Quota Usage

The system automatically creates batches based on token usage and deduplicates repeated text before sending requests to Gemini.

By default, each request supports up to 500 unique messages within an input budget of 120,000 tokens and an output budget of 45,000 tokens.

Cached translations can be reused across jobs when the languages, Glossary, and Style settings match exactly.

Temporary errors are retried automatically up to one time. Permanent errors are excluded from the bulk Retry queue to avoid unnecessary quota usage.

When the daily quota is exhausted, the system continues to pause and resume automatically as usual.

## Development and Testing

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
cd frontend
npm.cmd install
npm.cmd run build
```

While the system is running, the API documentation is available at:

`http://127.0.0.1:8000/docs`

## Project Structure

```text
backend/
  app/             FastAPI, worker, database, and Gemini services
  app/migrations/  SQLite migrations
frontend/
  src/             React application
scripts/           Windows launcher scripts
tests/             Backend and workflow test suites
docs/              Specifications and supporting documentation
storage/           Database, job files, and logs generated during use
```
