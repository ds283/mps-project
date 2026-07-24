# Handoff: Matching dashboard — recover config, timings & inheritance (option 1a)

## Overview

The rebuilt **Automatic matching** dashboard (`matching_workspace/matching_dashboard.html`, cards
rendered by `app/ajax/admin/matching/matches_v2.py`) simplified the old cluttered card and, in doing
so, dropped three groups of information that are no longer reachable anywhere:

1. **Inheritance** — whether the attempt was *based on* a previous match, and if so whether the basing
   was **forced** or **biased**.
2. **Timings** — problem build time and solve time.
3. **Configuration** — supervising/marking CATS limits, marking multiplicity, max project/group
   multiplicities, whether per-faculty limits and programme preferences were applied, the selector
   pool, solver, objective weights, penalties, and convenor-hint settings.

This handoff implements **option 1a: expand-in-place disclosure.** Each match card gains two toggle
buttons that reveal collapsible panels *inside the card*: **Configuration** and **Timing &
provenance**. Chosen because it is the most functional option — several cards' panels can be open at
once for side-by-side comparison, and every value is visible without scrolling or navigating away.

## About the design files

`Matching dashboard - surfacing config.dc.html` in this bundle is a **design reference built in
HTML** — a prototype showing the intended look and behaviour. It is **not** code to ship.

The target codebase is **server-side Flask + Jinja2 + Bootstrap 5.3 + jQuery** (see `CLAUDE.md`).
The task is to reproduce this design **in that stack**, editing the existing card template. Do **not**
introduce React or a new front-end framework.

## Fidelity

**High-fidelity.** Colours, spacing, chip styling, grouping and copy are final. Recreate faithfully
using Bootstrap 5.3 semantic tokens (the project's `.claude/rules/template-colours.md` mandates
Bootstrap semantic colour tokens — **no raw hex** in real templates; the hex in the prototype's tag
pills is only because the prototype has no access to `pclass.make_label`).

---

## Where the code lives

| Concern | File |
|---|---|
| Card HTML template (Jinja2 string `_card`) | `app/ajax/admin/matching/matches_v2.py` |
| Payload builder that renders each card | `matches_dashboard_data()` in the same file |
| Shared presentational macros | `app/templates/admin/matching_workspace/_macros.html` |
| Dashboard page shell + JS loader | `app/templates/admin/matching_workspace/matching_dashboard.html`, `app/static/js/admin/matching_dashboard.js` |
| Model (all fields below are columns/relationships on it) | `MatchingAttempt` in `app/models/matching.py` |

### Key architectural fact — these fields are CHEAP

The card is rendered server-side from **cheap fields only**; the *expensive* statistics bundle
(score, programme-pref/hint counts, δ, CATS, errors/warnings) is deliberately deferred to a separate
per-card AJAX call (`match_statistics_ajax`) — see the docstring on `matches_dashboard_data` and the
`"no new caching"` non-goal in `.prompts/matching-workspace/PLAN.md`.

**Everything in this handoff is a direct column or a simple relationship on `MatchingAttempt`.** It
costs nothing to read. Therefore the two panels **render inline at card-build time, collapsed** — do
**not** add a new AJAX endpoint or deferred fetch for them. This is the whole reason 1a is cheap.

---

## The disclosure mechanism (do this, not a popover)

Use **Bootstrap collapse** driven purely by data attributes:

```html
<button class="btn btn-sm mdash-cfg-toggle" type="button"
        data-bs-toggle="collapse" data-bs-target="#mdash-cfg-{{ m.id }}"
        aria-expanded="false" aria-controls="mdash-cfg-{{ m.id }}">
    <i class="fas fa-sliders-h me-1"></i><span class="mdash-toggle-label">Configuration</span>
    <i class="fas fa-chevron-down ms-2 mdash-toggle-caret"></i>
</button>
...
<div class="collapse mt-3" id="mdash-cfg-{{ m.id }}"> ... panel ... </div>
```

**Why collapse and not a popover:** cards are injected into the page by AJAX (`matching_dashboard.js`
sets `container.innerHTML`). Bootstrap popovers need a JS init step that never runs for
dynamically-inserted nodes — the exact reason the existing `validation_detail` macro
(`_macros.html`) already uses a collapse. Collapse works from data attributes alone, so it survives
the AJAX injection with no extra JS. Follow that precedent.

Two independent collapses per card (Configuration, Timing & provenance) — independent so both can be
open together, and open state on one card does not affect another (ids are namespaced by `m.id`).

### Button open/closed affordance (the reviewed refinement)

Bootstrap toggles `aria-expanded` on the button automatically. Drive **all** the state styling off
that attribute in CSS — no JS:

