from backend.app.tokens import (
    clean_for_glossary,
    extract_protected_tokens,
    rebuild_protected_text,
    segment_protected_text,
    term_matches,
    validate_protected_tokens,
)


def test_protected_tokens_and_newlines_are_strict():
    source = "Hello {name}\\n<color=red>%s</color>\nNext"
    valid = "สวัสดี {name}\\n<color=red>%s</color>\nต่อไป"
    invalid = "สวัสดี {player}\\n<color=red>%s</color>"

    assert "{name}" in extract_protected_tokens(source)
    assert validate_protected_tokens(source, valid) == (True, None)
    ok, message = validate_protected_tokens(source, invalid)
    assert not ok
    assert "token หาย" in (message or "")


def test_term_matching_uses_ascii_boundaries_and_unicode_substrings():
    assert term_matches("Use HP Potion", "HP")
    assert not term_matches("Board the SHIP", "HP")
    assert term_matches("勇者の剣を入手", "勇者")


def test_glossary_cleaner_removes_game_controls_but_keeps_names():
    text = "{0FEB}{0FF7}Karen met Rick{NL}at the Poultry Farm."
    assert clean_for_glossary(text) == "Karen met Rick at the Poultry Farm."


def test_segment_translation_rebuilds_controls_in_exact_order():
    source = "{0FEB}{0FF7}Hello {400A}!{NL}Welcome home."
    segments, template = segment_protected_text(source)

    assert [item["source_text"] for item in segments] == [
        "Hello ",
        "!",
        "Welcome home.",
    ]
    assert template[0] == ("token", "{0FEB}")

    rebuilt = rebuild_protected_text(
        source,
        [
            {"segment_id": "s0", "translated_text": "สวัสดี "},
            {"segment_id": "s1", "translated_text": "!"},
            {"segment_id": "s2", "translated_text": "ยินดีต้อนรับกลับบ้าน"},
        ],
    )
    assert rebuilt == "{0FEB}{0FF7}สวัสดี {400A}!{NL}ยินดีต้อนรับกลับบ้าน"
    assert validate_protected_tokens(source, rebuilt) == (True, None)


def test_segment_translation_rejects_missing_or_added_segments():
    source = "Hello {name}!"
    try:
        rebuild_protected_text(
            source,
            [{"segment_id": "s0", "translated_text": "สวัสดี "}],
        )
    except ValueError as exc:
        assert "segment หาย" in str(exc)
    else:
        raise AssertionError("missing segment must be rejected")


def test_control_only_row_needs_no_translatable_segments():
    segments, template = segment_protected_text("{0FEB}{NL}{0FF7}")
    assert segments == []
    assert template == [
        ("token", "{0FEB}"),
        ("token", "{NL}"),
        ("token", "{0FF7}"),
    ]
