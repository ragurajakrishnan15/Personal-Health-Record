"""Medical expenses and their totals.

Expenses are typed in by a person, or created from the total read off an uploaded bill (see persistence.py).
Money is stored as whole minor units (paise / cents) so totals never drift, and each currency is totalled on its own:
adding rupees to dollars would give a meaningless number.

Access is enforced centrally in auth.guard from the URL (patient_id / expense_id): viewers read, editors write.
Audit entries hold ids and actions only - never descriptions or amounts.
"""
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

import auth
from database import Expense, MedicalDocument, User, get_db
from schedule_routes import _check_date

router = APIRouter()

Currency = Literal["INR", "USD", "EUR", "GBP"]
Category = Literal["consultation", "medicine", "lab_test", "hospital", "insurance", "other"]


class ExpenseIn(BaseModel):
    expense_date: str
    description: str = Field(min_length=1, max_length=200)
    amount: Decimal = Field(gt=0, le=100_000_000, decimal_places=2)
    currency: Currency
    category: Category = "other"

    @field_validator("expense_date")
    @classmethod
    def _date(cls, v):
        return _check_date(v)

    @field_validator("description")
    @classmethod
    def _description(cls, v):
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


def totals_by_currency(rows) -> list[dict]:
    """One total per currency. `unverified` is the part read from bills that nobody has checked yet."""
    out: dict[str, dict] = {}
    for expense, status in rows:
        t = out.setdefault(expense.currency, {"currency": expense.currency, "total": 0, "unverified": 0, "count": 0})
        t["total"] += expense.amount_minor
        t["count"] += 1
        if status == "pending_review":
            t["unverified"] += expense.amount_minor
    return [{**t, "total": t["total"] / 100, "unverified": t["unverified"] / 100} for _, t in sorted(out.items())]


def expense_rows(db: Session, patient_id: int):
    """(Expense, validation_status of its source document, or None when typed in by hand), newest first."""
    return (db.query(Expense, MedicalDocument.validation_status)
            .outerjoin(MedicalDocument, MedicalDocument.id == Expense.document_id)
            .filter(Expense.patient_id == patient_id)
            .order_by(Expense.expense_date.desc(), Expense.id.desc()).all())


def _out(e: Expense, status: str | None) -> dict:
    return {"id": e.id, "expense_date": e.expense_date, "description": e.description, "amount": e.amount_minor / 100,
            "currency": e.currency, "category": e.category, "document_id": e.document_id,
            "unverified": status == "pending_review"}


@router.get("/api/patients/{patient_id}/expenses")
def list_expenses(patient_id: int, db: Session = Depends(get_db)):
    rows = expense_rows(db, patient_id)
    return {"totals": totals_by_currency(rows), "items": [_out(e, s) for e, s in rows]}


@router.post("/api/patients/{patient_id}/expenses", status_code=201)
def create_expense(patient_id: int, body: ExpenseIn, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    e = Expense(patient_id=patient_id, created_by=user.id, expense_date=body.expense_date,
                description=body.description, amount_minor=int(body.amount * 100), currency=body.currency,
                category=body.category)
    db.add(e)
    db.commit()
    auth.audit(db, request, user.id, patient_id, "expense_created", f"expense {e.id}")
    return _out(e, None)


@router.delete("/api/expenses/{expense_id}", status_code=204)
def delete_expense(expense_id: int, request: Request, db: Session = Depends(get_db),
                   user: User = Depends(auth.current_user)):
    e = db.get(Expense, expense_id)
    if e is None:
        raise HTTPException(404, "Not found")
    pid = e.patient_id
    db.delete(e)
    db.commit()
    auth.audit(db, request, user.id, pid, "expense_deleted", f"expense {expense_id}")
