# Cloud Storage Provider — Reconnaissance

*Prepared 2026-06-22. This document is intended to give a future Claude instance enough
context to reason about designing a two-layer `CloudStorageProvider` /
`CloudStorageLocation` abstraction for MPS-Project.*

---

## 1. Motivation

`app/tasks/box_export_period_marking.py` exports student reports and a marking-summary
spreadsheet from a `SubmissionPeriodRecord` to a Box folder. The task is hard-wired to Box.
The goal is a two-layer abstraction — analogous to the existing `Driver` / `ObjectStore`
split for internal buckets — so that:

- The export task talks to a `CloudStorageLocation` (the facade), never to a provider
  directly.
- The Box driver is one `CloudStorageProvider` implementation; other drivers (Google Drive,
  OneDrive, SharePoint, …) can be added without touching task code.
- Configured destinations (for the backup infrastructure) are expressed as
  `CloudStorageLocation` instances in `instance/local.py`, mirroring how `ObjectStore`
  buckets are configured today.
- A future **bucket-backup** feature (periodic ObjectStore → cloud, user-initiated cloud →
  ObjectStore restore) can reuse the same abstraction.
- API calls are instrumented at the location layer, providing an audit trail without
  coupling task code to logging concerns.

---

## 2. Existing ObjectStore abstraction (the model to follow)

The `cloud_object_store` package uses a two-layer pattern: a `Driver` ABC for raw provider
operations, and an `ObjectStore` facade that adds cross-cutting concerns (encryption,
compression, audit) on top. The new `cloud_storage` package mirrors this exactly:

| `cloud_object_store` | `cloud_storage` | Role |
|----------------------|-----------------|------|
| `Driver` | `CloudStorageProvider` | Raw provider operations; one concrete class per backend |
| `ObjectStore` | `CloudStorageLocation` | Facade: holds `(provider, root_ref)`, adds audit layer |
| `_drivers` registry | `_providers` registry | Maps name string → provider class |

Task code uses `CloudStorageLocation` exclusively. `CloudStorageProvider` is an
implementation detail, never referenced directly outside `cloud_storage/`.

### Location
`app/shared/cloud_object_store/` — the canonical internal-bucket abstraction.

### Key classes

#### `Driver` (abstract base, `base.py:85–154`)
Concrete drivers implement this interface:
```python
class Driver:
    def __init__(self, uri: SplitResult, data: Dict): ...
    def get_driver_name(self) -> str: ...
    def get_bucket_name(self) -> str: ...
    def get_host_uri(self) -> str: ...
    def get(self, key: PathLike) -> bytes: ...
    def get_range(self, key: PathLike, start: int, length: int) -> BytesLike: ...
    def put(self, key: PathLike, data: BytesLike, mimetype: Optional[str] = None) -> None: ...
    def delete(self, key: PathLike) -> None: ...
    def list(self, prefix: Optional[PathLike] = None) -> Dict[str, ObjectMeta]: ...
    def list_keys(self, prefix: Optional[PathLike] = None) -> Set[str]: ...
    def copy(self, src: PathLike, dst: PathLike) -> None: ...
    def head(self, key: PathLike) -> ObjectMeta: ...
    def get_url(self, key: PathLike) -> str: ...
    def ping(self) -> None: ...
```

#### `ObjectStore` (facade, `base.py:157–462`)
Constructed with `(uri: PathLike, database_key: int, data: Dict)`.
Adds transparent encryption/compression on top of the driver. Exposes the same `get / put /
delete / list / copy / head / get_url / ping` surface with an additional `audit_data: str`
parameter on every mutating call.

#### Driver registry (`base.py:25–29`)
```python
_drivers = {
    "file": LocalFileSystemDriver,
    "gs":   GoogleCloudStorageDriver,
    "s3":   AmazonS3CloudStorageDriver,
}
```
Scheme in the URI selects the driver. Adding a new driver = add one entry.

