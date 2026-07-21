# 09 — Review fixes: unread encoding, legend placement, selectors chip placement

Follow-up cleanup after the first production rollout. Three separate defects/decisions —
do them together but note each in the commit body.

## A. Make the unread signal legible and single-encoded
**Problem:** on the overview "Journal activity" card and the Journal tab, the unread state
is shown as a row background tint **and** (on the Journal tab) a second time via the Open
button variant (`btn-primary` vs `btn-outline-primary`). With no legend it reads as random
noise, and the double-encoding looks like an inconsistency rather than a signal.

**Fix:**
1. Encode "unread by the current user" with **one** treatment: a subtle row tint + a 3px
   left accent border + a small leading dot (a `.udot`/`unread-row` style, primary blue).
   Apply it on the overview card list items, the Journal-tab rows, and the per-student
   inspector rows — the same class everywhere.
2. Make the **Open** / action button a **single, consistent variant on every row**
   (`btn-sm btn-outline-primary`), regardless of read state. The row treatment alone carries
   the unread signal; the button must not vary by state.
3. Add a small legend (`<span class="udot"></span> = unread by you`) in the footer of the
   Journal tab and the inspector table, matching the selectors-page legend wording.
4. Confirm the tint is driven strictly by `entry.is_read_by(current_user)` from prompt 01 —
   not by recency, row index, or anything else.

## B. Fix the selectors-page legend placement
**Problem:** the "= no entries visible to you / = unread" key rendered full-width **below the
DataTables pagination strip**, which looks like stray footer text.

**Fix:** move the legend into the table toolbar — the row that holds "Show N entries" and the
email buttons (or immediately beneath it, above the table head). It must sit with the table
controls, never under the pagination. Use the same wording/markup as the legend in A.3.

## C. Move the selectors journal control under the student name
**Problem:** the dedicated **Journal** column consumed a full column (~110px) on an already
dense table, even for the many rows with zero visible entries.

**Fix:**
1. Remove the standalone **Journal** column from the selectors table header and DataTables
   `columns` config (re-check column counts/indices line up afterwards).
2. Render the journal indicator chip **under the student name**, in the same cell as the
   existing "Convert / No convert to submitter" sub-line, left-aligned (reuse the
   `journal_indicator` macro from prompt 04). Keep it compact (icon + count + unread dot;
   muted when nothing visible).
3. **Remove the standalone `+` quick-add button from the row.** Quick-add stays available via
   the drawer and via a new "Add journal entry…" item in the row's **Actions** dropdown
   (the menu has room — see the production screenshot). This declutters the name cell and
   removes a mis-click-prone control next to the name link.
4. Keep "View journal…" in the Actions menu pointing at the drawer, plus the secondary
   "Open full journal page" link.

Do **not** apply C to the submitters page — its cards have room for the inline Journal
button, which stays as-is (with the A-consistent unread treatment).

## Acceptance
- Overview card, Journal tab and inspector share one unread treatment; no button-variant
  encoding of read state; legends present and consistent.
- Selectors legend sits with the table controls, not under pagination.
- Selectors table has no Journal column; the chip sits under the name; no standalone `+`;
  Actions menu has "Add journal entry…". Column indices/sorting still correct.
- No regressions to the drawer, quick-add modal, or counts; no console errors.

## Commit
```
git add -A && git commit -m "journal-redesign(09): single unread encoding, selectors legend placement, chip under name"
```
