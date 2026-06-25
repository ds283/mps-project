# Phase 8 — Nav pill and overview tab cloud-status strip

## Prerequisites

Phase 6 (routes) must be complete.  Phase 7 may be run in parallel with this phase.

## Context

This phase adds the "Cloud backup" pill to the existing nav shell and a cloud-status
summary strip to the overview tab.  Both are purely template changes.

## Files to read before writing any code

1. `app/templates/admin/backup_dashboard/nav.html` — the pill nav shell.
2. `app/templates/admin/backup_dashboard/overview.html` — the overview tab template.
3. `app/admin/system.py` post Phase 6 — confirm what context variables the
   `backups_overview` view passes.  The overview view will need two additional
   variables: `latest_cloud_records` and `cloud_backup_alert`.

## Changes required

### 8.1  Update `backups_overview` route to pass cloud-backup context

In `app/admin/system.py`, in the `backups_overview` view function, add:

```python
# Latest cloud backup run summary
latest_cloud_run_id = (
    db.session.query(ObjectStoreBackupRecord.run_id)
    .order_by(ObjectStoreBackupRecord.timestamp.desc())
    .limit(1)
    .scalar()
)
latest_cloud_records = (
    db.session.query(ObjectStoreBackupRecord)
    .filter_by(run_id=latest_cloud_run_id)
    .all()
    if latest_cloud_run_id else []
)
cloud_backup_alert = any(
    r.status in (ObjectStoreBackupRecord.FAILED, ObjectStoreBackupRecord.PARTIAL)
    for r in latest_cloud_records
)
```

Add `latest_cloud_records=latest_cloud_records` and
`cloud_backup_alert=cloud_backup_alert` to the `render_template(...)` call.

Import `ObjectStoreBackupRecord` at the top of `system.py` if not already imported.

### 8.2  Update `nav.html`

Add a third pill immediately after the "View backups" pill:

```html
<li class="nav-item">
    <a class="nav-link {% if pane == 'cloud' %}active{% endif %}"
       href="{{ url_for('admin.cloud_backup') }}">
        Cloud backup
        {% if cloud_backup_alert is defined and cloud_backup_alert %}
            <span class="badge bg-danger rounded-pill">!</span>
        {% endif %}
    </a>
</li>
```

The `cloud_backup_alert` variable is passed from the route.  Use `is defined` guard
so the pill renders safely even on templates that do not pass this variable.

### 8.3  Update `overview.html`

Add a new card at the bottom of the `bodyblock`, after the existing Bokeh plots card.

The card should only render if `latest_cloud_records` is defined and non-empty.
If the cloud backup is not configured (no records), render a muted placeholder:

```html
{% if latest_cloud_records is defined %}
<div class="row">
    <div class="col-1"></div>
    <div class="col-10">
        <div class="card mt-3 mb-3 card-body bg-well">
            <div class="d-flex flex-row justify-content-between align-items-center mb-3">
                <strong><i class="fas fa-cloud"></i> Cloud backup status</strong>
                <a href="{{ url_for('admin.cloud_backup') }}"
                   class="btn btn-sm btn-outline-primary">
                    Details <i class="fas fa-arrow-right"></i>
                </a>
            </div>

            {% if latest_cloud_records %}
                {% set latest = latest_cloud_records[0] %}
                <div class="mb-2 small text-secondary">
                    Last run:
                    {{ latest.timestamp.strftime("%a %d %b %Y %H:%M") }}
                    &nbsp;&middot;&nbsp;
                    {% if latest.finished_at %}
                        Duration:
                        {{ "%.0f"|format(latest.duration_seconds) }}s
                    {% endif %}
                    &nbsp;&middot;&nbsp;
                    Provider: {{ latest.provider_name|title }}
                </div>
                <table class="table table-sm table-striped table-bordered mb-0">
                    <thead>
                        <tr>
                            <th>Bucket</th>
                            <th class="text-end">Objects</th>
                            <th class="text-end">Uploaded</th>
                            <th class="text-end">Skipped</th>
                            <th class="text-end">Errors</th>
                            <th>Status</th>
                        </tr>
                    </thead>
                    <tbody>
                        {% for r in latest_cloud_records %}
                        <tr>
                            <td><span class="badge bg-secondary">{{ r.bucket_label }}</span></td>
                            <td class="text-end">{{ r.object_count_total or '—' }}</td>
                            <td class="text-end">{{ r.object_count_uploaded or 0 }}</td>
                            <td class="text-end">{{ r.object_count_skipped or 0 }}</td>
                            <td class="text-end">
                                {% if r.object_count_error %}
                                    <span class="text-warning fw-bold">{{ r.object_count_error }}</span>
                                {% else %}
                                    0
                                {% endif %}
                            </td>
                            <td>
                                {% if r.status == 1 %}
                                    <span class="badge bg-success">
                                        <i class="fas fa-check"></i> OK
                                    </span>
                                {% elif r.status == 3 %}
                                    <span class="badge bg-warning text-dark">
                                        <i class="fas fa-exclamation-triangle"></i>
                                        {{ r.object_count_error }} errors
                                    </span>
                                {% elif r.status == 2 %}
                                    <span class="badge bg-danger">
                                        <i class="fas fa-times"></i> Failed
                                    </span>
                                {% else %}
                                    <span class="badge bg-info text-dark">Running</span>
                                {% endif %}
                            </td>
                        </tr>
                        {% endfor %}
                    </tbody>
                </table>
            {% else %}
                <div class="alert alert-secondary mb-0">
                    <i class="fas fa-info-circle"></i>
                    Cloud backup has not run yet, or is not configured.
                    <a href="{{ url_for('admin.cloud_backup') }}">Configure now</a>
                </div>
            {% endif %}
        </div>
    </div>
    <div class="col-1"></div>
</div>
{% endif %}
```

## Out of scope for this phase

Nothing — this is the final phase.

## Verification

```bash
grep -n "cloud_backup_alert" app/templates/admin/backup_dashboard/nav.html
grep -n "latest_cloud_records" app/templates/admin/backup_dashboard/overview.html
grep -n "url_for.*cloud_backup" app/templates/admin/backup_dashboard/nav.html
grep -n "ObjectStoreBackupRecord" app/admin/system.py
```

All should return at least one match.

Navigate to `/admin/backups_overview` and confirm:
- The "Cloud backup" pill appears in the nav bar.
- The cloud-status card renders at the bottom of the overview, either with the latest
  run summary or the "not configured" placeholder.
- The danger badge on the pill is absent when all buckets have `status == SUCCESS`
  and present when any bucket has `status == PARTIAL` or `FAILED`.

Live browser verification is outstanding at this stage.