#### Concrete drivers
| Scheme | Class | File |
|--------|-------|------|
| `file` | `LocalFileSystemDriver` | `drivers/local.py` |
| `gs`   | `GoogleCloudStorageDriver` | `drivers/google.py` |
| `s3`   | `AmazonS3CloudStorageDriver` | `drivers/amazons3.py` |

### Configuration pattern
Each bucket is configured in `instance/local.py` (or the equivalent env config) as:
```python
OBJECT_STORAGE_ASSETS = ObjectStore(
    uri="s3://bucket-name",
    database_key=BucketTypes.ASSETS,
    data={
        "access_key": "...",
        "secret_key": "...",
        "endpoint_url": "...",   # optional for non-AWS S3
        "compression": True,
        "audit": {"backend": "mongodb", ...},
        "encryption_pipeline": ...,
    }
)
```
`database_key` is an integer from `app/shared/cloud_object_store/bucket_types.py` that
identifies the bucket in the audit log.

### `AssetCloudAdapter` (`app/shared/asset_tools.py:58–259`)
Wraps an ORM asset and an `ObjectStore` instance. Provides `.get()`, `.delete()`,
`.duplicate()`, `.exists()`, `.stream()`, `.download_to_scratch()`. Used by
`box_export_period_marking` to download student reports before re-uploading to Box:
```python
file_bytes = AssetCloudAdapter(
    asset=asset,
    storage=object_store,
    audit_data="box_export_period_marking.upload_report",
).get()
```

---

## 3. Current Box integration

### Token management (`app/shared/box_api.py`)

All Box API access flows through one function: `get_box_client(user: User) → BoxClient`.
**Nothing else should construct a BoxClient or touch Box token fields on the User model.**

Key internals:
- `_REFRESH_THRESHOLD = timedelta(minutes=50)` — proactive refresh before Box's 60-minute
  access-token expiry.
- A per-user Redis lock (`box_token_lock:{user.id}`, TTL 30 s) prevents concurrent token
  rotations from multiple Celery workers.
- `DBTokenStorage` (dynamically-created class) implements the `box_sdk_gen.TokenStorage`
  interface, persisting refreshed tokens back to the User row during mid-task SDK-level
  refreshes.
- `_do_token_refresh(user)` performs a direct HTTP `POST /oauth2/token` call using the
  stored refresh token; sets `box_token_valid = False` if Box returns a 400.
- A daily Celery beat task (`app/tasks/box_tokens.maintain_box_tokens`) proactively
  refreshes tokens ≥ 45 days old and posts lapse warnings at ≥ 55 days (before Box's
  60-day refresh-token expiry).

### User model fields (`app/models/users.py:183–212`)
All encrypted at rest with AesGcmEngine:
```python
box_access_token  = EncryptedType(String, ...)   # nullable
box_refresh_token = EncryptedType(String, ...)   # nullable
box_token_valid   = Boolean(default=False)       # False until OAuth flow completes
box_updated_at    = DateTime(onupdate=datetime.now)
```
No other OAuth provider fields currently exist on the User model.

### OAuth2 flow (`app/oauth2/views.py`)
Blueprint `oauth2` at `/oauth2/`.
- `GET /oauth2/box` (`box_login`) — generates CSRF state token, stores in session, redirects
  to Box authorisation URL. Accepts `?next=<safe_relative_url>` for post-auth redirect.
- `GET /oauth2/box-callback` (`box_callback`) — validates state, exchanges code for tokens,
  writes tokens directly to `current_user.box_*` fields, commits. Redirects to `next` or
  home dashboard.

### Export task (`app/tasks/box_export_period_marking.py`)
Registered as:
```python
"app.tasks.box_export_period_marking.box_export_period_marking"
```
Signature:
```python
def box_export_period_marking(
    self,
    period_id: int,           # SubmissionPeriodRecord to export
    box_user_id: int,         # User whose Box OAuth tokens to use
    requesting_user_id: int,  # User receiving completion notification
    folder_id: str,           # Box folder ID (numeric string)
    task_id: str,             # TaskRecord UUID for progress tracking
)
```
Steps executed:
1. Load DB records (period, box_user, requesting_user).
2. Call `get_box_client(box_user)`.
3. `_build_in_scope_records(period)` — SubmissionRecords not DROPPED everywhere.
4. Create Box subfolder named after the ProjectClass abbreviation; create "Reports" sub-subfolder.
5. For each in-scope record: download report via `AssetCloudAdapter.get()`, upload to Box via
   `_upsert_file(client, reports_folder_id, filename, data)`, obtain shared link via
   `_get_shared_link(client, file_id)`.
