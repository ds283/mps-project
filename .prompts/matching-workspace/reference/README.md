# Handoff: MatchingAttempt Admin Workspace

## Overview
This is a redesign of the **project-matching admin workspace** in the MPS (Masters/undergraduate Physics) project-management system. A `MatchingAttempt` is the output of running the optimiser that allocates students to supervised projects. The convenor needs to review that output, inspect it from a student and a faculty angle, make manual corrections (reassign projects, edit supervisor/marker roles), see how the current state diverges from the optimiser baseline, and leave review comments — all before publishing to convenors.

The redesign closes seven gaps in the current UI:
1. **Slow dashboard load** — expensive summary statistics are now computed *on demand per row* (never cached), so the page paints instantly from cheap columns.
2. **Weak student inspector** — a right-hand drawer with quick reassignment, ranked selection, journal preview (with count badge), tickets, and recent emails.
3. **Weak faculty inspector** — a right-hand drawer showing workload/binding constraints, projects offered, and staff-centric alternatives (who ranked this staff #1, who would prefer them, next-highest interested).
4. **No faculty-level reassignment** — a full reassignment workspace with capacity gauges and a ranked candidate pool.
5. **No review comments** — a scoped comments panel (global + per-assignment) with threaded replies and resolve state.
6. **No change tracking** — a Changes tab diffing current state vs the optimiser baseline.
7. **Cleaner tables** — de-emphasised score, dominant colour-coded rank, subtle "modified" pill, two-line supervising column.

## About the Design Files
The file in this bundle (`Matching Workspace.dc.html`) is a **design reference created in HTML** — an interactive prototype showing the intended look and behaviour. It is **not production code to copy directly**. It is a self-contained Design Component (a small custom template runtime with inline styles and a `Component` logic class) used only for prototyping.

The task is to **recreate this design in the target codebase's existing environment**, using its established patterns, component library, and data layer. This app appears to be a server-rendered Django/Bootstrap application (the visual language is Bootstrap 5), so the natural implementation is Django templates + the existing Bootstrap components, with the interactive pieces (drawers, modals, on-demand stat loading, comments) done via the project's existing JS approach (htmx / Turbo / vanilla / Stimulus — whatever is already in use). If a component library is already established, use it rather than porting the inline styles verbatim.

All data in the prototype is **hard-coded sample data** (students, faculty, matches, comments). The real implementation must bind to the actual `MatchingAttempt`, `MatchingRecord`, `EnrollmentRecord`, `ProjectClassConfig`, project/selection, journal, and ticket models.

## Fidelity
**High-fidelity (hifi).** Colours, typography, spacing, and interactions are final and intended to be matched closely — but because the target is a Bootstrap app, prefer the codebase's existing Bootstrap tokens/utilities over the literal hex values where they correspond (they were chosen to match Bootstrap 5 defaults). Exact values are listed under **Design Tokens** for anything that isn't a stock Bootstrap value.

## Global Layout & Chrome

- **Top navbar** — dark (`#1b1e21`), 56px tall, brand "MPS projects management" on the left, nav links + user badge on the right. This is existing app chrome; reuse it as-is. The prototype's version is a static placeholder.
- **Page background** — warm cream `#f6ecd4` (this is the existing app's admin page background; keep whatever the real app uses).
- **Sub-toolbar** — a "◀◀ Return to matching dashboard" back link, then a pill/tab row on the left and a "💬 Review comments" button on the right.
- **Content max width** — content sits in 22px side padding; no artificial max-width in the prototype.

### Primary navigation (pill tabs)
Four views switched by pill buttons (single active state, active = solid blue `#0d6efd` filled, inactive = transparent with blue text):
1. **Student view** (default)
2. **Faculty view**
3. **Changes** — carries a count badge (cyan `#0dcaf0` when >0, grey `#adb5bd` when 0)
4. **Matches** (the dashboard / list of matching attempts)

The "Review comments" button carries a badge with the count of **unresolved** comments.

Each view is a card: white background, 1px blue border (`#0d6efd`), 8px radius, with a solid-blue header bar (white text, 16px).

---

## Screen 1 — Student view (default)

**Purpose:** review every student's allocation, spot poor outcomes (low-ranked allocations, unmet programme prefs), and reassign.

**Layout:**
- **Filter well** (grey `#f4f5f6`, 1px `#e3e6ea` border, 8px radius): three filter groups — "Filter by project class" (chip row), then side-by-side "Filter by project type" and "Filter by hinting status" chip groups. Chips are pill buttons; active = solid blue, inactive = white with grey border. Only the project-class filter is wired in the prototype; type/hint are illustrative.
- **Table** (1px `#dee2e6` border, 6px radius, header row `font-weight:700`, 2px bottom border, zebra striping `#fff` / `#f8f9fa`). Grid columns: `1.6fr 1.5fr 2.1fr 1.7fr .6fr .8fr`.

**Columns:**
1. **Student** — name (blue link, opens drawer). Under it a row of chips: "Show details ›", a journal badge `📖 N` (grey outline, only if journalCount>0), a tickets badge `🎫 N` (amber `#fff3cd`/`#b45309`, only if open tickets), and a `💬` comment button (opens comments panel scoped to this student).
2. **Project class** — colour swatch + class label; cohort line in blue; owner line "◉ {owner}" in grey.
3. **Project** — the assigned project title as a dropdown-style link (`… ▾`) that opens the **unified role editor**. A `MODIFIED` outlined blue pill appears if the assignment differs from baseline. Below: programme-pref status as plain text — green "✓ meets programme prefs" or amber "⚠ programme prefs not met".
4. **Markers** — each marker name as a `… ▾` link opening the role editor.
5. **Rank** — **dominant** number: 24px bold, colour-coded (green `#198754` for #1–2, orange `#fd7e14` for #3, red `#dc3545` for #4+), with a muted "preference" caption. This is the emphasised metric.
6. **Score** — de-emphasised: small muted grey text (`#6c757d`, 13px).

Footer: "Showing N of M entries".

> **Note on rank vs score:** rank is the student's preference position for their allocated project (1 = top choice). Score in the prototype is derived as `1/rank`. In production use the real objective contribution.

### Student drawer (right offcanvas, 520px)
Opens on student name / "Show details". Slides in from the right (`drawerIn` keyframe, 0.2s), dark scrim behind (`rgba(0,0,0,.35)`). Sections (each a white card):
- **Header** — name as `mailto:` link (22px blue), project-class swatch + label, convenor "◉ {name}".
- **Assigned project** — title + owner, a "Modified" cyan pill if changed. **Quick reassignment**: one button per ranked selection (`#rank  Project · owner`), the current one highlighted (blue border, `#e7f1ff` fill), an "· automatch" tag on the optimiser's original pick. Clicking sets the assignment. Plus a full-width "Open unified role editor…" button.
- **Ranked selection** — table of the student's ranked choices (rank / project / owner / hint badge). "Encourage" hint = solid green badge. Actions: "Edit selection…", "📖 View journal…".
- **Journal preview** — count of accessible entries in the header; each entry = title, date, snippet. Empty state "No accessible journal entries."
- **Tickets in scope** — only if the student has tickets; amber-bordered card; each = title link, opened date, status badge (Open = amber, Resolved = green).
- **Recent emails** — date + subject rows.

---

## Screen 2 — Faculty view

**Purpose:** review allocations per staff member; see supervising/marking load and reassign at the faculty level.

**Layout:** filter well (project-class chips only), then a table with grid `1.3fr 2.2fr 2.2fr 1.3fr`.

**Columns:**
1. **Name** — name link (opens faculty drawer). Under it: "offered" lines per project class (`swatch  FYP BSc · offered N`), a "Show details ›" link, then two buttons: "Reassign…" (blue outline, opens the reassignment workspace) and `💬` (opens comments scoped to this staff member).
2. **Supervising** — grouped by project class. Each group has an uppercase grey label, then per student: swatch + student name (blue link → role editor) + a programme-pref tick (green `✔`) / cross (amber `✖`) badge if set, with the project title beneath (muted, indented).
3. **Marking** — grouped by project class; student name + project, no links.
4. **Workload** — "Supervising N", "Marking N", "Total N" (total in blue). A binding-constraint pill (`⚖️ …`, amber) if any limit is binding.

Footer: "Showing N of M entries".

### Faculty drawer (right offcanvas, 560px)
Sections:
- **Workload & binding constraints** — supervising and marking CATS bars (`value / limit CATS`). Bar colour: green <85%, orange 85–99%, red ≥100%. If a limit is binding, a red note ("At supervising CATS limit — no further supervisees…", "At marking CATS limit (EnrollmentRecord)…"). Then a list of constraint callouts: CATS constraints amber (`#fff3cd`/`#664d03`, ⚖️), capacity constraints red (`#f8d7da`/`#842029`, 🚧).
- **Projects offered in this matching** — per project: swatch + title, a capacity badge (red "FULL n / cap" if full+enforced, amber "n / cap cap" if enforced, grey "n allocated" if not enforced), "{selected} selectors chose this · allocated:", then allocated-student chips (blue `#e7f1ff`).
- **Who else could be allocated here?** — header with a "Reassignment workspace →" button. Three staff-centric lists:
  - "Ranked a {surname} project #1 but allocated elsewhere" (with "+ N more" overflow)
  - "Would prefer a {surname} project to their current allocation"
  - "Next-highest interested (would take a freed place)"

### Faculty reassignment workspace (centered modal, 920px)
Opened from the drawer button or the row "Reassign…" button (which opens drawer + workspace). Blue header "Reassignment workspace — {name}", scrim `rgba(0,0,0,.45)`, scrollable.
- **Over-limit warning bar** (only when the supervising limit is already binding): amber `#fff3cd`/`#664d03`, "⚠️ **Over limit.** Assigning another supervisee here will exceed the supervising CATS limit (n/limit)." Overassignment is **allowed** (mirrors the role editor); the excess is meant to surface downstream as a validation warning, not blocked here.
- **Left column — capacity + assigned:** supervising & marking CATS gauges (same bar colours), binding notes; per-project capacity gauges (bar + "n/cap" + enforcement note); "Currently assigned (N)" list (student + project, "pending" cyan badge for newly added).
- **Right column — assignable pool (N):** intro line, then candidate cards ranked by preference strength. Each card: a coloured tone dot (green = ranked #1, blue = would-prefer, grey = next-highest), name, "why" line, current-allocation line, and an "Assign →" button (blue). Assigning adds the student to the pending list.
- **Footer:** right-aligned "Done" button (blue).

---

## Screen 3 — Changes tab

**Purpose:** show how the current match diverges from the optimiser's original allocation.

- Header bar with a "Revert all" outline button.
- **Summary cards** (3): "field changes" count, "students affected" count, and "objective score (optimizer → current)" showing `scoreFrom → scoreTo` (green → blue dots).
- **Table** grid `1fr .7fr 1.9fr 1.9fr 1.1fr .7fr`: Student / Field (grey pill: Project | Markers | Supervisors) / Optimizer baseline (red, strikethrough) / Current (green) / Edited by (name + timestamp) / Revert button.
- **Empty state:** big ✓, "This match matches the optimizer output exactly." with a hint to reassign to see changes.

Change rows are **derived** by diffing each assignment against its stored baseline (project rank, marker set, supervisor set) — so the tab stays consistent after any reassignment. The prototype seeds three illustrative edits.

---

## Screen 4 — Matches (dashboard)

**Purpose:** list all matching attempts with fast load.

- Header "Automatic matching" + a "Compute all statistics" button.
- **Info banner** (blue `#e7f1ff`): "⚡ **Fast first load, no cache.** … expensive summary statistics … are computed on demand per row — never cached, so there is nothing to invalidate after an edit." **This is the key performance behaviour to preserve.**
- **Match cards** (1px border, 8px radius; the "current" match gets a blue border + subtle blue glow). Grid `1.4fr 1fr 1fr 3fr`:
  1. Name link + tag chips (DS = orange, HSDS = amber, MPP = green, class tags = light blue).
  2. Status ("✔ Optimal solution"), "ⓘ Modified" / "✔ Published" flags.
  3. "● Original {score}" (green) / "● Current {score}" (blue), then "N sel · N sup · N mark · N proj".
  4. **Actions ▾** dropdown (grey button) with the action menu; then the on-demand statistics area:
     - Default: a dashed "Compute summary statistics ↻" button.
     - Loading: shimmering placeholder chips.
     - Loaded: stat chips (matched programme prefs = green, failed = amber if >0 else grey, satisfied hints = grey, δ range, CATS range).
     - "Created by ◉ {name} {when}".
     - Error / warning summary chips (red "N errors ›", amber "N warnings ›") that toggle an expandable detail panel listing each error/warning.

**Actions menu items:** Inspect: student view · Inspect: faculty view · View distributions · Compare to… · Publish to convenors · Duplicate match · Rename… · Download CSV · Delete…

---

## Unified role editor (modal, 640px)
Shared by both views (opened from project/marker links or the drawer button). Blue header "Edit roles for {name} (Submission Period #1)".
- **Assigned project** — `<select>` of the student's ranked selections.
- **Supervisors** — token chips (blue) with remove ✕; "+ Add supervisor…" select drawing from the faculty roster.
- **Markers (from assessor pool)** — token chips (grey) with remove ✕; "+ Add marker…" select.
- Footer: Cancel (outline) + "Save changes" (blue). Saving recomputes the `changed` flag by diffing against baseline.

Overassignment (multiple supervisors) is allowed; it surfaces as a validation warning elsewhere, not blocked here.

## Comments panel (right offcanvas, 440px)
- Two tabs: "Global (N)" and "By assignment (N)" (underline-active style).
- Each comment: avatar (initials), author, timestamp, optional scope pill ("On: {student/staff}"), body, threaded replies (indented, left-border), and "Reply" / "Resolve" (or "✔ Resolved — reopen") actions. Resolved comments get a green-tinted background.
- Composer at the bottom: when on the assignment tab, a "Scoped to: {label}" line; textarea ("Record a change or a desired change…") + "Post comment" button. New comments prepend to the list; unresolved by default.

---

## Interactions & Behavior
- **View switching** — pill tabs swap the single visible view (client state `view`).
- **Drawers/modals** — slide in from the right (`@keyframes drawerIn`, translateX 100%→0, 0.2s ease) with a fade-in scrim (`@keyframes fadeIn`, 0.15s). Clicking the scrim closes; clicking inside stops propagation.
- **On-demand stats** — per-row "Compute…" sets a loading flag, then (simulated ~650ms) a loaded flag; "Compute all" does every row (~700ms). In production these fire the real stat queries; never cache the result.
- **Reassignment** (student quick / role editor / faculty workspace) — mutates the assignment, sets `changed=true` by diffing baseline, which feeds both the "Modified" pills and the Changes tab and the Changes badge count.
- **Comments** — resolve/reopen toggles a flag; posting prepends; the unresolved count drives the header badge.
- **Actions/menus** — one dropdown open at a time; opening a match's detail closes its menu.

## State Management
Client state needed (however the real app models it):
- `view` — which of the 4 tabs is active.
- Filters: `fPclass`, `fType`, `fHint`.
- Open overlays: `drawerSel` (student id), `drawerFac` (faculty id), `roleEditor` (editing context), `facReassign` (faculty id), `commentsOpen`, `openMatchDetail`, `openMatchMenu`.
- `assignments` — current allocation per student (projectRank, project, owner, supervisors[], markers[], changed) + an immutable `original` baseline for diffing.
- `facAssigned` — pending faculty-workspace additions.
- `statsLoaded` / `statsLoading` — per-match on-demand stat flags.
- `comments` — list with scope, replies, resolved.
- Composer: `newComment`, `ctab` (global|assignment), `commentTarget`.

Data fetching: dashboard renders from cheap columns immediately; expensive per-match statistics are fetched lazily and never cached. Everything else binds to the matching attempt's records.

## Design Tokens
These track Bootstrap 5 — use the codebase's existing variables where they map.
- **Colors:** primary blue `#0d6efd` (hover `#0a58ca`); success green `#198754` / text `#0f5132`; warning amber fill `#fff3cd`, border `#ffe69c`, text `#664d03` / `#b45309`; danger red `#dc3545`, fill `#f8d7da`, border `#f5c2c7`, text `#842029`; orange `#fd7e14`; cyan `#0dcaf0`; info-blue fill `#e7f1ff`, border `#b6d4fe`; navbar `#1b1e21`; page bg `#f6ecd4`; card grey `#f4f5f6`; borders `#dee2e6` / `#e3e6ea` / `#eef0f2` / `#f1f3f5`; zebra `#f8f9fa`; muted text `#6c757d` / `#adb5bd` / `#495057`; body text `#212529`.
- **Project-class swatches:** FYP BSc `#9ec5fe`, FYP MPhys `#d8b4fe`, MPP `#0f5132`.
- **Radius:** 5–6px (buttons/badges/inputs), 7–8px (cards/wells), 10px (modals).
- **Typography:** system stack (`-apple-system, "Segoe UI", Roboto, …`). Sizes: body 13px, small 11–12px, card headers 16px, drawer name 22px, dominant rank 24px, uppercase group labels 10.5px with 0.4px tracking.
- **Shadows:** drawers `-8px 0 30px rgba(0,0,0,.25)`; modals `0 20–24px 60–70px rgba(0,0,0,.3)`; dropdowns `0 10px 28px rgba(0,0,0,.18)`.
- **Progress bars:** 7–8px tall, `#e9ecef` track, 4px radius; fill green/orange/red by threshold (85% / 100%).
- **Animations:** `drawerIn` 0.2s ease, `fadeIn` 0.15s ease.

## Assets
No image or icon assets — all glyphs are Unicode/emoji (◉ ▾ ✔ ✖ ⚖️ 🚧 📖 🎫 💬 ⚡ ✓ ↻ ◀◀). In production, prefer the existing icon set (Bootstrap Icons / Font Awesome — whatever is in use) over emoji for the functional icons.

## Data model touchpoints (for the implementer)
The sample data maps to these real concepts: `MatchingAttempt` (a match), `MatchingRecord` (a student's allocation within it), student `SelectionRecord` + ranked `SelectionRecord` items, `ProjectClassConfig` / project classes (FYP BSc / FYP MPhys / MPP), project capacity + enforcement flags, supervising vs marking **CATS** limits (marking limit lives on `EnrollmentRecord`), programme-preference matching, selection **hints** (encourage/forbid), student **journal** entries and **tickets**, and the optimiser **objective score**. Validation errors/warnings are the existing matching-attempt validation output.

## Screenshots
Reference renders of each view live in `screenshots/`:
- `01-student-view.png` — Student view (table, filters, rank/score)
- `02-faculty-view.png` — Faculty view (supervising/marking/workload)
- `03-changes.png` — Changes tab (diff vs optimizer baseline)
- `04-matches-dashboard.png` — Matches dashboard (on-demand stats loaded)
- `05-faculty-reassignment.png` — Faculty reassignment workspace (capacity gauges + candidate pool, over-limit state)
- `06-student-drawer.png` — Student inspector drawer (quick reassignment)
- `07-comments.png` — Review comments panel

## Files
- `Matching Workspace.dc.html` — the full interactive prototype (all four views + drawers + modals + comments). Sample data and all logic live in the `<script>` block at the bottom.
- `support.js` — the prototype runtime only; **not needed** for the real implementation (do not port it).
