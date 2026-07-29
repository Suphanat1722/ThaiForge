from __future__ import annotations


MAX_GLOSSARY_RULES = 20
MAX_GLOSSARY_RULE_CHARS = 300
MAX_GLOSSARY_RULES_TOTAL_CHARS = 4_000


def clean_glossary_rules(rules: list[str]) -> list[str]:
    """Validate optional project-specific overrides.

    Linguistic defaults belong to the fixed system prompt. These rules are only
    for conventions unique to one project, so an empty list is valid.
    """

    clean = [rule.strip() for rule in rules if rule.strip()]
    if len(clean) > MAX_GLOSSARY_RULES:
        raise ValueError(f"ข้อกำหนดโปรเจกต์มีได้ไม่เกิน {MAX_GLOSSARY_RULES} ข้อ")
    if any(len(rule) > MAX_GLOSSARY_RULE_CHARS for rule in clean):
        raise ValueError(
            f"ข้อกำหนดแต่ละข้อต้องยาวไม่เกิน {MAX_GLOSSARY_RULE_CHARS} ตัวอักษร"
        )
    if sum(len(rule) for rule in clean) > MAX_GLOSSARY_RULES_TOTAL_CHARS:
        raise ValueError(
            f"ข้อกำหนดรวมกันต้องยาวไม่เกิน {MAX_GLOSSARY_RULES_TOTAL_CHARS} ตัวอักษร"
        )
    return clean
