# Implement Box OAuth2 token refresh model

## Context

The `User` model (`app/models/users.py`) holds Box OAuth2 credentials:

```python
box_access_token  # EncryptedType, nullable
box_refresh_token  # EncryptedType, nullable
box_token_valid  # Boolean, default False
box_updated_at  # DateTime, onupdate=datetime.now
```

`User` also has `last_active` (DateTime), updated by the keep-alive ping mechanism.

Box access tokens expire after 60 minutes. Refresh tokens expire after 60 days and rotate
on every use (Box issues a new refresh token alongside each new access token).

The intended token lifecycle is:

- Users who are active in the app regularly should have their Box token silently kept alive
  by a proactive background refresh, even if they haven't touched the Box feature recently.
- Users who are genuinely inactive (not logged in at all) should be allowed to lapse
  naturally, and must re-authenticate when they next need Box access.
- The lazy `get_box_client()` helper handles per-call refresh with a Redis lock to
  prevent token-rotation races between concurrent requests.

## Files to read before writing any code

```
app/models/users.py                   # User model — Box fields, last_active, post_message()
app/tasks/canvas.py                   # Pattern for existing Celery tasks in this app
app/tasks/__init__.py                 # Beat schedule registration pattern
app/extensions.py                     # How Redis client is accessed (current_app.extensions or similar)
app/config.py                         # Config key naming conventions; BOX_CLIENT_ID etc. if present
```

Grep for the following before writing to confirm naming:

```bash
grep -r "extensions\[.redis.\]" app/ --include="*.py" -l
grep -r "BOX_CLIENT" app/ --include="*.py"
grep -r "celery_beat_schedule\|beat_schedule\|add_periodic_task" app/ --include="*.py" -l
grep -r "apply_async.*queue=" app/tasks/ --include="*.py" | head -20
```

## Work to be done

### 1. New module: `app/shared/box_api.py`

Create this file. It must contain:

#### `get_box_client(user) -> boxsdk.Client`

Returns a valid Box SDK client for `user`, performing a lazy token refresh if needed.

Logic:

1. Compute `needs_refresh`:
    - `not user.box_token_valid`, OR
    - `user.box_updated_at is None`, OR
    - `datetime.now() - user.box_updated_at > timedelta(minutes=50)`
      (50-minute threshold gives 10-minute margin before Box's 60-minute expiry)

2. If `needs_refresh`:
    - Acquire a per-user Redis lock: key `box_token_lock:{user.id}`, TTL 30 seconds, `nx=True`
    - Under the lock, call `db.session.refresh(user)` and re-evaluate `needs_refresh`
      (another worker may have refreshed between the check and the lock acquisition)
    - If still needed, call `_do_token_refresh(user)`
    - Release lock (use a `try/finally` block)

3. Construct and return a `boxsdk.OAuth2` + `boxsdk.Client` using the current token values,
   with `store_tokens` wired to `_persist_tokens(user, access, refresh)` so that
   any in-flight SDK refresh also persists correctly.

#### `_do_token_refresh(user)`

Private helper. Calls the Box token endpoint directly:

```
POST https://api.box.com/oauth2/token
grant_type=refresh_token
refresh_token=<user.box_refresh_token>
client_id=<BOX_CLIENT_ID from config>
client_secret=<BOX_CLIENT_SECRET from config>
```

On HTTP error: set `user.box_token_valid = False`, commit, and re-raise so the caller
can handle it (do not silently swallow the exception).

On success: call `_persist_tokens(user, data["access_token"], data["refresh_token"])`.

Use `requests.post(..., timeout=10)`.

#### `_persist_tokens(user, access_token, refresh_token)`

Private helper. Sets:

```python
user.box_access_token = access_token
user.box_refresh_token = refresh_token
user.box_token_valid = True
# box_updated_at is handled by onupdate= on the column
db.session.commit()
```

This function is also passed as `store_tokens` to `boxsdk.OAuth2`, so it must accept
exactly two positional arguments (access_token, refresh_token) in addition to any
closure-captured `user`. Use a lambda or `functools.partial` at the call site:

```python
store_tokens = lambda a, r: _persist_tokens(user, a, r)
```

#### `revoke_box_auth(user)`

Public helper. Sets `user.box_token_valid = False`, clears both token fields to `None`,
commits. Called from the account settings view when a user explicitly disconnects Box.

---

### 2. New Celery task: `app/tasks/box_tokens.py`

Create this file with a single task:

#### `app.tasks.box_tokens.maintain_box_tokens`

This is a **beat task** — do not call it manually from views.

Logic:

```python
from datetime import datetime, timedelta
from app import db
from app.models import User

PROACTIVE_REFRESH_THRESHOLD = timedelta(days=45)  # refresh if token older than 45 days
ACTIVE_WITHIN = timedelta(days=7)  # only refresh if user was active this recently
LAPSE_THRESHOLD = timedelta(days=55)  # warn users whose token is about to expire
```

Query 1 — **proactive refresh**: users who are active in the app but whose Box token
is getting stale:

```python
User.box_token_valid == True
AND
user.box_updated_at < datetime.now() - PROACTIVE_REFRESH_THRESHOLD
AND
user.last_active > datetime.now() - ACTIVE_WITHIN
```

For each such user: call `_do_token_refresh(user)` imported from `app.box_api`.
Wrap each individual user refresh in a `try/except` and log errors without aborting
the rest of the batch. Log a single summary line at INFO level after the loop:
`"Box token proactive refresh: {n_ok} refreshed, {n_err} errors"`.

Query 2 — **lapse warning**: users whose token is near the 60-day hard expiry but who
have _not_ been active recently (i.e. they won't be caught by the proactive refresh):

```python
User.box_token_valid == True
AND
user.box_updated_at < datetime.now() - LAPSE_THRESHOLD
AND(user.last_active
IS
NULL
OR
user.last_active < datetime.now() - ACTIVE_WITHIN)
```

For each such user: call `user.post_message(...)` with a `"warning"` class message:
`"Your Box connection will expire soon. Please visit your account settings to re-authenticate."`
Set `autocommit=True`.

Do not attempt a token refresh for this group — they are inactive and the token
should lapse naturally.

Task registration: use `@celery.task(name="app.tasks.box_tokens.maintain_box_tokens")`.
Match the decorator style used in `app/tasks/canvas.py` or whichever existing task file
is the best pattern match.

---

### 3. Register the beat schedule

In whichever file the Celery beat schedule is defined (confirm via grep above), add an
entry to run `app.tasks.box_tokens.maintain_box_tokens` once daily. Match the existing
schedule entry format precisely — do not introduce a new style.

Suggested schedule key: `"box-token-maintenance"`, interval: every 24 hours,
queue: `"default"` (or whichever low-priority queue existing beat tasks use — confirm
from grep output).

---

### 4. Config keys

If `BOX_CLIENT_ID` and `BOX_CLIENT_SECRET` are not already present in `app/config.py`,
add them with `None` defaults and read from environment variables:

```python
BOX_CLIENT_ID = os.environ.get("BOX_CLIENT_ID", None)
BOX_CLIENT_SECRET = os.environ.get("BOX_CLIENT_SECRET", None)
```

Do not add to `.env` or any secrets file — leave a `# TODO: set in environment` comment.

---

## Out of scope for this prompt

- The Box OAuth2 callback/authorisation flow (connecting a Box account for the first time)
- The `revoke_box_auth` view wiring (just implement the helper function in `box_api.py`)
- Any UI changes
- `boxsdk` installation — assume it is already present or will be added separately

---

## Verification steps

After implementation, run the following to confirm correctness:

```bash
# 1. Module is importable
python -c "from app.box_api import get_box_client, revoke_box_auth; print('OK')"

# 2. Task is registered
python -c "
from app import create_app
app = create_app()
with app.app_context():
    from app import celery
    print('maintain_box_tokens' in celery.tasks or 'app.tasks.box_tokens.maintain_box_tokens' in celery.tasks)
"

# 3. Beat schedule contains the new entry
python -c "
from app import create_app
app = create_app()
with app.app_context():
    from app import celery
    print([k for k in celery.conf.beat_schedule if 'box' in k.lower()])
"

# 4. No import errors in tasks module
python -c "import app.tasks.box_tokens; print('OK')"
```