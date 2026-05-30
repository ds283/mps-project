# MarkingEvent model field rules

## SubmitterReport sign-off / completion field discipline

`SubmitterReport` has two pairs of fields that track the sign-off / completion action:

- `signed_off_id` / `signed_off_timestamp`
- `completed_by_id` / `completed_timestamp`

**Both pairs must always be written together** whenever a `SubmitterReport` transitions into
the `COMPLETED` state.  Never set one pair without also setting the other.

```python
# Correct — always set both pairs simultaneously
sr.signed_off_id = current_user.id
sr.signed_off_timestamp = now
sr.completed_by_id = current_user.id
sr.completed_timestamp = now
sr.workflow_state = SubmitterReportWorkflowStates.COMPLETED
```

**On return to convenor**, clear only the `completed_*` fields.  The `signed_off_*` fields
must be left untouched so they preserve the most-recent sign-off identity across return cycles.

```python
# Correct — clear only completed_*, leave signed_off_* intact
sr.workflow_state = SubmitterReportWorkflowStates.READY_TO_SIGN_OFF
sr.completed_by_id = None
sr.completed_timestamp = None
```

**Invariant**: whenever `completed_by_id` is non-NULL, `signed_off_id == completed_by_id`
and `signed_off_timestamp == completed_timestamp`.

See `app/models/markingevent.py` (`SubmitterReport`, SIGN-OFF / COMPLETION section) for the
canonical field documentation.
