# Project Notes: Sanctum Sanctorum Bookstore

## 1. Live Deployment
* **Live URL:** `[To be added upon deployment]`
* **Demo Member IDs to sign in with:**
  * Member ID `1`: Stephen Strange (Master tier)
  * Member ID `2`: Wong (Adept tier)

---

## 2. Implementation Status
* [x] **Book Validation & Creation**: ISBN-13 checksum validation, normalization, and duplicate prevention.
* [x] **Book Updates & Catalogue Browsing**: `PATCH /books/{id}`, search filters, sorting, and pagination.
* [x] **Members**: Registration, case-insensitive duplicate email handling, and tier hierarchy access rules.
* [ ] **Orders**: Tier/bulk discounts, all-or-nothing stock reservation, and status transitions (pay/cancel).
* [ ] **Loans**: ORM model completion, loan limits, due dates, returns, and late fee calculation.
* [ ] **Reports & Stats**: Top books report and member activity summaries.

---

## 3. Architectural Decisions & Trade-offs

### Clean Layering & Separation of Concerns
We strictly adhered to the layered architecture specified in the assignment:
* **Routers (`app/routers/`)**: Kept as thin HTTP controllers that only parse incoming requests, inject dependencies (e.g. `db`, `now`), call the corresponding service functions, and return responses.
* **Schemas (`app/schemas.py`)**: Built on Pydantic v2 to encapsulate all input validation (e.g. whitespace trimming, string length bounds, ISBN-13 checksums) before any business logic or database queries execute. Invalid inputs fail fast with HTTP 422.
* **Services (`app/services/`)**: Centralize all business logic and domain rules, keeping the code testable, maintainable, and decoupled from the transport layer.
* **Models (`app/models.py`)**: Standard SQLAlchemy 2.0 mapped models representing persistent database tables.

### Concurrency & Data Integrity: Two-Layer Defense for Unique Constraints
Across both entity creation services (`POST /books` for `isbn` and `POST /members` for `email`), a naive pre-check (`db.scalar(select(...))`) is susceptible to a **Time-Of-Check to Time-Of-Use (TOCTOU)** race condition if two concurrent requests attempt to insert the same unique identifier simultaneously:
1. Both requests query the database at the same millisecond and see no existing record.
2. Both proceed to insert.
3. The first commit succeeds, while the second commit triggers the database-level `UNIQUE` constraint (`books.isbn` or `members.email`).
4. Without handling, the second request crashes with an unhandled `sqlite3.IntegrityError` (resulting in a 500 Internal Server Error).

**Generalized Solution**:
We established a uniform two-layer defense across all creation services (`app/services/books.py` and `app/services/members.py`):
1. **Fast Pre-Check**: A preliminary `select(...).where(...)` catches duplicates under normal traffic without incurring the cost of an exception.
2. **ACID Safety Net**: We wrap `db.commit()` in a `try...except IntegrityError` block. If a concurrent collision occurs at the database engine level, we immediately issue `db.rollback()` to cleanly restore the session state and raise `HTTPException(status_code=409, detail="...")`.
* This guarantees absolute data integrity, connection health, and clean HTTP 409 responses under high concurrent load.

### Database-Level Aggregation vs. In-Memory Pagination
When implementing `list_books` pagination, calculating `total` (the total count of matching books before slicing) poses an architectural choice:
* **In-Memory Counting (`len(all_books)`)**: Simpler to write, but requires fetching every column of every matching row into Python memory. In a production catalog with hundreds of thousands of books, this causes severe $O(N)$ memory bloat, high network I/O, and CPU pressure on every request.
* **Database-Side Aggregation (`select(func.count()).select_from(query.subquery())`)**: We delegate row counting directly to SQLite's optimized C engine. The database computes the count internally and returns a single 4-byte integer ($O(1)$ memory).
* **Benefit**: Combined with SQL-level `.limit(limit).offset(offset)`, this architecture guarantees that the application maintains a constant, predictable $O(\text{page\_size})$ memory footprint regardless of whether the store has 50 books or 500,000 books.

---

## 4. Spec Ambiguities & Clarifications
* **Mixed-case sorting**: As highlighted in SPEC.md, databases sort uppercase and lowercase characters differently (SQLite sorts uppercase first; Postgres default collations differ). We follow standard database ordering with secondary ID tie-breaking.

---

## 5. AI Usage
* **Tools Used:** Gemini
* **Use Cases:** Architectural review, understanding acceptance criteria, and validating edge cases (such as TOCTOU race conditions).
* **Override / Correction:** `[To be updated as development continues]`
