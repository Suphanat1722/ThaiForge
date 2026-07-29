from __future__ import annotations

from .db import connect
from .tokens import clean_for_glossary, normalize_term, term_matches


MAX_CONTEXT_EXAMPLES = 4
MAX_CONTEXT_CHARS = 360
MAX_REFINEMENT_CANDIDATES = 100
MAX_REFINEMENT_CHARS = 60_000


def _context_excerpt(text: str, term: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    clean = clean_for_glossary(text)
    if len(clean) <= max_chars:
        return clean

    index = clean.casefold().find(term.casefold())
    if index < 0:
        return clean[: max_chars - 1].rstrip() + "…"

    half = max_chars // 2
    start = max(0, index - half)
    end = min(len(clean), start + max_chars)
    start = max(0, end - max_chars)
    excerpt = clean[start:end].strip()
    if start:
        excerpt = "…" + excerpt[1:]
    if end < len(clean):
        excerpt = excerpt[:-1] + "…"
    return excerpt


def build_candidate_contexts(
    job_id: str,
    suggestions: list[tuple[str, str, str]],
) -> list[dict]:
    candidates = [
        {
            "s": source,
            "t": target,
            "n": note,
            "count": 0,
            "x": [],
            "_seen": set(),
        }
        for source, target, note in suggestions
    ]
    if not candidates:
        return []

    with connect() as connection:
        rows = connection.execute(
            """
            SELECT source_text FROM translation_rows
            WHERE job_id = ? AND TRIM(source_text) != ''
            ORDER BY row_index
            """,
            (job_id,),
        )
        for row in rows:
            source_text = row["source_text"]
            for candidate in candidates:
                if not term_matches(source_text, candidate["s"]):
                    continue
                candidate["count"] += 1
                if len(candidate["x"]) >= MAX_CONTEXT_EXAMPLES:
                    continue
                excerpt = _context_excerpt(source_text, candidate["s"])
                key = normalize_term(excerpt)
                if key and key not in candidate["_seen"]:
                    candidate["_seen"].add(key)
                    candidate["x"].append(excerpt)

    return [
        {
            "s": candidate["s"],
            "t": candidate["t"],
            "n": candidate["n"],
            "count": candidate["count"],
            "x": candidate["x"],
        }
        for candidate in candidates
    ]


def chunk_candidate_contexts(candidates: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for candidate in candidates:
        size = sum(
            len(str(value))
            for value in (
                candidate["s"],
                candidate["t"],
                candidate["n"],
                candidate["count"],
                *candidate["x"],
            )
        )
        if current and (
            len(current) >= MAX_REFINEMENT_CANDIDATES
            or current_chars + size > MAX_REFINEMENT_CHARS
        ):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(candidate)
        current_chars += size
    if current:
        chunks.append(current)
    return chunks

