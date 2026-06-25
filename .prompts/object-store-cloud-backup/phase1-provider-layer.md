# Phase 1 — Provider layer: chunked upload and folder-listing cache

## Context

The `CloudStorageProvider` ABC and its concrete `BoxCloudStorageProvider` implementation
currently buffer every file entirely in memory before uploading.  The object-store cloud
backup task will upload mysqldump archives that can reach ~100 MB uncompressed.  This
phase adds chunked upload support at the provider layer and a within-task folder-listing
cache that eliminates the O(N²) `_get_folder_items` calls that `upsert_file` currently
makes.

## Files to read before writing any code

Read each of these in full before making any changes:

1. `app/shared/cloud_storage/base.py` — `CloudStorageProvider` ABC and `CloudStorageLocation` façade
2. `app/shared/cloud_storage/providers/box.py` — `BoxCloudStorageProvider`
3. `app/shared/cloud_storage/__init__.py` — public surface of the cloud_storage package

## Changes required

### 1.1  `CloudStorageProvider` ABC (`app/shared/cloud_storage/base.py`)

Add one new abstract method immediately after `upsert_file`:

```python
@abstractmethod
def upsert_file_chunked(
    self,
    folder_ref: str,
    filename: str,
    stream: BinaryIO,
    size: int,
    mimetype: str = "application/octet-stream",
    chunk_size: int = 20 * 1024 * 1024,
) -> str:
    """
    Upload *stream* as *filename* inside *folder_ref* using chunked/multipart upload.
    *size* must be the total byte length of the stream.
    *chunk_size* is the per-part size in bytes (default 20 MB).
    Creates a new version if the filename already exists.
    Returns the provider file ref.

    Falls back to upsert_file() for streams smaller than *chunk_size*.
    """
```

### 1.2  `CloudStorageLocation` façade (`app/shared/cloud_storage/base.py`)

Add a matching `upsert_file_chunked` method on `CloudStorageLocation`, immediately
after the existing `upsert_file` method.  Mirror the audit-log pattern used by
`upsert_file` exactly (record bytes, elapsed_ms, error on exception).

```python
def upsert_file_chunked(
    self,
    folder_ref: str,
    filename: str,
    stream: BinaryIO,
    size: int,
    mimetype: str = "application/octet-stream",
    chunk_size: int = 20 * 1024 * 1024,
) -> str:
    """Chunked upload via the provider; audited."""
    t0 = time.monotonic()
    try:
        result = self._provider.upsert_file_chunked(
            folder_ref, filename, stream, size, mimetype, chunk_size
        )
        self._log_audit(
            "upsert_file_chunked",
            folder_ref=folder_ref,
            name=filename,
            bytes=size,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
        )
        return result
    except Exception as exc:
        self._log_audit(
            "upsert_file_chunked",
            folder_ref=folder_ref,
            name=filename,
            bytes=size,
            elapsed_ms=int((time.monotonic() - t0) * 1000),
            error=repr(exc),
        )
        raise
```

### 1.3  `BoxCloudStorageProvider` — chunked upload (`app/shared/cloud_storage/providers/box.py`)

Add `upsert_file_chunked` implementing the Box SDK chunked upload API.

Box SDK gen exposes chunked upload via `self._client.chunked_uploads`.  The steps are:

1. Create an upload session via `create_file_upload_session` or
   `create_file_upload_session_for_existing_file` (for version replacement).
2. Loop: read `chunk_size` bytes at a time, call
   `self._client.chunked_uploads.upload_file_part(session_id, part_data, digest, offset, total_size)`.
   The `digest` is `"sha=<base64(sha1(part_bytes))>"`.
3. Collect the returned `UploadPart` objects.
4. Commit the session via `self._client.chunked_uploads.create_file_from_upload_session(session_id, parts=parts, digest=<sha1 of full content>)` or the version equivalent.

For the version-replacement path, first check `_get_folder_items` for an existing file
with the same name (same as `upsert_file`), then branch on whether `existing_id` is None.

Fall back to `upsert_file` when `size < chunk_size`:

```python
def upsert_file_chunked(self, folder_ref, filename, stream, size, mimetype, chunk_size):
    if size < chunk_size:
        # Small file — delegate to standard upload
        data = stream.read()
        return self.upsert_file(folder_ref, filename, data, mimetype)
    # ... chunked path
```

**Important:** The Box SDK gen class names for chunked uploads may differ from the v2
SDK.  Read the installed `box_sdk_gen` source or stubs to find the correct class and
method names before writing the implementation.  Do not guess; verify.

### 1.4  `BoxCloudStorageProvider` — folder-listing cache

The current `upsert_file` calls `self._get_folder_items(folder_ref)` before every
upload.  For a backup task iterating over thousands of objects in one folder, this
produces thousands of identical Box API calls.

Add a simple in-instance cache:

```python
# In __init__:
self._folder_item_cache: dict = {}   # folder_ref -> List[item]

def _get_folder_items_cached(self, folder_ref: str) -> list:
    """Return cached folder listing; falls back to live fetch on cache miss."""
    if folder_ref not in self._folder_item_cache:
        self._folder_item_cache[folder_ref] = self._get_folder_items(folder_ref)
    return self._folder_item_cache[folder_ref]

def invalidate_folder_cache(self, folder_ref: str) -> None:
    """Remove a folder from the cache (call after a successful upsert)."""
    self._folder_item_cache.pop(folder_ref, None)
```

Update `upsert_file` and `upsert_file_chunked` to call `_get_folder_items_cached`
instead of `_get_folder_items` for the existence check, and call
`invalidate_folder_cache` after a successful upload so the next check sees the
new item.

**Do not** cache `list_folder` (the public read method called by task code) — that
path is already used for incremental-skip comparisons where freshness matters.
Only the existence-check inside `upsert_file` / `upsert_file_chunked` uses the cache.

`get_or_create_folder` should also use `_get_folder_items_cached` for its folder
existence check, with a `invalidate_folder_cache` call after creating a new folder.

## Out of scope for this phase

- The backup task itself.
- Any ORM changes.
- Any template changes.
- The `download_file` method (Box streaming download is already adequate for restore).

## Verification

After completing the changes, run these greps to confirm the implementation:

```bash
grep -n "upsert_file_chunked" app/shared/cloud_storage/base.py
grep -n "upsert_file_chunked" app/shared/cloud_storage/providers/box.py
grep -n "_folder_item_cache" app/shared/cloud_storage/providers/box.py
grep -n "invalidate_folder_cache" app/shared/cloud_storage/providers/box.py
```

Each should return at least one match.  Confirm the ABC has `@abstractmethod` on
`upsert_file_chunked` and the `CloudStorageLocation` façade has a non-abstract wrapper.
