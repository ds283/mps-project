# Phase 7 — Cloud backup tab template and AJAX formatter

## Prerequisites

Phase 6 (routes) must be complete.

## Context

This phase creates the `cloud_backup.html` template and a new AJAX row formatter in
`app/ajax/site/cloud_backups.py`.  It also creates the confirmation template for the
account/folder change flow.

## Files to read before writing any code

1. `app/templates/admin/backup_dashboard/nav.html` — shell template to extend.
2. `app/templates/admin/backup_dashboard/manage.html` — DataTable template pattern.
3. `app/templates/admin/backup_dashboard/overview.html` — card layout and Bootstrap
   patterns used in this dashboard.
4. `app/ajax/site/backups.py` — row formatter pattern to mirror.
5. `app/admin/system.py` (post Phase 6) — to confirm template variable names passed
   by the `cloud_backup` view.
6. `app/models/utilities.py` (post Phase 2) — `ObjectStoreBackupRecord` field names
   and status constants.
7. Any existing confirmation template in `app/templates/admin/` — for the
   config-change confirmation page pattern.

## CSS / Bootstrap discipline

- Use Bootstrap 5.3 semantic colour tokens (`text-success`, `text-warning`,
  `text-danger`, `bg-success`, etc.).  No hardcoded hex values.
- No inline `style="color: #..."` attributes.
- Badge classes: `badge bg-success`, `badge bg-warning text-dark`,
  `badge bg-danger`, `badge bg-info text-dark`, `badge bg-secondary`.
- Card headers: `card-header bg-primary text-white` for primary-accent cards
  (matching `manage.html`).
- Use `bg-well` for secondary-surface cards (matching `overview.html`).
- All icons: Font Awesome 5 classes (`fas fa-...`), matching the existing templates.

## New file: `app/ajax/site/cloud_backups.py`

Formatter function: `cloud_backups_data(records: List[ObjectStoreBackupRecord])`.

Follow the pattern in `app/ajax/site/backups.py` exactly: use
`render_template_string(template_str, r=record)` for each cell, return a list of dicts
with keys matching the DataTable column names defined in the route.

Column templates:

- `timestamp`: `r.timestamp.strftime("%a %d %b %Y %H:%M:%S")`
- `run_id`: first 8 characters of `r.run_id` in a `<code>` tag — enough to identify
  runs visually.
- `bucket`: `<span class="badge bg-secondary">{{ r.bucket_label }}</span>`
- `total`: `{{ r.object_count_total or '—' }}`
- `uploaded`: `{{ r.object_count_uploaded or 0 }}`
- `errors`:
  ```
  {% if r.object_count_error %}
      <span class="text-warning fw-bold">{{ r.object_count_error }}</span>
  {% else %}
      0
  {% endif %}
  ```
- `bytes`: `{{ r.readable_bytes_uploaded }}`
- `status`:
  ```
  {% if r.status == 1 %}<span class="badge bg-success">Success</span>
  {% elif r.status == 3 %}<span class="badge bg-warning text-dark">Partial</span>
  {% elif r.status == 2 %}<span class="badge bg-danger">Failed</span>
  {% else %}<span class="badge bg-info text-dark">Running</span>{% endif %}
  ```
- `menu`: an actions dropdown containing:
  - "Restore this bucket…" → `url_for('admin.cloud_backup_restore', record_id=r.id)`
  - "Restore all from this run…" → `url_for('admin.cloud_backup_restore_run', run_id=r.run_id)`
  - Separator
  - Muted display of `error_detail` truncated to 200 chars if `r.object_count_error > 0`.

Register the import in `app/ajax/site/__init__.py` (or wherever the site AJAX modules
are imported) following the existing pattern.

## New template: `app/templates/admin/backup_dashboard/cloud_backup.html`

Extends `admin/backup_dashboard/nav.html`.  `pane="cloud"`.

### Section A: Configuration card

```
card.bg-well
  card-header "Cloud backup configuration"
  form  action="{{ url_for('admin.cloud_backup') }}"  method="POST"
    hidden_tag
    row (2 columns)
      col-8:  config fields (backup_account, root_folder_id)
      col-4:  status summary (token status, schedule, next run, enabled flag)
    row:
      alert-warning (only if schedule_entry.owner_id is None):
        "No backup account configured. Select an account above and save."
    row (action buttons):
      btn: Save configuration
      btn: Run backup now  →  url_for('admin.cloud_backup_run_now')
```

Use `{{ wtf.render_field(form.backup_account) }}` and
`{{ wtf.render_field(form.root_folder_id) }}` from the `bootstrap/form.html` macro.

The "Token status" display:
```html
{% if schedule_entry and schedule_entry.owner and schedule_entry.owner.box_token_valid %}
    <span class="badge bg-success"><i class="fas fa-check"></i> Valid</span>
    <a href="{{ url_for('oauth2.box_login') }}" class="ms-2 small">Re-authenticate</a>
{% elif schedule_entry and schedule_entry.owner %}
    <span class="badge bg-danger"><i class="fas fa-exclamation-triangle"></i> Invalid</span>
    <a href="{{ url_for('oauth2.box_login') }}" class="ms-2 small">Re-authenticate now</a>
{% else %}
    <span class="badge bg-secondary">Not configured</span>
{% endif %}
```