6. Build anonymised Excel workbook (`_build_excel`) including Box shared-link URLs.
7. Upload Excel to Box project subfolder.
8. Post completion notification to `requesting_user`.

Auth error handling: `_is_box_auth_error(exc)` detects 400 invalid_grant / 401 errors from
the SDK; when triggered, `_post_relink_notification(requesting_user)` sends a message with a
link to `/oauth2/box` and the task fails.

### Export trigger view (`app/convenor/markingevent.py:3386–3503`)
Route: `GET/POST /convenor/export_period_to_box/<period_id>`

Workflow:
1. Collect convenors + co-convenors where `user.box_token_valid == True` → `candidates`.
2. If none, render page with `ConvenorAction` warning banner (no form).
3. Otherwise render `ExportPeriodToBoxFormFactory(candidates)` form.
4. On POST: call `register_task(...)` → get `task_id`, call `export_task.apply_async(...)`.

### Export form (`app/convenor/forms.py:1792–1818`)
Factory function `ExportPeriodToBoxFormFactory(box_users: list)` builds:
```python
class ExportPeriodToBoxForm(Form):
    box_user    = QuerySelectField(...)   # Select from users with box_token_valid == True
    box_folder_id = StringField(...)      # Regex: r"^\d+$"
    submit      = SubmitField("Export…")
```

---

## 4. What a CloudStorageProvider abstraction needs to capture

### 4.1 Provider-agnostic file operations

The operations used by the export task map to a small interface:

| Operation | Box helper used | Purpose |
|-----------|-----------------|---------|
| Create folder | `_get_or_create_subfolder(client, parent_id, name)` | Idempotent mkdir |
| Upload file | `_upsert_file(client, folder_id, filename, data, mimetype)` | Insert or version-replace |
| Get shareable URL | `_get_shared_link(client, file_id)` | Obtain public/shared link |
| List folder contents | `_get_folder_items(client, folder_id)` | Enumerate files/folders |
| Find file in folder | `_find_file_in_folder(client, folder_id, filename)` | Existence check |

For the planned **bucket backup** feature, one additional operation is needed:
- **Download** a specific file by its provider ref (not currently in `box_export`, but
  needed for restore). This is a direct API call using the file's opaque identifier — not
  a shareable URL fetch.

Where `folder_ref` and `file_ref` are opaque provider-specific identifiers (strings for Box
folder/file IDs; paths for other backends).

**Upload idempotency must be explicit in the contract.** `_upsert_file` inserts a new file
if `filename` is absent from the folder, or creates a new version on Box if it already
exists (idempotent re-runs, preserving file IDs and shared links). Provider implementations
must honour this semantic: re-uploading the same filename must not create a duplicate entry.

### 4.2 Shareable URLs and direct downloads

The export task uses `_get_shared_link` to obtain a URL per uploaded report, then embeds
those URLs in the Excel summary for external examiners. This is a human-readable,
browser-accessible link — not an API download call.

The backup restore feature will need to **download file content** programmatically. This
must be done via a direct API call (e.g. Box `/files/{id}/content`) using the stored
`file_ref`, not by fetching a shareable URL. The two are distinct operations serving
different use cases:

- `get_shareable_url(file_ref, access)` — returns a human-readable link for embedding in
  documents. Some providers may not support this (e.g. a corporate SharePoint with no
  external sharing). Returns `Optional[str]`.
- `download_file(file_ref)` — fetches file content via the provider API using the stored
  credential. Always available if `file_ref` is valid.

