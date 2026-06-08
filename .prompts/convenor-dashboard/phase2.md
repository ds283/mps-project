# Phase 2 — Actions panel

**Prerequisite: Phase 1 is complete and verified.**

---

## Objective

Add a prioritised actions panel to the top of the convenor dashboard overview tab, between the pill navigation and the
60/40 split columns. The panel lists items requiring the convenor's attention, ordered by severity (blocking → warning →
advisory), each with a direct action button.

This phase adds a new data function and a new template fragment. It does not change any existing queries — it
centralises conditions already scattered across `status.html` and `overview.html`.

---

## Step 1 — Read before writing

Read these files in full:

- `app/shared/context/convenor_dashboard.py` — specifically `get_convenor_dashboard_data` return dict and
  `marking_urgent_count` computation
- `app/templates/convenor/dashboard/status.html` — find every conditional that triggers an alert or warning (stale
  confirmations, canvas issues, marking urgent, etc.)
- `app/templates/convenor/dashboard/overview.html` — same, for the overview card alerts
- The `MarkingEvent` model — find `urgent_action_count` and any related state constants
- The `SubmissionPeriodRecord` model — find any `closed`, `feedback_open` state properties and what blocks period
  closure

---

## Step 2 — Define `get_convenor_action_items`

Add a new function to `app/shared/context/convenor_dashboard.py`:

```python
def get_convenor_action_items(pclass: ProjectClass, config: ProjectClassConfig, convenor_data: dict) -> list[dict]:
```

This function takes the already-computed `convenor_data` dict (do not re-query what is already there) and returns a list
of action item dicts, each with:

```python
{
    "severity": "blocking" | "warning" | "advisory",
    "icon": str,  # FontAwesome class, e.g. "fas fa-exclamation-octagon"
    "message": str,  # plain-text description of the issue
    "detail": str | None,  # optional sub-line with more context
    "action_label": str,  # button label
    "action_url": str,  # url_for(...) result
}
```

The list must be sorted: all `blocking` items first, then `warning`, then `advisory`.

### Required action items (implement all of these)

**Blocking:**

- Outstanding confirmation requests older than a threshold (use the existing `age_oldest_confirm_request` value from
  `convenor_data`; threshold = 14 days). Message: "N outstanding confirmation requests — oldest waiting D days." Action:
  `url_for('convenor.outstanding_confirm_requests', id=pclass.id)` (or the correct route name from Phase 0).
- Any `MarkingEvent` in an active period with `urgent_action_count > 0` — one item per affected event. Message: "«event
  name» — N workflow(s) require convenor action." Action: `url_for('convenor.marking_event_workflows_inspector', ...)` (
  use the correct route name from Phase 0).

**Warning:**

- Any `SubmissionPeriodRecord` in the current config where submitters are awaiting report upload (i.e.
  `SubmittingStudent` records with no completed `SubmissionRecord`). Message: "Submission Period #N — N submitters
  awaiting report upload." Action: `url_for('convenor.submitters', id=pclass.id)`.
- Canvas integration enabled but `missing_canvas_count > 0` (from `convenor_data`). Message: "N students are not
  enrolled in the Canvas module." Action: `url_for('convenor.submitters', id=pclass.id)`.

**Advisory:**

- Selectors with neither a submission nor any bookmarks (derive from `convenor_data` if available, otherwise query).
  Message: "N selectors have neither submitted a selection nor bookmarked any projects — they may receive a random
  allocation." Action: `url_for('convenor.selectors', id=pclass.id)`.

Do not invent new queries for data already in `convenor_data`. For items that need a small additional query (e.g.
per-period missing upload count), keep it focused and add a comment noting the query cost.

---

## Step 3 — Update `status` view function

In `dashboard.py`, in the `status` view:

1. Import `get_convenor_action_items`
2. After the existing `data = get_convenor_dashboard_data(pclass, config)` call, add:
   ```python
   action_items = get_convenor_action_items(pclass, config, data)
   ```
3. Pass `action_items=action_items` to `render_template_context`

---

## Step 4 — Create `_action_panel.html` fragment

Create `app/templates/convenor/dashboard/overview_cards/_action_panel.html`.

The fragment receives `action_items` (the list from Step 2).

Render rules:

- If `action_items` is empty, render a compact "all clear" row: a small green check icon and "No actions required" in
  `text-body-secondary`. Keep this minimal — it should not dominate the page.
- If non-empty, render a count badge ("N items") followed by one card per item.
- Each card: left-aligned icon (colour driven by severity: `text-danger` for blocking, `text-warning` for warning,
  `text-body-secondary` for advisory), message text with `detail` sub-line if present, right-aligned action button (
  `btn-outline-danger` for blocking, `btn-outline-warning` for warning, `btn-outline-secondary` for advisory).
- Blocking items get `border-danger` card border. Warning items get `border-warning`. Advisory items have default
  border.

Use only existing Bootstrap 5.3 utility classes and the app's named CSS tokens. No inline hex colours. No new CSS
classes.

---

## Step 5 — Include the fragment in `status.html`

In `app/templates/convenor/dashboard/status.html`, find the correct insertion point — this should be **after** the pill
nav and sub-tab bar but **before** the existing first content section (currently the stale-confirmations alert strip).

Add:

```jinja
{% from "convenor/dashboard/overview_cards/_action_panel.html" import action_panel %}
{{ action_panel(action_items) }}
```

Remove (or comment out with a `{# SUPERSEDED #}` marker) any existing alert strips in `status.html` whose conditions are
now covered by the action panel. Do not remove anything you are unsure about — mark it and note it in your report.

---

## Step 6 — Verification

1. With `action_items = []`, render the page mentally and confirm the "all clear" row appears and takes no significant
   vertical space.
2. Confirm that `get_convenor_action_items` never calls `get_convenor_dashboard_data` internally — it only reads from
   the passed-in `convenor_data` dict (plus any small targeted queries noted in Step 2).
3. Grep `status.html` for `alert-danger` and `alert-warning` blocks. For each one, confirm it is either (a) superseded
   by an action panel item and marked `{# SUPERSEDED #}`, or (b) covers a genuinely different condition and kept.
4. Confirm the action panel fragment uses no hardcoded hex colours and no inline `style` font-size attributes.

Report results of all four checks.