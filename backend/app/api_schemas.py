from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class JobConfiguration(BaseModel):
    source_column: str = Field(min_length=1)
    target_column: str = Field(min_length=1)
    source_lang: str = Field(min_length=1)
    target_lang: str = Field(min_length=1)
    encoding: str | None = None
    delimiter: str | None = None

    @field_validator("source_column", "target_column", "source_lang", "target_lang")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("ต้องไม่เป็นค่าว่าง")
        return value


class GlossaryCreate(BaseModel):
    source_term: str = Field(min_length=1)
    target_term: str = Field(min_length=1)
    rule_note: str = ""
    translation_mode: Literal["translate", "transliterate", "keep", "mixed"] = "mixed"


class GlossaryUpdate(BaseModel):
    source_term: str | None = Field(default=None, min_length=1)
    target_term: str | None = Field(default=None, min_length=1)
    rule_note: str | None = None
    is_active: bool | None = None
    translation_mode: Literal["translate", "transliterate", "keep", "mixed"] | None = None


class StyleRulesUpdate(BaseModel):
    rules: list[str]


class GlossaryRulesUpdate(BaseModel):
    rules: list[str]


class RetryFailedRequest(BaseModel):
    resume: bool = False


class ScanConfirm(BaseModel):
    row_ids: list[str] | None = None
