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
* [x] **Orders**: Tier/bulk discounts, all-or-nothing stock reservation, and status transitions (pay/cancel).
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

### Concurrency & Data Integrity: Two-Layer Defense for Unique Constraints and Inventory Invariants
Across entity creation services (`POST /books` for `isbn`, `POST /members` for `email`, and `POST /orders` for inventory stock), naive application-level pre-checks are susceptible to **Time-Of-Check to Time-Of-Use (TOCTOU)** race conditions if concurrent requests arrive simultaneously:
1. **Unique Constraints (`isbn`, `email`)**: Two simultaneous registration requests both observe that an identifier is available, and both attempt to insert. Without defensive handling, the second request triggers a database error, resulting in an unhandled 500 crash.
2. **Inventory Stock Invariant (Overselling Race Condition)**: When two buyers purchase the last available copy of a book at the exact same millisecond, both threads pass the Python pre-check (`book.stock >= item.quantity`). Both attempt to decrement stock and commit, leading to negative inventory and oversold books.

**Generalized Solution**:
We established a uniform two-layer defense across all mutations (`app/services/books.py`, `app/services/members.py`, `app/services/orders.py`, and `app/models.py`):
1. **Layer 1: Fast Python Pre-Check**:
   - `db.scalar(...)` catches duplicates under normal traffic without exception overhead.
   - `if book.stock < item.quantity: raise HTTPException(409)` guarantees all-or-nothing stock evaluation before any mutation begins.
2. **Layer 2: Database ACID Safety Net**:
   - Unique constraints (`unique=True` on `books.isbn` and `members.email`).
   - Check constraints (`CheckConstraint("stock >= 0", name="check_stock_non_negative")` on `books.stock`).
   - Wrapping `db.commit()` in a `try...except IntegrityError` block with `db.rollback()`. If a concurrent collision occurs at the database engine level (duplicate key or attempt to push stock below 0), the session state is cleanly rolled back and an `HTTPException(status_code=409, detail="...")` is returned.
* This guarantees absolute data integrity, zero overselling, and clean HTTP 409 responses under high concurrent load.

### Database-Level Aggregation vs. In-Memory Pagination
When implementing `list_books` pagination, calculating `total` (the total count of matching books before slicing) poses an architectural choice:
* **In-Memory Counting (`len(all_books)`)**: Simpler to write, but requires fetching every column of every matching row into Python memory. In a production catalog with hundreds of thousands of books, this causes severe $O(N)$ memory bloat, high network I/O, and CPU pressure on every request.
* **Database-Side Aggregation (`select(func.count()).select_from(query.subquery())`)**: We delegate row counting directly to SQLite's optimized C engine. The database computes the count internally and returns a single 4-byte integer ($O(1)$ memory).
* **Benefit**: Combined with SQL-level `.limit(limit).offset(offset)`, this architecture guarantees that the application maintains a constant, predictable $O(\text{page\_size})$ memory footprint regardless of whether the store has 50 books or 500,000 books.

### In-Memory Duplicate Detection: Hash Set vs. Linear and Nested Scans
When validating incoming order payloads (`OrderCreate.items`), duplicate `book_id`s must be rejected with HTTP 422. Several algorithmic options were considered:
* **Nested Loops / Brute Force ($O(N^2)$ time, $O(1)$ space)**: Compares every item against every subsequent item. While it uses zero additional memory, CPU time degrades quadratically as line items scale.
* **Linear List Scan (`item in seen_list`)**: Simpler to write, but list membership is $O(N)$ per element, leading to $O(N^2)$ total validation time.
* **Frequency Mapping (`collections.Counter`)**: While $O(N)$ overall, it scans the entire collection unconditionally to tally frequencies before any error check can run.
* **Hash Set Tracking (`seen_books = set()`)**:
  * Each lookup (`item.book_id in seen_books`) and insertion (`seen_books.add(...)`) operates in average $O(1)$ constant time via hash tables.
  * The total validation takes linear $O(N)$ time.
  * **Short-circuiting / Fail-Fast**: The moment a duplicate is encountered, validation immediately halts and raises a `ValueError` without parsing the rest of the payload.
* **Decision**: We chose hash-set tracking with immediate short-circuiting for optimal $O(N)$ time complexity, minimal memory overhead, and clear diagnostic error messages identifying the exact duplicate ID.

---

## 4. Spec Ambiguities & Clarifications
* **Mixed-case sorting**: As highlighted in SPEC.md, databases sort uppercase and lowercase characters differently (SQLite sorts uppercase first; Postgres default collations differ). We follow standard database ordering with secondary ID tie-breaking.

---

## 5. AI Usage
* **Tools Used:** Gemini
* **Use Cases:** Architectural review, understanding acceptance criteria, and validating edge cases (such as TOCTOU race conditions).
* **Override / Correction:** `[To be updated as development continues]`
