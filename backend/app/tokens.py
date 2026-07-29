from __future__ import annotations

import re
import unicodedata
from collections import Counter
from typing import Iterable


PROTECTED_TOKEN_RE = re.compile(
    r"""
    \$?\{[^{}\r\n]+\}
    |%\([^)]+\)[#0\- +'0-9.]*[A-Za-z%]
    |%(?:\d+\$)?[#0\- +'0-9.]*[A-Za-z%]
    |</?[^<>\r\n]+?>
    |\\(?:[nrtbfv\\'""]|u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2})
    |&[A-Za-z0-9#]+;
    """,
    re.VERBOSE,
)
PROTECTED_PART_RE = re.compile(
    r"""
    \$?\{[^{}\r\n]+\}
    |%\([^)]+\)[#0\- +'0-9.]*[A-Za-z%]
    |%(?:\d+\$)?[#0\- +'0-9.]*[A-Za-z%]
    |</?[^<>\r\n]+?>
    |\\(?:[nrtbfv\\'""]|u[0-9A-Fa-f]{4}|x[0-9A-Fa-f]{2})
    |&[A-Za-z0-9#]+;
    |\r\n|\r|\n
    """,
    re.VERBOSE,
)
GLOSSARY_CONTROL_RE = re.compile(r"\{(?:[0-9A-Fa-f]{4}|NL)\}", re.IGNORECASE)


def extract_protected_tokens(text: str) -> list[str]:
    tokens = PROTECTED_TOKEN_RE.findall(text or "")
    tokens.extend(["\n"] * (text or "").count("\n"))
    return tokens


def validate_protected_tokens(source: str, translated: str) -> tuple[bool, str | None]:
    source_tokens = Counter(extract_protected_tokens(source))
    translated_tokens = Counter(extract_protected_tokens(translated))
    if source_tokens == translated_tokens:
        return True, None

    missing = list((source_tokens - translated_tokens).elements())
    added = list((translated_tokens - source_tokens).elements())
    details: list[str] = []
    if missing:
        details.append(f"token หาย: {', '.join(repr(item) for item in missing[:8])}")
    if added:
        details.append(f"token เกิน: {', '.join(repr(item) for item in added[:8])}")
    return False, "; ".join(details)


def segment_protected_text(text: str) -> tuple[list[dict[str, str]], list[tuple[str, str]]]:
    """Split translatable text from immutable controls while preserving exact order."""
    source = text or ""
    segments: list[dict[str, str]] = []
    template: list[tuple[str, str]] = []
    cursor = 0
    for match in PROTECTED_PART_RE.finditer(source):
        if match.start() > cursor:
            segment_id = f"s{len(segments)}"
            value = source[cursor : match.start()]
            segments.append({"segment_id": segment_id, "source_text": value})
            template.append(("segment", segment_id))
        template.append(("token", match.group(0)))
        cursor = match.end()
    if cursor < len(source):
        segment_id = f"s{len(segments)}"
        value = source[cursor:]
        segments.append({"segment_id": segment_id, "source_text": value})
        template.append(("segment", segment_id))
    return segments, template


def rebuild_protected_text(
    source: str,
    translated_segments: list[dict[str, str]],
) -> str:
    segments, template = segment_protected_text(source)
    expected = {item["segment_id"] for item in segments}
    translated: dict[str, str] = {}
    for item in translated_segments:
        segment_id = str(item.get("segment_id", ""))
        if segment_id in translated:
            raise ValueError(f"segment ซ้ำ: {segment_id}")
        translated[segment_id] = str(item.get("translated_text", ""))
    missing = sorted(expected - translated.keys())
    extra = sorted(translated.keys() - expected)
    if missing or extra:
        details: list[str] = []
        if missing:
            details.append(f"segment หาย: {', '.join(missing)}")
        if extra:
            details.append(f"segment เกิน: {', '.join(extra)}")
        raise ValueError("; ".join(details))

    rebuilt = "".join(
        value if kind == "token" else translated[value]
        for kind, value in template
    )
    valid, error = validate_protected_tokens(source, rebuilt)
    if not valid:
        raise ValueError(error or "protected token ไม่ตรง")
    return rebuilt


def normalize_term(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold()


def clean_for_glossary(text: str) -> str:
    without_controls = GLOSSARY_CONTROL_RE.sub(" ", text or "")
    return " ".join(without_controls.split())


def _is_ascii_word_term(term: str) -> bool:
    return bool(term) and term.isascii() and term[0].isalnum() and term[-1].isalnum()


def term_matches(source_text: str, source_term: str) -> bool:
    source = normalize_term(source_text)
    term = normalize_term(source_term).strip()
    if not term:
        return False
    if _is_ascii_word_term(term):
        pattern = rf"(?<![A-Za-z0-9_]){re.escape(term)}(?![A-Za-z0-9_])"
        return re.search(pattern, source) is not None
    return term in source


def matching_entries(source_text: str, entries: Iterable[dict]) -> list[dict]:
    matches = [entry for entry in entries if term_matches(source_text, entry["source_term"])]
    return sorted(matches, key=lambda item: len(normalize_term(item["source_term"])), reverse=True)
