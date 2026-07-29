from __future__ import annotations

import json
from collections.abc import Mapping


def decode_context_columns(value: str | list[str] | None) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not value:
        return []
    try:
        decoded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(decoded, list):
        return []
    return [str(item) for item in decoded]


def row_context(
    original_data: str | Mapping[str, object] | None,
    context_columns: list[str],
) -> dict[str, str]:
    if not context_columns:
        return {}
    if isinstance(original_data, str):
        try:
            decoded = json.loads(original_data)
        except (TypeError, json.JSONDecodeError):
            return {}
    else:
        decoded = original_data
    if not isinstance(decoded, Mapping):
        return {}

    context: dict[str, str] = {}
    for column in context_columns:
        value = decoded.get(column)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            context[column] = text
    return context


def context_for_row(row: Mapping[str, object], job: Mapping[str, object]) -> dict[str, str]:
    columns = decode_context_columns(
        job.get("context_columns", job.get("context_columns_json"))
    )
    return row_context(row.get("original_data_json"), columns)