`CloudItem` (returned by `list_folder`) may optionally carry a `url` field. Box can return
a download URL or shared link at list time, avoiding a separate round-trip. Other providers
may not support this. The field is `Optional[str]`; callers must always be prepared to fall
back to `get_shareable_url(item.ref)` when `item.url is None`.

### 4.3 OAuth identity binding

The current Box flow binds exactly one OAuth identity (one Box account) to one User row.
The provider abstraction needs to support:
- Multiple providers, each with their own OAuth tokens on the User model.
- Possibly multiple accounts per provider (e.g. personal OneDrive + work SharePoint).
- Periodic/headless tasks (backup) that must obtain a client without user interaction — the
  client must be constructable from persisted tokens alone.
- User-initiated tasks (export) that obtain a client via a selected User's tokens.

Current Box implementation stores tokens directly in scalar columns on `User`. A more general
design should treat each provider's token set as a separate related model
(`UserCloudStorageToken` with `provider`, `access_token`, `refresh_token`, `token_valid`,
`updated_at`), allowing multiple providers without adding columns for each.

However, since the project currently has only Box, the minimal migration path is:
- Keep `box_*` fields on User as-is.
- Introduce a thin `CloudStorageProvider` ABC.
- Add a `BoxCloudStorageProvider` that wraps `get_box_client(user)`.
- Add future providers alongside without changing task code.

**Phase 1 scope (current work):** The `CloudStorageProvider` ABC abstracts file operations
only — not token storage. Box tokens remain as scalar columns on `User`; `from_user` calls
`get_box_client(user)` as before. Token storage generalisation (`UserCloudStorageToken`
table, changes to the OAuth flow) is a Phase 2 concern and is explicitly out of scope here.

### 4.4 Token maintenance tasks are out of scope for the abstraction

`maintain_box_tokens` (`app/tasks/box_tokens.py`) is inherently Box-specific: it knows
about `User.box_updated_at`, Box's 60-day refresh-token expiry, and the 45/55-day warning
cadence. A future `maintain_gdrive_tokens` would have entirely different rotation cadences
and different User fields. Token maintenance tasks are **not** abstracted by
`CloudStorageProvider` — each provider gets its own beat task. The ABC does not need a
`refresh_tokens_for_all_users()` method or similar.

### 4.5 CloudStorageLocation: the facade layer

`CloudStorageLocation` is what task code constructs and calls. It holds a
`(provider: CloudStorageProvider, root_ref: str)` pair and adds the audit layer. It is
**not** an ABC — there is one concrete class, and provider variation is achieved by
swapping the provider inside it.

**Construction — two modes, mirroring `from_user` / `from_config` on the provider:**

```python
# User-delegated (export task): constructed at dispatch time from form data
location = CloudStorageLocation.from_user(
    provider_name="box",
    user=box_user,
    root_ref=form.box_folder_id.data.strip(),
    audit_data="export_period_marking",
)

# Server-delegated (backup task): constructed from instance config
CLOUD_STORAGE_BACKUP = CloudStorageLocation(
    provider_name="box",
    root_ref="123456789",      # Box folder ID of the backup root
    data={
        "auth": "server",      # constructs provider via from_config, not from_user
        "audit": {"backend": "mongodb", ...},
    },
)
```

**Root-relative folder resolution:** `get_or_create_folder(parent_ref=None, name=...)` is
interpreted as "create this folder directly under `root_ref`". This keeps task code
root-agnostic — the export task and the backup task use the same call pattern regardless
of where their respective roots sit in the provider's namespace.

**Audit layer:** Every mutating call emits a structured audit record before and after
execution. Audited operations: `get_or_create_folder`, `upsert_file`, `download_file`,
`delete_file`. Non-mutating operations (`list_folder`, `get_shareable_url`) are not
audited. Each record captures: timestamp, provider name, operation, folder/file ref,
filename (where applicable), byte count (where applicable), duration (ms), success/failure,
and the `audit_data` tag supplied at construction time. MongoDB is the audit backend,
consistent with `ObjectStore`.

