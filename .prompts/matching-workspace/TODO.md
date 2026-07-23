# Matching Workspace — TODO

Living checklist for the Matching Workspace redesign. See `PLAN.md` (same directory) for the full
plan and rationale. Tick items as they complete; one commit per phase
(`matching-workspace: <imperative summary>`).

**Status:** Phase 0, Phase 1, Phase 2, Phase 3, Phase 4, Phase 5, and Phase 6 complete. Phase 7 not started.

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
- [x] `_faculty_pane.html`
- [x] `match_view_faculty_v2.py` formatter + `match_faculty_view_v2_ajax`
- [x] `_faculty_drawer.html` + `match_faculty_drawer_ajax`
- [x] `_faculty_reassign_modal.html` + `faculty_reassign_ajax` + `POST faculty_reassign_assign`
- [x] Over-limit warning bar; capacity/CATS gauges; binding notes
- [x] Commit

## Phase 4 — Changes tab
- [x] `_changes_pane.html` (summary cards + table + empty state)
- [x] Changes badge count in shell
- [x] Revert (all + per-record) wired to existing routes (whole-attempt via existing
      `revert_match`/`perform_revert_match`; per-record via new `revert_match_record`, applied
      synchronously in the same style as `reassign_match_project`/`reassign_match_marker`)
- [x] Commit

## Phase 5 — Top-level Matches list (consolidated dashboard)
- [x] `matching_dashboard.html` + `matching_dashboard` route (privilege-scoped, standalone page)
- [x] Info banner, Create (root), year selector, match cards with Open → + Actions menu (incl. View distributions)
- [x] `matches_v2_ajax` privilege-scoped feed (root all-for-year vs convenor published-for-pclass)
- [x] `match_statistics_ajax` on-demand (single) + Compute-all
- [x] Repoint `manage_matching` + convenor `audit_matches` entries → `matching_dashboard` (both routes
      now redirect, so every existing `url_for(...)` caller lands in the new dashboard without
      needing to be touched individually — same pattern as the Phase 2 `match_student_view` redirect)
- [x] Commit

## Phase 6 — Review comments
- [x] `MatchingReviewComment` model (+ relationships, `scope_label`, cascades — DB-level
      `ondelete="CASCADE"` on the attempt/record/parent FKs, ORM `delete-orphan` on the
      self-referential parent/replies thread)
- [x] Hand-written Alembic migration (chain tip `b4e7a1d9c3f2` verified; new id `e7f8a9b0c1d2`;
      `body` stored as `LargeBinary` to match the `EncryptedType`/`AesEngine` at-rest encoding used
      by `TicketComment.body`; up/down)
- [x] `match_comments_ajax` + `_comments_panel.html` (Global / By-assignment tabs, threaded list,
      composer; service-layer `comments_data()`/`unresolved_comment_count()` in
      `app/shared/matching_workspace.py`)
- [x] `POST post_match_comment` / `reply_match_comment` / `resolve_match_comment` (WTForms +
      CSRF + `log_db_commit`; `MatchCommentFormFactory`/`MatchCommentReplyForm` in `app/admin/forms.py`)
- [x] Unresolved-count badge on Review-comments button (server-rendered at page load, same as the
      Changes-tab badge)
- [x] Commit

## Phase 7 — Consolidation & polish
- [x] Colour-token compliance pass (verified: no raw hex in workspace templates/v2 formatters/JS
      except the policy-allowed `color: #fff`; swatches via `make_CSS_style`)
- [x] Font Awesome icons (verified: no emoji glyphs remain in workspace templates, v2 formatters, or JS)
- [x] Retire `manage.html`, `audit.html`, superseded `student.html`/`faculty.html`:
      - `match_faculty_view` repointed to a redirect into the workspace (mirrors `match_student_view`);
        this also removed the stray `E731` lambda that lived in its old body
      - deleted templates `admin/matching/manage.html`, `convenor/matching/audit.html`,
        `admin/match_inspector/faculty.html`, `admin/match_inspector/student.html`
      - removed now-dead AJAX routes `matches_ajax`, `audit_matches_ajax`, `match_student_view_ajax`,
        `match_faculty_view_ajax` and their orphaned formatters (`matches.py`, `match_view_faculty.py`,
        `student_view_data`); kept `get_match_student_emails` (used by the live compare feature) and
        `match_inspector/nav.html` (still extended by the live `dists.html`)
      - `manage_matching`, `match_student_view`, `match_faculty_view`, `audit_matches` remain as thin
        redirect shims so existing `url_for(...)` callers and external bookmarks keep working
- [ ] Accessibility (focus, aria on offcanvas/modals) + responsive check
- [ ] `ruff check`/`format`; full end-to-end QA; migration up/down
- [ ] Commit
