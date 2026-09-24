"""Library loan operations: borrowing and returning books."""
import math
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import Loan, MemberTier,Book,Member
from app.schemas import LoanCreate, LoanOut, LoanStatus
from app.services.members import ensure_can_access_restricted

# Maximum concurrent unreturned loans per tier (None = unlimited).
TIER_LOAN_LIMIT: Dict[str, Optional[int]] = {
    MemberTier.APPRENTICE.value: 1,
    MemberTier.ADEPT.value: 3,
    MemberTier.MASTER.value: 5,
    MemberTier.SUPREME.value: None,
}

LOAN_PERIOD = timedelta(days=14)
LATE_FEE_PER_DAY_CENTS = 25


def loan_status(loan: Loan, now: datetime) -> LoanStatus:
    """``returned`` if returned; else ``overdue`` if now > due_at; else ``active``."""
    if loan.returned_at is not None:
        return "returned"
    returntime=loan.due_at
    if now > returntime:
        return "overdue"
    else:
        return "active"
     
      


def to_loan_out(loan: Loan, now: datetime) -> LoanOut:
    """Serialize a loan, computing its status at read time."""
    return LoanOut(
        id=loan.id,
        member_id=loan.member_id,
        book_id=loan.book_id,
        borrowed_at=loan.borrowed_at,
        due_at=loan.due_at,
        returned_at=loan.returned_at,
        late_fee_cents=loan.late_fee_cents,
        status=loan_status(loan,now),
    )


def calculate_late_fee(due_at: datetime, returned_at: datetime, price_cents: int) -> int:
    """25 cents per started day late (any partial day counts), capped at the book's price; 0 if not late."""
    late=returned_at-due_at
    seconds_late=late.total_seconds()
    days_late=math.ceil(seconds_late/86400)
    if days_late <=0:
        return 0
    else:
        return min(days_late * LATE_FEE_PER_DAY_CENTS,price_cents)


        


def create_loan(db: Session, data: LoanCreate, now: datetime) -> LoanOut:
    """Borrow a book for 14 days.

    Checks, in order:
    1. 404 member not found; 404 book not found
    2. 403 book restricted and member tier below master
    3. 409 member has any overdue loan
    4. 409 member already has an unreturned loan of this book
    5. 409 member is at their tier's loan limit
    6. 409 book is out of stock
    On success: borrowed_at = now, due_at = now + 14 days, returned_at None,
    late_fee_cents 0, and stock is decremented by one.
    """
    member=db.get(Member,data.member_id)
    book=db.get(Book,data.book_id)
    if member is None:
        raise HTTPException(status_code=404,detail=f"Member {data.member_id} Not Found")
    if book is None:
        raise HTTPException(status_code=404,detail=f"Book {data.book_id} Not Found")
    
    if book.restricted:
        ensure_can_access_restricted(member)
    active_loans=db.scalars(select(Loan).where(Loan.member_id==member.id,Loan.returned_at.is_(None))).all()
    for loan in active_loans:
        if loan.due_at < now:
            raise HTTPException(status_code=409,detail="Member has overdue loans")
    for loan in active_loans:
        if loan.book_id == book.id:
            raise HTTPException(status_code=409,detail="Member has unreturned loan of this book")
    role=member.tier
    loan_limit=TIER_LOAN_LIMIT.get(role,0)
    if loan_limit is not None and len(active_loans) >= loan_limit:
        raise HTTPException(status_code=409, detail="Member reached tier loan limit")
    if book.stock == 0:
        raise HTTPException(status_code=409,detail="Book is Out of Stock")
    book.stock=book.stock-1
    loan=Loan(
         member_id=member.id,
         book_id=book.id,
         borrowed_at=now,
         due_at = now + LOAN_PERIOD,
         returned_at=None,
         late_fee_cents=0,
        )
    db.add(loan)
    try:
        db.commit()
        db.refresh(loan)
        return to_loan_out(loan, now)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="Book was borrowed concurrently or stock exhausted"
        )
     


def get_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    """Return a loan by id, or raise 404."""
    loan=db.get(Loan,loan_id)
    if loan is None:
        raise HTTPException(status_code=404,detail="Loan not found")
    return to_loan_out(loan,now)


def return_loan(db: Session, loan_id: int, now: datetime) -> LoanOut:
    """Return a borrowed book.

    Rules: 404 if missing; 409 if already returned. Sets returned_at = now, restores one copy
    of stock and charges a late fee (see ``calculate_late_fee``).
    """
    loan=db.get(Loan,loan_id)
    if loan is None:
        raise HTTPException(status_code=404,detail="Loan not found")
    if loan.returned_at is not None:
        raise HTTPException(status_code=409,detail="Book has been returned already")
    loan.returned_at=now
    book=loan.book
    book.stock+=1
    loan.late_fee_cents=calculate_late_fee(loan.due_at,now,book.price_cents)
    db.commit()
    db.refresh(loan)
    return to_loan_out(loan,now)
    


def list_member_loans(
    db: Session, member_id: int, now: datetime, status: Optional[LoanStatus] = None
) -> List[LoanOut]:
    """A member's loans ordered by id, optionally filtered by computed status; 404 if member missing."""
    member=db.get(Member,member_id)
    if member is None:
        raise HTTPException(status_code=404,detail="Member not found")
    loans=member.loans
    out=[]
    for loan in loans:
        loan_out=to_loan_out(loan,now)
        if status is None or loan_out.status == status:
            out.append(loan_out)
    return out