**The location does not re-expose `is_auth_error` or `reauth_url`.** These are
provider-specific error-handling concerns that bubble up through exceptions; the task
catches them and calls `provider.reauth_url()` via `location.provider` if needed.
Alternatively, the location can expose a `handle_auth_error(exc, notify_user)` convenience
that encapsulates the check-and-notify pattern currently repeated three times in
`box_export_period_marking`.

### 4.6 Target location UI

The export form currently has two Box-specific fields:
- **Account selector** — `QuerySelectField` over users with `box_token_valid == True`.
- **Folder ID** — raw numeric string typed by the user.

For a provider-agnostic UI, the "upload sheet" needs to be parameterised by provider:
- The account selector becomes a selector over provider-specific linked accounts.
- The destination picker is provider-specific: Box uses a folder ID; Google Drive might use a
  folder URL or picker widget; S3 uses a bucket name + prefix.

The cleanest approach is a **provider-specific destination fragment**: the form factory
takes a provider type and renders the appropriate destination field(s) for that provider.
The task receives an opaque `destination` dict that the provider driver knows how to
interpret (e.g. `{"folder_id": "123456789"}` for Box).

### 4.7 Backup-specific requirements

The planned bucket-backup feature (out of scope for the current session, but the abstraction
must accommodate it) requires:
- **Periodic sync (ObjectStore → cloud)**: Celery beat task; no user involved. Needs a
  pre-configured provider identity (likely a service-account or long-lived token) rather than
  a per-user token.
- **Restore sync (cloud → ObjectStore)**: User-initiated. Needs the same provider abstraction
  used for export, but in the download direction. The cloud source is a folder/prefix; the
  target is an ObjectStore bucket.
- **Conflict resolution**: objects may exist on both sides; the restore path needs a strategy
  (overwrite all, skip existing, overwrite-if-newer).

The distinction between per-user tokens (export) and service-account/system tokens (backup)
suggests the provider driver should be constructable in two modes:
1. **User-delegated** — from a `User` row's stored OAuth tokens.
2. **Server-delegated** — from application config (service account key, long-lived API key,
   etc.), with no User association.

---

## 5. Gaps and open questions

1. **Token model**: Phase 1 keeps Box tokens as scalar columns on `User`. If a second
   provider is added, introduce a `UserCloudStorageToken` table (`provider`, `access_token`,
   `refresh_token`, `token_valid`, `updated_at`) and migrate Box tokens into it. This
   requires a DB migration and changes to the OAuth flow, and is deferred to Phase 2.

2. **Folder picker UX**: The current "type the folder ID" UX works for Box-savvy users but
   is fragile. Future work might add a JS-driven folder browser using the Box Picker SDK or
   similar. The abstraction should not assume that the destination is always a raw ID.

3. **Backup service identity**: Box supports OAuth2 user delegation but also JWT-based app
   auth (service-account style). For automated backup, JWT auth is more appropriate. This
   is a separate auth path that `get_box_client` does not currently support.

4. **Shared-link access level**: `_get_shared_link` creates an **open** (anyone with the
   link) shared link. For external examiner use this may be intentional, but the provider
   interface surfaces `access` as a parameter rather than hardcoding `OPEN`.

5. **Large-file / streaming uploads**: The current implementation buffers entire files in
   memory (`AssetCloudAdapter.get()` returns bytes). Box supports chunked/multipart uploads
   for files > 50 MB. The `upsert_file` signature accepts `Union[bytes, BinaryIO]` to allow
   streaming without a breaking interface change later.

---

## 6. File inventory

### Existing files (read before implementing)

