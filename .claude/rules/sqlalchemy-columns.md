---
paths:
  - app/models/**
  - migrations/**
---

# SQLAlchemy string columns

- `String()` columns must be declared with `collation="utf8_bin"` unless a different collation is explicitly required.
- `Text()` (and `UnicodeText()`, `MediumText()`, etc.) columns must be declared with `collation="utf8_bin"`. Without an explicit collation the column inherits the MySQL server default (currently `latin1`), which cannot store non-Latin Unicode content. Example: `db.Column(db.Text(collation="utf8_bin"))`.
- Alembic migrations must specify `collation='utf8_bin'` on every `sa.Column` of type `String`, `Text`, or similar. Do not rely on the server default.
