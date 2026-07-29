from pathlib import Path

import pytest

from backend.app.csv_service import CsvValidationError, build_export_csv, inspect_csv


def test_detects_windows_874_and_preserves_multiline(tmp_path: Path):
    path = tmp_path / "thai.csv"
    path.write_bytes('id,text\n1,"สวัสดี\\nโลก"\n'.encode("cp874"))

    result = inspect_csv(path)

    assert result["encoding"] in {"cp874", "tis-620"}
    assert result["headers"] == ["id", "text"]
    assert result["preview"][0]["text"] == "สวัสดี\\nโลก"


def test_rejects_duplicate_headers(tmp_path: Path):
    path = tmp_path / "bad.csv"
    path.write_text("text,text\none,two\n", encoding="utf-8")
    with pytest.raises(CsvValidationError, match="ต้องไม่ซ้ำ"):
        inspect_csv(path)


def test_export_is_utf8_bom_and_uses_latest_translation():
    rows = [
        {
            "original_data_json": '{"id":"1","source":"Hello","target":"old"}',
            "translated_text": "สวัสดี",
            "original_target": "old",
        },
        {
            "original_data_json": '{"id":"2","source":"Bye","target":"keep"}',
            "translated_text": None,
            "original_target": "keep",
        },
    ]
    content = build_export_csv(["id", "source", "target"], ",", rows, "target")
    assert content.startswith(b"\xef\xbb\xbf")
    text = content.decode("utf-8-sig")
    assert "สวัสดี" in text
    assert "keep" in text

