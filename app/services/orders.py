"""Order operations: placing, paying and cancelling purchases."""
from datetime import datetime
from typing import Dict

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Book, Member, MemberTier, Order, OrderItem, OrderStatus
from app.services.members import ensure_can_access_restricted
from app.schemas import OrderCreate

# Percentage discount granted by each membership tier.
TIER_DISCOUNT_PERCENT: Dict[str, int] = {
    MemberTier.APPRENTICE.value: 0,
    MemberTier.ADEPT.value: 5,
    MemberTier.MASTER.value: 10,
    MemberTier.SUPREME.value: 15,
}

# Extra discount when the total quantity across all items reaches the threshold.
BULK_QUANTITY_THRESHOLD = 10
BULK_DISCOUNT_PERCENT = 5


def calculate_discount_percent(member: Member, total_quantity: int) -> int:
    """Tier discount, plus the bulk discount when total quantity >= threshold."""
    role=member.tier
    discount=TIER_DISCOUNT_PERCENT.get(role,0)
    if total_quantity >= BULK_QUANTITY_THRESHOLD:
        discount+=BULK_DISCOUNT_PERCENT
    return discount

     


def create_order(db: Session, data: OrderCreate, now: datetime) -> Order:
    """Place a pending order and reserve stock.

    Checks, in order (422 for empty items / bad quantity / duplicate books is done by the schema):
    1. 404 member not found; 404 any book not found
    2. 403 any book restricted and member tier below master
    3. 409 any book has insufficient stock (all-or-nothing: nothing is changed)
    Then stock is decremented for every item and prices are snapshotted.
    Pricing: discount_cents = subtotal * percent // 100; total = subtotal - discount.
    """
    # TODO:
    # 1. Load the member (404) and every book (404).
    # 2. If any book is restricted, check the member's tier (403).
    # 3. Check stock for every item before changing anything (409).
    # 4. Decrement stock and build OrderItems with the current price as unit_price_cents.
    # 5. Compute subtotal, discount_percent (calculate_discount_percent), discount_cents, total.
    # 6. Save the pending Order with created_at = now and return it.
    member = db.get(Member , data.member_id)
    if member is None:
        raise HTTPException(status_code=404,detail="Member not found")
    books=[]
    for item in data.items:
        book = db.get(Book,item.book_id)
        if book is None:
            raise HTTPException(status_code=404,detail=f"Book {item.book_id} not found")
        books.append((item,book))
    for item,book in books:
        if book.restricted:
            ensure_can_access_restricted(member)
            break
    for item,book in books:
        if book.stock < item.quantity:
            raise HTTPException(status_code=409,detail="Insufficient Stock for books")
    
    order_items=[]
    total_quantity = 0
    subtotal_cents = 0
    for item,book in books:
        book.stock=book.stock-item.quantity
        this_item = OrderItem(
            book_id=book.id,
            quantity=item.quantity,
            unit_price_cents=book.price_cents,
        )
        order_items.append(this_item)
        total_quantity+=item.quantity
        subtotal_cents+=book.price_cents*item.quantity
    discount_percent=calculate_discount_percent(member,total_quantity)
    final_discounted_cents = subtotal_cents * discount_percent // 100
    total_cents = subtotal_cents - final_discounted_cents
    order=Order(
        member_id=member.id,
        status=OrderStatus.PENDING.value,
        items=order_items,
        subtotal_cents=subtotal_cents,
        discount_percent=discount_percent,
        discount_cents=final_discounted_cents,
        total_cents=total_cents,
        created_at=now,
    )
    db.add(order)
    try:
        db.commit()
        db.refresh(order)
        return order
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Insufficient stock due to concurrent purchase collision",
        )
            
    


def get_order(db: Session, order_id: int) -> Order:
    """Return an order by id, or raise 404."""
    order = db.get(Order, order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


def pay_order(db: Session, order_id: int) -> Order:
    """Mark a pending order as paid. 404 if missing; 409 if not pending."""
    order = get_order(db, order_id)
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Cannot pay an order that is {order.status}")
    order.status = OrderStatus.PAID.value
    db.commit()
    db.refresh(order)
    return order


def cancel_order(db: Session, order_id: int) -> Order:
    """Cancel a pending order and restore the reserved stock. 404 if missing; 409 if not pending."""
    order = get_order(db, order_id)
    if order.status != OrderStatus.PENDING.value:
        raise HTTPException(status_code=409, detail=f"Cannot cancel an order that is {order.status}")
    order.status = OrderStatus.CANCELLED.value
    for item in order.items:
        item.book.stock += item.quantity
    db.commit()
    db.refresh(order)
    return order
