"""Check hand-corrected document data before it replaces what the AI read.

Badly shaped data is refused with a 422 before anything changes, instead of failing half way through saving.
Unknown extra fields are kept.
"""
import datetime as dt
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class _Open(BaseModel):
    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)


class _Medication(_Open):
    name: str = Field(min_length=1)
    generic_name: str | None = None
    strength: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    route: str | None = None
    timing: str | None = None
    instructions: str | None = None
    duration: str | None = None
    confidence: float | None = None


class _Lab(_Open):
    test_name: str = Field(min_length=1)
    test_value: str | None = None
    unit: str | None = None
    reference_range: str | None = None
    specimen_type: str | None = None
    is_abnormal: bool | None = None
    confidence: float | None = None


class _Allergy(_Open):
    allergen: str = Field(min_length=1)
    reaction: str | None = None


class Corrected(_Open):
    category: str = "other"
    document_date: str | None = None
    follow_up_date: str | None = None
    discharge_date: str | None = None
    follow_up_text: str | None = None
    doctor: str | None = None
    hospital: str | None = None
    medications: list[_Medication] = []
    lab_results: list[_Lab] = []
    allergies: list[_Allergy] = []
    diagnoses: list[str] = []
    past_medical_history: list[str] = []
    bill_total: float | None = Field(None, gt=0, le=100_000_000)
    bill_currency: Literal["INR", "USD", "EUR", "GBP"] | None = None
    confidence: float | None = None

    @field_validator("document_date", "follow_up_date", "discharge_date")
    @classmethod
    def _iso(cls, v):
        if v:
            dt.date.fromisoformat(v)          # ValueError becomes a validation error
        return v or None


def check_corrected(data: dict) -> dict:
    try:
        return Corrected.model_validate(data).model_dump()
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first["loc"])
        raise HTTPException(422, f"corrected_data is not valid at '{where}': {first['msg']}")
