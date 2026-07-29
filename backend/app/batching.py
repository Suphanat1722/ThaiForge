from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .config import get_settings
from .row_context import decode_context_columns, row_context
from .tokens import segment_protected_text


PROMPT_OVERHEAD_TOKENS = 900
INPUT_SAFETY_MULTIPLIER = 1.20
OUTPUT_EXPANSION_MULTIPLIER = 1.80


@dataclass(frozen=True)
class BatchEstimate:
    input_tokens: int
    output_tokens: int


def estimate_text_tokens(value: str) -> int:
    """Conservative local estimate without spending a Gemini request."""
    ascii_chars = sum(1 for character in value if ord(character) < 128)
    unicode_chars = len(value) - ascii_chars
    return max(1, math.ceil((ascii_chars / 4) + (unicode_chars * 1.15)))


def estimate_row(row: dict) -> BatchEstimate:
    segments, _ = segment_protected_text(row.get("source_text", ""))
    source_tokens = sum(estimate_text_tokens(item["source_text"]) for item in segments)
    context = row.get("context")
    if context is None and row.get("original_data_json"):
        context = row_context(
            row["original_data_json"],
            decode_context_columns(row.get("context_columns")),
        )
    context_tokens = sum(
        estimate_text_tokens(str(name)) + estimate_text_tokens(str(value))
        for name, value in (context or {}).items()
    )
    structure_tokens = 8 + (len(segments) * 4) + context_tokens
    return BatchEstimate(
        input_tokens=math.ceil((source_tokens + structure_tokens) * INPUT_SAFETY_MULTIPLIER),
        output_tokens=math.ceil(
            ((source_tokens * OUTPUT_EXPANSION_MULTIPLIER) + structure_tokens)
            * INPUT_SAFETY_MULTIPLIER
        ),
    )


def take_adaptive_batch(rows: Iterable[dict]) -> tuple[list[dict], BatchEstimate]:
    settings = get_settings()
    candidates = list(rows)
    chosen: list[dict] = []
    input_tokens = PROMPT_OVERHEAD_TOKENS
    output_tokens = 0

    for row in candidates:
        estimate = estimate_row(row)
        fits = (
            input_tokens + estimate.input_tokens <= settings.translation_batch_input_tokens
            and output_tokens + estimate.output_tokens
            <= settings.translation_batch_output_tokens
        )
        if fits and len(chosen) < settings.translation_batch_max_rows:
            chosen.append(row)
            input_tokens += estimate.input_tokens
            output_tokens += estimate.output_tokens
        if len(chosen) >= settings.translation_batch_max_rows:
            break

    if not chosen:
        first = candidates[0] if candidates else None
        if first is not None:
            estimate = estimate_row(first)
            chosen = [first]
            input_tokens += estimate.input_tokens
            output_tokens += estimate.output_tokens

    return chosen, BatchEstimate(input_tokens=input_tokens, output_tokens=output_tokens)