- **Caret** rotates 180° when open.
- **Fill**: outline when closed, solid fill when open.
- **Label**: "Configuration" ↔ "Hide configuration" (and "Timing & provenance" ↔ "Hide timing &
  provenance").

Because the label text differs, either swap it via two spans toggled by
`[aria-expanded]`/`.collapsed`, or via a `::after`. Suggested scoped CSS (add to the page's
`{% block bodyblock %}` style island in `matching_dashboard.html`, alongside the existing
`.mdash-col` rule):

```css
.mdash-cfg-toggle, .mdash-tim-toggle {
  border: 1px solid var(--bs-primary);
  color: var(--bs-primary);
  background: #fff;
}
.mdash-tim-toggle { border-color: var(--bs-secondary); color: var(--bs-secondary); }
.mdash-cfg-toggle[aria-expanded="true"] { background: var(--bs-primary); color: #fff; }
.mdash-tim-toggle[aria-expanded="true"] { background: var(--bs-secondary); color: #fff; }
.mdash-toggle-caret { transition: transform .15s ease; }
[aria-expanded="true"] .mdash-toggle-caret { transform: rotate(180deg); }
/* label swap */
[aria-expanded="true"] .mdash-toggle-label::after  { content: none; }
```

Simplest label approach: render both words and let CSS decide, e.g.
`<span class="mdash-toggle-label" data-open="Hide configuration" data-closed="Configuration">`
with `content: attr(data-closed)` / `[aria-expanded="true"] … content: attr(data-open)` on a
`::before`. Use whichever of these the team prefers — the requirement is only that the button clearly
reads "this panel is open, click to hide."

---

## Placement in the card

Insert **after** the existing "Compute summary statistics" block and **before** the "Created by …"
footer line in `_card`. A control bar holds the two toggles (and, optionally, keep the recompute
control on the right):

```
[ statistics block, unchanged ]
──────────────────────────────────────  (border-top, pt-2)
[ ⚙ Configuration ▾ ]  [ 🕐 Timing & provenance ▾ ]
   ↳ (collapsed) Configuration panel
   ↳ (collapsed) Timing & provenance panel
Created by Prof David Seery Fri 15 Aug 2025 12:21
```

Only render the toggles when `m.solution_usable` (matching the guard already used for the statistics
block); an unsolved/awaiting-upload attempt has no meaningful configuration to inspect beyond
provenance — team's call whether to still show Timing & provenance there.

---

## Panel 1 — Configuration

A light panel (`background: var(--bs-tertiary-bg)`, `rounded`, `p-3`) containing a responsive grid
(`row g-4`, columns `col-6 col-xl-4`) of labelled groups. Each group has an uppercase caption
(`.cfg-grp-h`: 10px, 700 weight, `letter-spacing:.6px`, `var(--bs-secondary-color)`) and a wrapping
row of chips (`d-flex flex-wrap gap-2`).

**Chip** = pill, `background: var(--bs-tertiary-bg)`, `1px solid var(--bs-border-color)`,
`color: var(--bs-secondary-color)`, `padding:3px 10px`, `font-size:12px`; the **value** inside is
`font-weight:600; color: var(--bs-body-color)`. Boolean/policy chips carry a leading FA icon.

### Groups, field mapping, and formatting

All fields are on `MatchingAttempt`. Decimal columns are `Numeric(8,3)` → format with `'%0.3f'`.
Integer columns render as-is.

**Limits & multiplicities**
| Chip label | Field | Notes |
|---|---|---|
| Supervising CATS | `supervising_limit` | int |
| Marking CATS | `marking_limit` | int |
| Marker multiplicity | `max_marking_multiplicity` | int |
| Max project types | `max_different_all_projects` | `None` ⇒ render "no limit" (not a number) |
| Max group types | `max_different_group_projects` | `None` ⇒ "no limit" |

**Policies**
| Chip | Field | Rule |
|---|---|---|
| Per-faculty limits applied | `ignore_per_faculty_limits` | Applied (green ✔) when **False**; "not applied" when True |
| Programme prefs applied | `ignore_programme_prefs` | Applied (green ✔) when **False** |
| Only submitted selectors | `include_only_submitted` | show when True; else "All selectors" |
| Solver | `solver_name` (property) | e.g. "Gurobi", "CBC", "PuLP-packaged CBC"; append "external" where the name implies it |

> Note the polarity: the columns are `ignore_*`, so **applied = not ignored**. The old UI's green
> "Apply per-faculty limits" / "Apply programme prefs" badges = `ignore_* is False`.

**Objective weights** — all `'%0.3f'`
| Chip | Field |
|---|---|
| Programme | `programme_bias` |
| Bookmark | `bookmark_bias` |
| Levelling | `levelling_bias` |
| Group tension | `intra_group_tension` |
| Sup. pressure | `supervising_pressure` |
| Mark. pressure | `marking_pressure` |

**Penalties** — `'%0.3f'`
| Chip | Field |
|---|---|
| CATS violation | `CATS_violation_penalty` |
| No assignment | `no_assignment_penalty` |

**Convenor hints** — group caption shows enforced/disabled from `use_hints` (green "enforced" when
True). Chips (each `'%0.3f'`, shown as `×value`), with up/down arrow icons:
| Chip | Field | Icon |
|---|---|---|
| Encourage | `encourage_bias` | `fa-arrow-up` (success) |
| Discourage | `discourage_bias` | `fa-arrow-down` (danger) |
| Strong enc. | `strong_encourage_bias` | `fa-angle-double-up` (success) |
| Strong disc. | `strong_discourage_bias` | `fa-angle-double-down` (danger) |

Also surface, as small note chips, `require_to_encourage` ("Require → strong encourage") and
`forbid_to_discourage` ("Forbid → strong discourage") when True — they change how hints behave.
If `use_hints` is False, render the group caption "Convenor hints — disabled" and either dim or omit
the weight chips.

---

## Panel 2 — Timing & provenance

Same light panel; a `d-flex flex-wrap gap-4` of two blocks.

**Based on** (only render the block when `m.base is not None`):
- Link to the base attempt:
  `url_for('admin.matching_workspace', id=m.base.id, view='student', text=text, url=url)` (falls back
  to a plain span if the base is not `solution_usable`), label `m.base.name`, preceded by
  `fa-link`.
- **Inheritance mode badge**, from `m.force_base`:
  - `force_base is True` → **"Forced"** — warning-subtle pill with `fa-lock`
    (`background: var(--bs-warning-bg-subtle); color: var(--bs-warning-text-emphasis)`).
  - `force_base is False` → **"Biased"** — info/secondary-subtle pill (no lock icon).
- **Base bias** chip: `m.base_bias` (`'%0.3f'`) — most relevant when biased, but show for both.

If `m.base is None`, omit the whole "Based on" block (the attempt is not inherited).

**Timings** — two chips using the model's **already-formatted** properties (do not reformat raw
Decimals yourself):
| Chip | Property | Icon |
|---|---|---|
| Build | `m.formatted_construct_time` | `fa-hammer` |
| Solve | `m.formatted_compute_time` | `fa-stopwatch` |

