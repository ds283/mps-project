---
paths:
  - app/ajax/**
---

# AJAX endpoints and DataTables

## Handler selection

Both handlers are defined in `app/tools/ServerSideProcessing.py` and exported from `app/tools`.
Import via `from ..tools import ServerSideSQLHandler, ServerSideInMemoryHandler`. They are context
managers; see `app/tools/ServerSideProcessing.py` for full signatures.

- Use `ServerSideSQLHandler` where a single SQL query can satisfy all sorting, searching, and pagination
  requirements.
- Fall back to `ServerSideInMemoryHandler` only when it is not possible to build such a query.

## ServerSideSQLHandler column rules

- When adding a searchable column, always include `"search_collation": "utf8_general_ci"` so that
  searches are case-insensitive by default. Omit it only when case-sensitive matching is explicitly
  required (e.g. a hash or token field).
- Only pass actual SQLAlchemy mapped column expressions (e.g. `User.first_name`) as search targets —
  never Python `@property` accessors, which are not column expressions and will be serialised as bound
  literals, causing collation errors at runtime.
- Do not use separate "display" and "sortstring" fields in DataTables rows when `ServerSideSQLHandler`
  is used. These do not format correctly and are not needed; `ServerSideSQLHandler` handles any required
  sorting.

## Row formatters

All elements should be rendered using Jinja2 templates, not simply injected as raw strings. For
efficiency, pre-evaluate the templates in the current Jinja2 environment obtained from the current Flask
app before applying to the rows to be formatted.