### Section B: Latest run summary (if `latest_records` is not empty)

A compact status strip — one row per record — matching the design in the overview
mockup.  Rendered as a bordered table (not a DataTable), not paginated:

```
table.table.table-sm.table-bordered
  thead: Bucket | Objects | Uploaded | Skipped | Errors | Status | Duration
  tbody:
    {% for r in latest_records %}
    <tr>
      <td><span class="badge bg-secondary">{{ r.bucket_label }}</span></td>
      <td>{{ r.object_count_total or '—' }}</td>
      <td>{{ r.object_count_uploaded or 0 }}</td>
      <td>{{ r.object_count_skipped or 0 }}</td>
      <td>
        {% if r.object_count_error %}
          <span class="text-warning fw-bold"
                data-bs-toggle="popover" data-bs-trigger="focus"
                data-bs-content="{{ r.error_detail[:500] if r.error_detail else '' }}"
                tabindex="0">
            {{ r.object_count_error }}
          </span>
        {% else %}0{% endif %}
      </td>
      <td>{{ r.status_label }}</td>
      <td>{{ "%.0f"|format(r.duration_seconds) ~ 's' if r.duration_seconds else '—' }}</td>
    </tr>
    {% endfor %}
```

Note the popover on the error count — this surfaces `error_detail` without requiring
a separate page.

### Section C: Run history DataTable

```javascript
$('#cloud-backup-table').DataTable({
    responsive: true, bAutoWidth: false, colReorder: true, dom: 'lftipr',
    stateSave: true, serverSide: true, processing: true,
    language: {{ bootstrap_spinner() }},
    ajax: {
        url: $SCRIPT_ROOT + '/admin/cloud_backup_ajax',
        type: 'POST',
        data: function(args) { return {"args": JSON.stringify(args)}; }
    },
    "fnDrawCallback": function() {
        $('body').tooltip({selector: '[data-bs-toggle="tooltip"]'});
        $('body').popover({selector: '[data-bs-toggle="popover"]', html: true, trigger: 'focus'});
    },
    columns: [
        {data: 'timestamp',  orderable: true,  searchable: true},
        {data: 'run_id',     orderable: false, searchable: false},
        {data: 'bucket',     orderable: true,  searchable: false},
        {data: 'total',      orderable: true,  searchable: false},
        {data: 'uploaded',   orderable: true,  searchable: false},
        {data: 'errors',     orderable: true,  searchable: false},
        {data: 'bytes',      orderable: true,  searchable: false},
        {data: 'status',     orderable: true,  searchable: false},
        {data: 'menu',       orderable: false, searchable: false},
    ],
    order: [[0, 'desc']],
});
```

### Section D: Restore modal

Use a Bootstrap 5 modal (`<div class="modal fade" ...>`) for the restore confirmation,
populated via JavaScript when the user clicks a Restore button in the DataTable menu.
The modal content mirrors the mockup design:

- Source run (run_id prefix + timestamp).
- Scope (bucket label or "all buckets").
- Two radio options (skip existing / overwrite all), default to skip existing.
- Warning about nonce re-encryption.
- Orphaned-objects note: "Objects with no matching database record will be skipped."
- Confirm / Cancel buttons.

The Confirm button submits a form `action` that points to the appropriate restore route
with the `record_id` or `run_id` encoded as a data attribute, set by the JS that opens
the modal.

**Note:** Since Bootstrap modals use `display: none` which conflicts with the streaming
rules in this codebase's mockup tool, this is a standard in-page Bootstrap modal and is
fine for an actual Jinja template.

## New template: `app/templates/admin/backup_dashboard/confirm_cloud_config_change.html`

Extends `admin/backup_dashboard/nav.html`.  `pane="cloud"`.

Content:
```
card border-warning
  card-header bg-warning text-dark
    "Confirm cloud backup configuration change"
  card-body
    alert-danger:
      "Changing the backup account or root folder will permanently delete all
       existing cloud backup records from the database.  The cloud files in Box
       will not be affected, but MPS Projects will lose track of them and begin
       a fresh backup cycle."
    dl.row (proposed new settings):
      dt: Backup account  dd: <new account name or "None">
      dt: Root folder ID  dd: <new folder ID>
    form action="{{ url_for('admin.apply_cloud_backup_config_change') }}" method="POST"
      hidden_tag
      d-flex gap-2:
        btn btn-warning: Confirm — reset and apply
        a btn btn-outline-secondary href="{{ url_for('admin.cloud_backup') }}": Cancel
```

## Out of scope for this phase

- `nav.html` pill and overview strip — Phase 8.

## Verification

```bash
ls app/templates/admin/backup_dashboard/cloud_backup.html
ls app/templates/admin/backup_dashboard/confirm_cloud_config_change.html
grep -n "cloud_backups_data" app/ajax/site/cloud_backups.py
grep -n "cloud-backup-table" app/templates/admin/backup_dashboard/cloud_backup.html
grep -n "popover" app/templates/admin/backup_dashboard/cloud_backup.html
```

Manually confirm the DataTable AJAX endpoint returns valid JSON with the expected
column keys by navigating to the cloud backup tab and inspecting the network request
in the browser developer tools.  Live browser verification is outstanding at this
stage.
