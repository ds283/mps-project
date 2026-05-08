---
paths:
  - app/models/submissions.py
  - app/shared/scraped_text_store.py
  - app/tasks/**
  - app/documents/**
---

# MongoDB scraped-text cache and SubmissionRecord deletion

The language-analysis pipeline caches extracted document text in MongoDB, keyed by `submission_record_id`
(see `app/shared/scraped_text_store.py`). This cache must be explicitly cleaned up whenever a
`SubmissionRecord` is deleted — MongoDB has no foreign-key constraints and will silently accumulate
orphaned documents otherwise.

`delete_scraped_text(record_id: int)` in `app/shared/scraped_text_store.py` is the designated cleanup
function. It is safe to call unconditionally: it is a no-op when no cached document exists, and it logs a
warning (rather than raising) when MongoDB is not configured.

**ORM-path deletes** (single-object `db.session.delete()` or ORM cascade) fire the
`_SubmissionRecord_delete_handler` `before_delete` event in `app/models/submissions.py`. The call to
`delete_scraped_text` belongs there so that all ORM-path deletes are covered automatically.

**Bulk SQL deletes** (`.delete()` on a Query) bypass ORM events entirely. Before issuing any bulk delete
against `SubmissionRecord`, collect the affected IDs first and call `delete_scraped_text` for each:

```python
record_ids = [r.id for r in db.session.query(SubmissionRecord.id).filter_by(...)]
db.session.query(SubmissionRecord).filter_by(...).delete()
for rid in record_ids:
    delete_scraped_text(rid)
```

**Report field changes** — the scraped-text cache must also be invalidated whenever `SubmissionRecord.report`
is voided or replaced on a record that already exists:

- **Voiding** (`record.report_id = None`): call `delete_scraped_text(record.id)` immediately after the
  assignment. There is no pipeline task that will repopulate the cache, so failing to clear it leaves
  stale text in MongoDB indefinitely.
- **Replacing** (`record.report_id = new_asset_id`): call `delete_scraped_text(record.id)` before the
  assignment. The subsequent `download_and_extract` pipeline task will repopulate the cache via an upsert,
  but clearing first makes the intent explicit and avoids a brief window of stale data.

Note: `upload_submitter_report` (`app/documents/views.py`) guards against uploads when a report already
exists, so `report_id` always goes `None → asset_id` there and no stale cache entry can exist.
Only `perform_delete_submitter_report` (void) and `_finalize_report_attachment` in `app/tasks/canvas.py`
(Canvas pull, which can replace) require explicit cache invalidation.