| File | Role | Key symbols |
|------|------|-------------|
| `app/shared/cloud_object_store/base.py` | ObjectStore abstraction | `Driver`, `ObjectStore`, `EncryptionPipeline`, `_drivers` |
| `app/shared/cloud_object_store/drivers/amazons3.py` | S3 driver | `AmazonS3CloudStorageDriver` |
| `app/shared/cloud_object_store/drivers/google.py` | GCS driver | `GoogleCloudStorageDriver` |
| `app/shared/cloud_object_store/drivers/local.py` | Local FS driver | `LocalFileSystemDriver` |
| `app/shared/cloud_object_store/bucket_types.py` | Bucket integer constants | `BucketTypes` |
| `app/shared/box_api.py` | Box client factory + token lifecycle | `get_box_client`, `revoke_box_auth`, `_do_token_refresh`, `DBTokenStorage` |
| `app/models/users.py:183–212` | Box OAuth fields on User | `box_access_token`, `box_refresh_token`, `box_token_valid`, `box_updated_at` |
| `app/oauth2/views.py` | Box OAuth2 flow | `box_login`, `box_callback` |
| `app/tasks/box_export_period_marking.py` | Export task | `box_export_period_marking`, `_build_in_scope_records`, `_build_excel`, `_upsert_file`, `_get_shared_link` |
| `app/tasks/box_tokens.py` | Token maintenance beat task | `maintain_box_tokens` |
| `app/convenor/markingevent.py:3386–3503` | Export trigger view | `export_period_to_box` |
| `app/convenor/forms.py:1792–1818` | Export form factory | `ExportPeriodToBoxFormFactory` |
| `app/shared/asset_tools.py:58–259` | Asset download helper | `AssetCloudAdapter` |
| `app/templates/convenor/markingevent/export_period_to_box.html` | Export form template | (Jinja2) |
| `instance/local.py` | ObjectStore bucket configuration | `OBJECT_STORAGE_ASSETS`, etc. |

### New files (to be created)

| File | Role |
|------|------|
| `app/shared/cloud_storage/__init__.py` | Package root |
| `app/shared/cloud_storage/base.py` | `CloudStorageProvider` ABC, `CloudStorageLocation`, `CloudItem` |
| `app/shared/cloud_storage/registry.py` | `_providers` dict; `get_provider_class(name)` |
| `app/shared/cloud_storage/providers/__init__.py` | Sub-package root |
| `app/shared/cloud_storage/providers/box.py` | `BoxCloudStorageProvider` |

---

## 7. Design sketch

### Package layout

```
app/shared/cloud_storage/
  __init__.py
  base.py          ← CloudStorageProvider ABC, CloudStorageLocation, CloudItem
  registry.py      ← _providers dict; get_provider_class(name)
  providers/
    __init__.py
    box.py         ← BoxCloudStorageProvider (wraps get_box_client / from_config)
    [future: gdrive.py, onedrive.py, ...]
```

### `CloudStorageProvider` ABC

The low-level layer. Knows how to talk to one provider; holds the credential. Never used
directly by task code. Must be declared with `abc.ABC` and `@abstractmethod` so that
incomplete implementations raise `TypeError` at class-definition time:

```python
from abc import ABC, abstractmethod
from typing import BinaryIO, List, Optional, Union

class CloudStorageProvider(ABC):
    # Introspection
    @abstractmethod
    def provider_name(self) -> str: ...       # "box", "gdrive", …
    @abstractmethod
    def display_name(self) -> str: ...        # "Box", "Google Drive", …

    # Construction — two modes
    @classmethod
    @abstractmethod
    def from_user(cls, user: User) -> "CloudStorageProvider": ...
    @classmethod
    @abstractmethod
    def from_config(cls, cfg: dict) -> "CloudStorageProvider": ...

    # Auth status / recovery
    @abstractmethod
    def is_authenticated(self) -> bool: ...
    @abstractmethod
    def reauth_url(self) -> str: ...          # URL for re-link notification
    @abstractmethod
    def is_auth_error(self, exc: Exception) -> bool: ...

    # Folder operations
    @abstractmethod
    def get_or_create_folder(self, parent_ref: str, name: str) -> str: ...
    @abstractmethod
    def list_folder(self, folder_ref: str) -> List["CloudItem"]: ...

    # File operations — upload is upsert (insert or version-replace; never duplicates)
    @abstractmethod
    def upsert_file(
        self,
        folder_ref: str,
        filename: str,
        data: Union[bytes, BinaryIO],
        mimetype: str = "application/octet-stream",
    ) -> str: ...                             # returns file_ref
    @abstractmethod
    def download_file(self, file_ref: str) -> bytes: ...
    @abstractmethod
    def get_shareable_url(
        self,
        file_ref: str,
        access: str = "open",
    ) -> Optional[str]: ...                   # None if provider doesn't support sharing
    @abstractmethod
    def delete_file(self, file_ref: str) -> None: ...
```

