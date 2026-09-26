from typing import List

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Book, Order, OrderItem, OrderStatus
from app.schemas import TopBook


def top_books(db: Session, limit: int = 5) -> List[TopBook]:
    """Best-selling books.

    Rules:
    - copies_sold sums quantities over ``paid`` orders only.
    - books with no sales are excluded (handled by inner joins).
    - sorted by copies_sold desc, then title asc.
    - at most ``limit`` rows returned.
    """
    total_copies = func.sum(OrderItem.quantity).label("copies_sold")

    query = (
        select(
            Book.id.label("book_id"),
            Book.title.label("title"),
            total_copies,
        )
        .join(OrderItem, Book.id == OrderItem.book_id)
        .join(Order, Order.id == OrderItem.order_id)
        .where(Order.status == OrderStatus.PAID.value)
        .group_by(Book.id, Book.title)
        .order_by(total_copies.desc(), Book.title.asc())
        .limit(limit)
    )

    rows = db.execute(query).all()
    return [
        TopBook(
            book_id=row.book_id,
            title=row.title,
            copies_sold=int(row.copies_sold),
        )
        for row in rows
    ]