(`formatted_construct_time`/`formatted_compute_time` wrap `format_time(...)` over the raw
`construct_time`/`compute_time` `Numeric(8,3)` columns — see `PuLPMixin` in `matching.py`.)

---

## State management

None beyond Bootstrap collapse's own DOM state (`aria-expanded` + the `.show` class on the panel).
No new JS, no server state, no new endpoint. `matching_dashboard.js` is untouched except that its
existing delegated click handler on `#mdash-cards` must not swallow the new buttons — it only matches
`.mdash-compute-btn`, so there is no conflict.

## Interactions & behavior

- Click a toggle → its panel slides open (Bootstrap collapse default transition), button flips to the
  open style (fill + rotated caret + "Hide …" label). Click again → closes.
- Both panels independent; multiple cards may have panels open simultaneously.
- No hover requirement beyond standard button hover.
- Responsive: config grid is `col-6 col-xl-4`, collapsing to two columns then one on narrow widths;
  chips wrap. The card's existing `.mdash-col` vertical rules already drop below `992px`.

## Design tokens

Use Bootstrap 5.3 semantic tokens only:
- Panel bg: `var(--bs-tertiary-bg)`; borders: `var(--bs-border-color)`.
- Chip text: `var(--bs-secondary-color)`; chip value + body: `var(--bs-body-color)`.
- Applied/enforced/encourage: `text-success` / `var(--bs-success-*)`.
- Discourage / forced inheritance: `var(--bs-danger-*)` / `var(--bs-warning-*-subtle)` +
  `-text-emphasis`.
- Primary toggle: `var(--bs-primary)`; secondary toggle: `var(--bs-secondary)`.
- Group caption: 10px / 700 / `letter-spacing:.6px`. Chip: 12px, `padding:3px 10px`, pill radius.

## Assets

None. Icons are Font Awesome (already loaded app-wide): `fa-sliders-h`, `fa-history`, `fa-chevron-down`,
`fa-link`, `fa-lock`, `fa-hammer`, `fa-stopwatch`, `fa-arrow-up/-down`, `fa-angle-double-up/-down`,
`fa-microchip` (solver, optional).

## Files in this bundle

- `Matching dashboard - surfacing config.dc.html` — the interactive prototype. Option **1a** is the
  left-most card (`#1a`); 1b/1c are alternatives that were **not** chosen and are included only for
  context — implement 1a.
- `screenshots/1a-01-collapsed.png` — default card, both panels closed (outline toggles).
- `screenshots/1a-02-expanded.png` — toggles in the open state (solid fill, rotated caret,
  "Hide …" labels).
- `screenshots/1a-03-panels.png` — the full Configuration and Timing & provenance panels expanded,
  showing chip styling, grouping, and the Forced-inheritance badge.

## Acceptance checklist

- [ ] Two toggle buttons appear per solved card, after the statistics block, before "Created by".
- [ ] Panels render inline & collapsed at page load — no extra network request when expanding.
- [ ] Configuration panel shows all fields in the mapping above, correctly formatted, with the
      `ignore_*` polarity handled (applied = not ignored) and `None` multiplicities shown as
      "no limit".
- [ ] Timing & provenance shows base link + **Forced/Biased** badge + base bias when `m.base`
      exists, and Build/Solve from the `formatted_*` properties.
- [ ] Button clearly indicates open vs closed (fill + caret rotation + "Hide …" label) via
      `[aria-expanded]` CSS, no JS.
- [ ] Multiple cards can have panels open at once; toggling one card does not affect others.
- [ ] No raw hex in the template — Bootstrap semantic tokens only.