### `CloudItem`

```python
@dataclass
class CloudItem:
    ref: str                    # provider-specific opaque ID
    name: str
    kind: str                   # "file" | "folder"
    size: Optional[int]
    modified_at: Optional[datetime]
    url: Optional[str] = None   # shareable/download URL if the provider returns one at
                                # list time; None otherwise. Callers must fall back to
                                # location.get_shareable_url(item.ref) when this is None.
```

### `CloudStorageLocation`

The facade layer. Holds `(provider, root_ref)`, adds the audit layer, and is the only
class task code imports from `cloud_storage`. Not an ABC — provider variation is achieved
by swapping the provider inside it.

```python
class CloudStorageLocation:
    def __init__(
        self,
        provider: CloudStorageProvider,
        root_ref: str,
        audit_data: str = "",
        audit_cfg: Optional[dict] = None,
    ): ...

    # Construction helpers
    @classmethod
    def from_user(
        cls,
        provider_name: str,
        user: User,
        root_ref: str,
        audit_data: str = "",
        audit_cfg: Optional[dict] = None,
    ) -> "CloudStorageLocation": ...

    @classmethod
    def from_config(
        cls,
        provider_name: str,
        root_ref: str,
        data: dict,             # passed to provider.from_config; also contains "audit" key
    ) -> "CloudStorageLocation": ...

    # Folder operations — parent_ref=None means relative to root_ref
    def get_or_create_folder(
        self, parent_ref: Optional[str], name: str
    ) -> str: ...
    def list_folder(self, folder_ref: str) -> List[CloudItem]: ...

    # File operations (all mutating calls are audited)
    def upsert_file(
        self,
        folder_ref: str,
        filename: str,
        data: Union[bytes, BinaryIO],
        mimetype: str = "application/octet-stream",
    ) -> str: ...
    def download_file(self, file_ref: str) -> bytes: ...
    def get_shareable_url(
        self, file_ref: str, access: str = "open"
    ) -> Optional[str]: ...
    def delete_file(self, file_ref: str) -> None: ...

    # Auth error convenience — wraps provider.is_auth_error + provider.reauth_url
    def handle_auth_error(
        self, exc: Exception, notify_user: Optional[User] = None
    ) -> bool: ...    # returns True if exc was an auth error (and notification was posted)
```

### Configuration pattern (backup destinations)

Server-delegated destinations are declared in `instance/local.py`:

```python
CLOUD_STORAGE_BACKUP = CloudStorageLocation.from_config(
    provider_name="box",
    root_ref="123456789",      # Box folder ID of the backup root
    data={
        "auth": "server",      # causes from_config on the provider
        "client_id": "...",    # or pulled from BOX_CLIENT_ID config key
        "client_secret": "...",
        "audit": {"backend": "mongodb", ...},
    },
)
```

User-delegated locations are constructed at task dispatch time and are not stored in config.

### Refactoring targets

**`box_export_period_marking`:** Replace `get_box_client(box_user)` + all private helpers
with a `CloudStorageLocation.from_user(provider_name="box", user=box_user, root_ref=folder_id, ...)`.
Map: `_upsert_file` → `location.upsert_file`; `_get_shared_link` →
`location.get_shareable_url`; `_get_or_create_subfolder` → `location.get_or_create_folder`;
the three `_is_box_auth_error` / `_post_relink_notification` call sites →
`location.handle_auth_error(exc, notify_user=requesting_user)`.

**`ExportPeriodToBoxFormFactory`** (sole call site: `markingevent.export_period_to_box`)
→ `CloudExportFormFactory(provider_name, users_with_tokens)`, rendering the appropriate
destination fields for the configured provider.

**Token maintenance tasks** (`maintain_box_tokens` and any future equivalents) remain
provider-specific and are **not** part of either layer.
