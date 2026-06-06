
# Box token management

## Rule

All code that needs a Box SDK client **must** obtain it via `get_box_client(user)` from
`app/shared/box_api.py`.  Do **not** construct `BoxOAuth` / `BoxClient` directly, and do not
read or write `user.box_access_token`, `user.box_refresh_token`, or `user.box_token_valid`
outside of `app/shared/box_api.py`.

```python
from ..shared.box_api import get_box_client

client = get_box_client(box_user)   # proactive refresh + Redis lock included
```

To explicitly disconnect a user's Box account, use `revoke_box_auth(user)` from the same module.

## Why

`get_box_client` owns the full token lifecycle:

- Proactively refreshes tokens that are within 10 minutes of Box's 60-minute access-token expiry
  (threshold: 50 minutes since last update).
- Acquires a per-user Redis lock (`box_token_lock:{user.id}`, TTL 30 s) before refreshing, to
  prevent token-rotation races when multiple Celery workers serve the same user simultaneously.
- Wires `DBTokenStorage` into the returned `BoxClient` so any SDK-level refresh (e.g. mid-task)
  also persists the new token pair back to the database.

Building a `BoxClient` directly bypasses all of this, risking stale tokens, rotation races, and
silently lost refreshed credentials.

## Key symbols

| Symbol | Defined in | Notes |
|---|---|---|
| `get_box_client(user)` | `app/shared/box_api.py` | Returns a ready `BoxClient`; refreshes if needed |
| `revoke_box_auth(user)` | `app/shared/box_api.py` | Clears token fields and marks token invalid |
| `_do_token_refresh(user)` | `app/shared/box_api.py` | Direct HTTP refresh; called by the beat task and by `get_box_client` — do not call from views |
| `_persist_tokens(user, access, refresh)` | `app/shared/box_api.py` | Persists a token pair; private, do not call directly |

## Beat task

`app/tasks/box_tokens.maintain_box_tokens` runs daily (registered via `ensure_box_token_schedule`
in `initdb.py`) and calls `_do_token_refresh` for active users whose tokens are ≥45 days old,
well before Box's 60-day refresh-token expiry.  It also posts a lapse warning to inactive users
whose tokens are ≥55 days old.

## Auth error handling in export tasks

When a Box API call fails with an auth error (`_is_box_auth_error(exc)` returns True), post a
re-link notification via `_post_relink_notification(requesting_user)` and mark the task as
`FAILURE`.  Do not silently swallow auth errors or retry without user action.
