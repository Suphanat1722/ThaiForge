from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Iterable

from charset_normalizer import from_bytes


SUPPORTED_DELIMITERS = [",", ";", "\t", "|"]
ENCODING_ALIASES = {
    "utf_8": "utf-8",
    "utf_8_sig": "utf-8-sig",
    "cp874": "cp874",
    "windows_874": "cp874",
    "tis_620": "tis-620",
}


class CsvValidationError(ValueError):
    pass


def normalize_encoding(value: str) -> str:
    key = (value or "").strip().lower().replace("-", "_")
    return ENCODING_ALIASES.get(key, value.strip().lower())


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    try:
        data.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass

    try:
        thai_candidate = data.decode("cp874")
        if any("\u0e00" <= character <= "\u0e7f" for character in thai_candidate):
            return "cp874"
    except UnicodeDecodeError:
        pass

    best = from_bytes(data).best()
    if best and best.encoding:
        normalized = normalize_encoding(best.encoding)
        if normalized in {"cp874", "tis-620"}:
            return normalized
        return normalized
    return "cp874"


def detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters="".join(SUPPORTED_DELIMITERS)).delimiter
    except csv.Error:
        return ","


def validate_headers(headers: list[str] | None) -> list[str]:
    if not headers:
        raise CsvValidationError("ไม่พบแถวหัวคอลัมน์ในไฟล์ CSV")
    cleaned = [str(header or "").strip() for header in headers]
    if any(not header for header in cleaned):
        raise CsvValidationError("ชื่อคอลัมน์ต้องไม่เป็นค่าว่าง")
    if len(set(cleaned)) != len(cleaned):
        raise CsvValidationError("ชื่อคอลัมน์ใน CSV ต้องไม่ซ้ำกัน")
    return cleaned


def inspect_csv(path: Path, encoding: str | None = None, delimiter: str | None = None) -> dict:
    raw = path.read_bytes()
    selected_encoding = normalize_encoding(encoding) if encoding else detect_encoding(raw[:262_144])
    try:
        text_sample = raw[:262_144].decode(selected_encoding)
    except (UnicodeDecodeError, LookupError) as exc:
        raise CsvValidationError(f"อ่านไฟล์ด้วย encoding {selected_encoding} ไม่ได้") from exc

    selected_delimiter = delimiter or detect_delimiter(text_sample)
    if selected_delimiter not in SUPPORTED_DELIMITERS:
        raise CsvValidationError("delimiter ต้องเป็น comma, semicolon, tab หรือ pipe")

    try:
        with path.open("r", encoding=selected_encoding, newline="") as handle:
            reader = csv.reader(handle, delimiter=selected_delimiter)
            headers = validate_headers(next(reader, None))
            preview: list[dict[str, str]] = []
            for values in reader:
                if len(values) > len(headers):
                    raise CsvValidationError("บางแถวมีจำนวนคอลัมน์มากกว่าหัวตาราง")
                padded = values + [""] * (len(headers) - len(values))
                preview.append(dict(zip(headers, padded, strict=True)))
                if len(preview) >= 10:
                    break
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CsvValidationError(f"รูปแบบ CSV ไม่ถูกต้อง: {exc}") from exc

    return {
        "encoding": selected_encoding,
        "delimiter": selected_delimiter,
        "headers": headers,
        "preview": preview,
    }


def iter_csv_rows(path: Path, encoding: str, delimiter: str) -> Iterable[tuple[int, dict[str, str]]]:
    try:
        with path.open("r", encoding=normalize_encoding(encoding), newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter)
            headers = validate_headers(next(reader, None))
            for index, values in enumerate(reader):
                if len(values) > len(headers):
                    raise CsvValidationError(
                        f"แถว {index + 2} มีจำนวนคอลัมน์มากกว่าหัวตาราง"
                    )
                padded = values + [""] * (len(headers) - len(values))
                yield index, dict(zip(headers, padded, strict=True))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CsvValidationError(f"อ่าน CSV ไม่สำเร็จ: {exc}") from exc


def build_export_csv(
    headers: list[str],
    delimiter: str,
    rows: Iterable[dict],
    target_column: str,
) -> bytes:
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=headers,
        delimiter=delimiter,
        extrasaction="ignore",
        lineterminator="\r\n",
    )
    writer.writeheader()
    for row in rows:
        original = json.loads(row["original_data_json"])
        original[target_column] = (
            row["translated_text"]
            if row["translated_text"] is not None
            else row["original_target"]
        )
        writer.writerow(original)
    return buffer.getvalue().encode("utf-8-sig")


def build_error_csv(rows: Iterable[dict]) -> bytes:
    buffer = io.StringIO(newline="")
    fields = [
        "row_index",
        "source_text",
        "status",
        "last_error",
        "total_attempts",
        "retranslation_error",
    ]
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: row.get(field, "") for field in fields})
    return buffer.getvalue().encode("utf-8-sig")
