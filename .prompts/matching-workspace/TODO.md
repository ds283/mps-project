# Matching Workspace — TODO

Living checklist for the Matching Workspace redesign. See `PLAN.md` (same directory) for the full
plan and rationale. Tick items as they complete; one commit per phase
(`matching-workspace: <imperative summary>`).

**Status:** Phase 0, Phase 1, and Phase 2 complete. Phase 3 not started.

---

## Phase 0 — Planning
- [x] Write `.prompts/matching-workspace/PLAN.md`
- [x] Write `.prompts/matching-workspace/TODO.md`
- [x] Commit

## Phase 1 — Service layer (`app/shared/matching_workspace.py`)
- [x] `student_row(attempt, record)`
- [x] `faculty_row(attempt, fac)`
- [x] `faculty_drawer(attempt, fac)`
- [x] `faculty_assignable_pool(attempt, fac)` (3 tone-coded, deduplicated lists)
- [x] `binding_constraints(attempt, fac)`
- [x] `student_drawer(attempt, record)` (selections, journal, tickets, emails)
- [x] `changes_data(attempt)` + `changes_count(attempt)` (live vs `original_*`/`original_roles`)
- [x] `dashboard_statistics(attempt)`
- [x] Commit

## Phase 2 — Detail shell + Student tab
- [x] `workspace.html` detail shell (Return-to-matches, match-name heading, 3 pills + Changes badge, Review-comments button)
- [x] `_macros.html` (pills, swatches, bars, pref badges, chips)
- [x] Route `matching_workspace/<id>` (student/faculty/changes view dispatch — faculty/changes
      render placeholder panes until Phases 3/4 land)
- [x] `_student_pane.html` (filter well + table + footer)
- [x] `match_view_student_v2.py` formatter + `match_student_view_v2_ajax`
- [x] `_student_drawer.html` + `match_student_drawer_ajax`
- [x] `_role_editor_modal.html` + `match_role_editor_ajax` + `POST edit_match_roles`
- [x] Quick-reassignment buttons wired to existing reassign routes
- [x] Repoint `match_student_view` entry → workspace (legacy route now redirects, so every
      existing `url_for('admin.match_student_view', ...)` caller lands in the new workspace
      without needing to be touched individually)
- [x] Commit

## Phase 3 — Faculty tab + reassignment
- [ ] `_faculty_pane.html`
- [ ] `match_view_faculty_v2.py` formatter + `match_faculty_view_v2_ajax`
- [ ] `_faculty_drawer.html` + `match_faculty_drawer_ajax`
- [ ] `_faculty_reassign_modal.html` + `faculty_reassign_ajax` + `POST faculty_reassign_assign`
- [ ] Over-limit warning bar; capacity/CATS gauges; binding notes
- [ ] Commit

## Phase 4 — Changes tab
- [ ] `_changes_pane.html` (summary cards + table + empty state)
- [ ] Changes badge count in shell
- [ ] Revert (all + per-record) wired to existing routes
- [ ] Commit

## Phase 5 — Top-level Matches list (consolidated dashboard)
- [ ] `matching_dashboard.html` + `matching_dashboard` route (privilege-scoped, standalone page)
- [ ] Info banner, Create (root), year selector, match cards with Open → + Actions menu (incl. View distributions)
- [ ] `matches_v2_ajax` privilege-scoped feed (root all-for-year vs convenor published-for-pclass)
- [ ] `match_statistics_ajax` on-demand (single) + Compute-all
- [ ] Repoint `manage_matching` + convenor `audit_matches` entries → `matching_dashboard`
- [ ] Commit

## Phase 6 — Review comments
- [ ] `MatchingReviewComment` model (+ relationships, `scope_label`, cascades)
- [ ] Hand-written Alembic migration (verify chain tip + new id; utf8_bin; up/down)
- [ ] `match_comments_ajax` + `_comments_panel.html`
- [ ] `POST post_match_comment` / `reply_match_comment` / `resolve_match_comment` (WTForms + CSRF + log_db_commit)
- [ ] Unresolved-count badge on Review-comments button
- [ ] Commit

## Phase 7 — Consolidation & polish
- [ ] Colour-token compliance pass (Bootstrap/`common.css` tokens; no raw hex; swatches via model)
- [ ] Font Awesome icons (replace prototype emoji)
- [ ] Retire `manage.html`, `audit.html`, superseded `student.html`/`faculty.html` (or thin redirects)
- [ ] Accessibility (focus, aria on offcanvas/modals) + responsive check
- [ ] `ruff check`/`format`; full end-to-end QA; migration up/down
- [ ] Commit
