# Phase 4 — Configuration tile surface

**Prerequisite: Phases 1, 2, and 3 are complete and verified.**

---

## Objective

Add a new `configure` route that renders a tile grid giving the convenor a scannable overview of all cycle-level and
per-period configuration, with direct links into the relevant sections of existing edit forms. No existing edit forms
are replaced — this surface is purely navigational and informational.

---

## Step 1 — Read before writing

Read these files in full:

- `app/templates/convenor/dashboard/edit_project_config.html` — identify every form section and its fields; these become
  cycle-level tiles
- `app/templates/convenor/dashboard/edit_period_record.html` — identify every form section; these become per-period
  tiles
- `app/convenor/dashboard.py` — find the existing `edit_project_config` and `edit_period_record` view functions and
  their route names
- The Phase 0 resources routes list — for marking schemes, email templates, feedback documents, grading rubric tiles
- `app/models/ProjectClassConfig` — identify the fields summarised in each tile (to render current values)

---

## Step 2 — New route and view function

Add to `app/convenor/dashboard.py`:

```python
@convenor.route("/configure/<int:id>")
@roles_accepted("faculty", "admin", "root")
def configure(id):
    pclass: ProjectClass = ProjectClass.query.get_or_404(id)
    if not validate_is_convenor(pclass):
        return redirect(redirect_url())

    config: ProjectClassConfig = pclass.most_recent_config
    if config is None:
        flash("Internal error: could not locate ProjectClassConfig.", "error")
        return redirect(redirect_url())

    data = get_convenor_dashboard_data(pclass, config)

    return render_template_context(
        "convenor/dashboard/configure.html",
        pane="configure",  # new pane value — nav.html will show no pill as active
        pclass=pclass,
        config=config,
        convenor_data=data,
    )
```

---

## Step 3 — Create `configure.html`

Create `app/templates/convenor/dashboard/configure.html`. It must extend `convenor/dashboard/pclass_base.html`.

The page has two sections, visually separated by a section label and a horizontal rule:

### Section A — Cycle-level settings

Section label: "Cycle-level settings" with a small badge: "ProjectClassConfig · applies to the whole {{
config.submit_year_a }}–{{ config.submit_year_b }} cycle"

Tile grid — 3 columns, Bootstrap `row-cols-1 row-cols-md-2 row-cols-lg-3 g-3`:

| Tile name          | Current value summary                                                    | Edit link target                                                     |
|--------------------|--------------------------------------------------------------------------|----------------------------------------------------------------------|
| Roles & assessment | Enabled roles as chips (Supervisors, Markers, Moderators, Presentations) | `url_for('convenor.edit_project_config', pid=config.id)#supervision` |
| Workload & CATS    | "Supervision: N CATS · Marking: N CATS · …"                              | `url_for('convenor.edit_project_config', pid=config.id)#cats`        |
| Project selection  | "N initial choices · availability"                                       | `url_for('convenor.edit_project_config', pid=config.id)#selection`   |
| Canvas integration | Module ID if set, else "Not configured"                                  | `url_for('convenor.edit_project_config', pid=config.id)#canvas`      |
| AI grading rubric  | Rubric name if set, else "None (disabled)"                               | `url_for('convenor.edit_project_config', pid=config.id)#ai`          |
| Document limits    | Word limit status, tolerance                                             | `url_for('convenor.edit_project_config', pid=config.id)#limits`      |
| Email templates    | "N templates configured" or "Default"                                    | Route from Phase 0 resources list                                    |
| Marking schemes    | Count of schemes                                                         | Route from Phase 0 resources list                                    |
| Feedback documents | "N recipes configured" or "None"                                         | Route from Phase 0 resources list                                    |

**Important:** The fragment-id anchors (`#supervision`, `#cats`, etc.) require the corresponding `id` attributes to be
added to the section headings in `edit_project_config.html`. Add these `id` attributes in this phase — list which ones
you added.

Each tile is a Bootstrap card with:

- Icon (FontAwesome, consistent with the rest of the app)
- Tile name as `card-title`
- Current value summary as `card-text text-body-secondary small`
- A "Edit →" button (`btn btn-sm btn-outline-secondary`) linking to the target above
- Scope badge in `card-footer`:
  `<span class="badge bg-primary-subtle text-primary-emphasis rounded-pill">Cycle setting</span>`

### Section B — Per-period settings

Section label: "Per-period settings" with badge: "SubmissionPeriodRecord · each period is configured independently"

For each `period` in `config.periods` (iterate in submission_period order):

Period heading row: period display name, status chip, date range, small warning if `period.has_active_marking_event` ("⚠
Active marking events — some fields locked")

2-column tile grid within each period:

| Tile name               | Current value summary                          | Edit link                                                            |
|-------------------------|------------------------------------------------|----------------------------------------------------------------------|
| Dates & deadlines       | Start date, hand-in date                       | `url_for('convenor.edit_period_record', pid=period.id)#dates`        |
| Markers per submission  | N markers, supervision grade enabled/disabled  | `url_for('convenor.edit_period_record', pid=period.id)#markers`      |
| Presentation assessment | Summary if configured, "Not configured" if not | `url_for('convenor.edit_period_record', pid=period.id)#presentation` |
| Canvas assignment       | Assignment ID if set, else "Not set"           | `url_for('convenor.edit_period_record', pid=period.id)#canvas`       |

Add `id` attributes to the corresponding sections in `edit_period_record.html` (list which ones you added).

---

## Step 4 — "Edit all settings" escape hatch

At the top-right of the page (inside a `d-flex justify-content-end` wrapper before Section A), add:

```html
<a class="btn btn-outline-secondary btn-sm" href="{{ url_for('convenor.edit_project_config', pid=config.id) }}">
    <i class="fas fa-list fa-fw"></i> Edit all cycle settings
</a>
```

---

## Step 5 — Wire up the "Configure" button in the persistent header

In `pclass_base.html` (from Phase 1), the "Configure" button currently links to
`url_for('convenor.edit_project_config', pid=config.id)`. Change this to link to the new
`url_for('convenor.configure', id=pclass.id)`.

---

## Step 6 — Verification

1. Load the configure page for a pclass that has: Canvas enabled, a grading rubric set, 2 periods. Confirm all 9 cycle
   tiles render with non-empty current values and working Edit links.
2. Confirm both periods appear under Section B.
3. Confirm fragment-id anchors exist in `edit_project_config.html` for every tile target listed in Step 3.
4. Confirm fragment-id anchors exist in `edit_period_record.html` for every per-period tile target.
5. Confirm `configure.html` extends `pclass_base.html` and the persistent header renders correctly (pane="configure"
   means no pill is active, which is correct — the configure page is not one of the pill tabs).
6. Grep for `url_for('convenor.edit_project_config'` in `pclass_base.html` — confirm it now points to
   `convenor.configure` instead.

Report results of all six checks.