# Project Notes: Sanctum Sanctorum Bookstore

## 1. Live Deployment
* **Live URL:** `[To be added upon deployment]`
* **Demo Member IDs to sign in with:**
  * Member ID `1`: Stephen Strange (Master tier)
  * Member ID `2`: Wong (Adept tier)

---

## 2. Implementation Status
* [x] **Book Validation & Creation**: ISBN-13 checksum validation, normalization, and duplicate prevention.
* [ ] **Book Updates & Catalogue Browsing**: `PATCH /books/{id}`, search filters, sorting, and pagination.
* [ ] **Members**: Registration, case-insensitive duplicate email handling, and tier hierarchy access rules.
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

### Concurrency & Data Integrity in Book Creation
When creating a book with `POST /books`, a simple pre-check (`db.scalar(select(Book)...)`) is susceptible to a **Time-Of-Check to Time-Of-Use (TOCTOU)** race condition if two requests attempt to insert the same ISBN simultaneously:
1. Both requests query the database at the same millisecond and see no existing book.
2. Both proceed to insert.
3. The first commit succeeds, while the second commit triggers the database-level `UNIQUE` constraint on `books.isbn`.
4. Without handling, the second request crashes with an unhandled `sqlite3.IntegrityError` (HTTP 500).

**Solution**:
We implemented optimistic concurrency protection in `app/services/books.py`:
* We perform the fast pre-check to catch duplicates early.
* We wrap `db.commit()` in a `try...except IntegrityError` block.
* If a concurrent insert collides at the database level, we immediately issue `db.rollback()` to restore connection health and raise `HTTPException(status_code=409, detail="A book with this ISBN already exists")`.
* This guarantees data integrity and prevents unhandled 500 crashes under concurrent load.

---

## 4. Spec Ambiguities & Clarifications
* **Mixed-case sorting**: As highlighted in SPEC.md, databases sort uppercase and lowercase characters differently (SQLite sorts uppercase first; Postgres default collations differ). We follow standard database ordering with secondary ID tie-breaking.

---

## 5. AI Usage
* **Tools Used:** Gemini
* **Use Cases:** Architectural review, understanding acceptance criteria, and validating edge cases (such as TOCTOU race conditions).
* **Override / Correction:** `[To be updated as development continues]`
