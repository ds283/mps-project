#!/usr/bin/env python3
"""
inject_presentation_marks.py
-----------------------------
Populate MarkingReport instances from an external presentations spreadsheet.

Connects directly to the database via a SQLAlchemy URI — no Flask app context
needed.  Designed to run locally against a production MariaDB reached over an
SSH tunnel.

TUNNEL SETUP
------------
Open an SSH tunnel on your local machine before running the script:

    ssh -N -L 13306:127.0.0.1:3306 <user>@mps026298.phys.susx.ac.uk

Then pass the tunnelled URI:

    --db-uri "mysql+pymysql://<user>:<password>@127.0.0.1:13306/<dbname>"

PyMySQL is the recommended pure-Python driver:

    pip install pymysql sqlalchemy pandas openpyxl

USAGE
-----
    python inject_presentation_marks.py \\
        --db-uri "mysql+pymysql://user:pass@127.0.0.1:13306/mpsdb" \\
        --spreadsheet combined_scores.xlsx \\
        --bsc-workflow <id or name> \\
        --mphys-workflow <id or name> \\
        [--dry-run] \\
        [--verbose]

The URI can also be supplied via the environment variable DB_URI to avoid
exposing credentials in shell history:

    export DB_URI="mysql+pymysql://user:pass@127.0.0.1:13306/mpsdb"
    python inject_presentation_marks.py --spreadsheet ... --bsc-workflow ... --mphys-workflow ...

OPTIONS
-------
--db-uri            SQLAlchemy database URI (overrides DB_URI env var).
--spreadsheet       Path to the .xlsx file.
--bsc-workflow      ID (integer) or name of the BSc MarkingWorkflow.
--mphys-workflow    ID (integer) or name of the MPhys MarkingWorkflow.
--dry-run           Report what would happen; make no database changes.
--verbose           Print a line for every MarkingReport processed.

EXIT CODES
----------
0 = success (or dry-run with no errors)
1 = one or more errors

DATA MODEL PATH
---------------
Spreadsheet row (email) -> users -> student_data -> submitting_students
  -> submission_records -> submitter_reports (per workflow)
     -> marking_reports (per assessor submission_role)

REPORT JSON (matches MarkingScheme schema)
------------------------------------------
{
    "duration":      <float>,
    "content":       <float>,
    "structure":     <float>,
    "presentation":  <float>,
    "visual":        <float>,
    "understanding": <float>,
    "justification": ""          (blank — not captured this year)
}
Grade = (content + structure + presentation + visual + understanding) * 5.0

Feedback1/Feedback2 columns -> MarkingReport.feedback_positive (feedback_improvement left blank).
Both report_submitted and feedback_submitted are set True on each MarkingReport.
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Optional, Tuple

import pandas as pd
from sqlalchemy import create_engine, text, MetaData, Table, select, and_, func
from sqlalchemy.orm import Session


# ---------------------------------------------------------------------------
# Role constant — mirrors SubmissionRoleTypesMixin.ROLE_PRESENTATION_ASSESSOR
# ---------------------------------------------------------------------------
ROLE_PRESENTATION_ASSESSOR = 2


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_args():
    p = argparse.ArgumentParser(
        description="Inject presentation marks into MarkingReport instances.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--db-uri",
        dest="db_uri",
        default=None,
        help="SQLAlchemy URI, e.g. mysql+pymysql://user:pass@127.0.0.1:13306/db  (falls back to DB_URI environment variable)",
    )
    p.add_argument("--spreadsheet", required=True, help="Path to the .xlsx file")
    p.add_argument(
        "--bsc-workflow",
        required=True,
        dest="bsc_workflow",
        help="ID (integer) or name of the BSc MarkingWorkflow",
    )
    p.add_argument(
        "--mphys-workflow",
        required=True,
        dest="mphys_workflow",
        help="ID (integer) or name of the MPhys MarkingWorkflow",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="Report only; make no database changes",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Print a line for every processed MarkingReport",
    )
    p.add_argument(
        "--role-constant",
        type=int,
        default=ROLE_PRESENTATION_ASSESSOR,
        dest="role_constant",
        help=f"Integer value of ROLE_PRESENTATION_ASSESSOR in your deployment "
        f"(default: {ROLE_PRESENTATION_ASSESSOR}). "
        f"Verify with: SELECT DISTINCT role FROM submission_roles;",
    )
    return p.parse_args()


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------


def _connect(uri: str):
    """Return (engine, session, metadata-with-all-tables-reflected)."""
    engine = create_engine(uri, future=True)
    meta = MetaData()
    meta.reflect(bind=engine)
    session = Session(engine)
    return engine, session, meta


def _tbl(meta: MetaData, name: str) -> Table:
    if name not in meta.tables:
        raise SystemExit(f"ERROR: Table '{name}' not found in database. Check your URI and database name.")
    return meta.tables[name]


def _find_workflow(session: Session, meta: MetaData, spec: str):
    """Resolve a MarkingWorkflow row by integer ID or by name (case-insensitive)."""
    t = _tbl(meta, "marking_workflows")
    try:
        wid = int(spec)
        row = session.execute(select(t).where(t.c.id == wid)).mappings().first()
        if row is None:
            raise SystemExit(f"ERROR: No MarkingWorkflow with id={wid}")
        return row
    except ValueError:
        pass
    row = session.execute(select(t).where(func.lower(t.c.name) == spec.lower())).mappings().first()
    if row is None:
        raise SystemExit(f"ERROR: No MarkingWorkflow with name matching '{spec}'")
    return row


def _get_marking_event(session: Session, meta: MetaData, event_id: int):
    t = _tbl(meta, "marking_events")
    return session.execute(select(t).where(t.c.id == event_id)).mappings().first()


def _get_config(session: Session, meta: MetaData, config_id: int):
    t = _tbl(meta, "project_class_config")
    return session.execute(select(t).where(t.c.id == config_id)).mappings().first()


def _find_user_by_email(session: Session, meta: MetaData, email: str):
    t = _tbl(meta, "users")
    return session.execute(select(t).where(func.lower(t.c.email) == email.strip().lower())).mappings().first()


def _get_student_data(session: Session, meta: MetaData, user_id: int):
    """Return the student_data row for a given user_id (id column is the FK to users)."""
    t = _tbl(meta, "student_data")
    return session.execute(select(t).where(t.c.id == user_id)).mappings().first()


def _parse_assessor_name(full_name: str) -> Tuple[str, str]:
    """Split 'First Last' into (first, last); last name may be multi-word."""
    parts = full_name.strip().split()
    if len(parts) < 2:
        return full_name.strip(), ""
    return parts[0], " ".join(parts[1:])


def _find_user_by_name(session: Session, meta: MetaData, full_name: str) -> Tuple[Optional[object], Optional[str]]:
    """
    Match 'First Last' to a users row.
    Prefers faculty_data-linked users when the name is ambiguous.
    Returns (row_or_None, warning_or_None).
    """
    first, last = _parse_assessor_name(full_name)
    if not first or not last:
        return None, f"Cannot parse assessor name '{full_name}' into first + last"

    t = _tbl(meta, "users")
    matches = (
        session.execute(
            select(t).where(
                and_(
                    func.lower(t.c.first_name) == first.lower(),
                    func.lower(t.c.last_name) == last.lower(),
                )
            )
        )
        .mappings()
        .all()
    )

    if not matches:
        return None, f"No User found matching name '{full_name}'"

    if len(matches) == 1:
        return matches[0], None

    # Prefer faculty-linked accounts
    fd = _tbl(meta, "faculty_data")
    faculty_ids = {row.id for row in session.execute(select(fd.c.id).where(fd.c.id.in_([u["id"] for u in matches]))).mappings().all()}
    faculty_matches = [u for u in matches if u["id"] in faculty_ids]

    if len(faculty_matches) == 1:
        return faculty_matches[0], (f"Ambiguous name '{full_name}' ({len(matches)} users); resolved to faculty user id={faculty_matches[0]['id']}")

    ids = ", ".join(str(u["id"]) for u in matches)
    return None, (f"Ambiguous name '{full_name}' — {len(matches)} users matched (ids: {ids}); cannot resolve automatically")


def _find_submission_record(session: Session, meta: MetaData, config_id: int, student_data_id: int):
    """
    Return the SubmissionRecord for this student within the given ProjectClassConfig.
    Path: submission_records -> owner (submitting_students) filtered by config_id and student_id.
    """
    sr = _tbl(meta, "submission_records")
    ss = _tbl(meta, "submitting_students")
    return (
        session.execute(
            select(sr)
            .join(ss, sr.c.owner_id == ss.c.id)
            .where(
                and_(
                    ss.c.config_id == config_id,
                    ss.c.student_id == student_data_id,
                )
            )
        )
        .mappings()
        .first()
    )


def _find_submission_role(
    session: Session,
    meta: MetaData,
    submission_id: int,
    user_id: int,
    role_type: int,
):
    t = _tbl(meta, "submission_roles")
    return (
        session.execute(
            select(t).where(
                and_(
                    t.c.submission_id == submission_id,
                    t.c.user_id == user_id,
                    t.c.role == role_type,
                )
            )
        )
        .mappings()
        .first()
    )


def _find_submitter_report(
    session: Session,
    meta: MetaData,
    record_id: int,
    workflow_id: int,
):
    t = _tbl(meta, "submitter_reports")
    return session.execute(select(t).where(and_(t.c.record_id == record_id, t.c.workflow_id == workflow_id))).mappings().first()


def _find_marking_report(
    session: Session,
    meta: MetaData,
    role_id: int,
    submitter_report_id: int,
):
    t = _tbl(meta, "marking_reports")
    return (
        session.execute(
            select(t).where(
                and_(
                    t.c.role_id == role_id,
                    t.c.submitter_report_id == submitter_report_id,
                )
            )
        )
        .mappings()
        .first()
    )


# ---------------------------------------------------------------------------
# Grade / report helpers
# ---------------------------------------------------------------------------


def _safe_float(v) -> float:
    try:
        if pd.isna(v):
            return 0.0
    except (TypeError, ValueError):
        pass
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _build_report_json(
    duration,
    content,
    structure,
    presentation,
    visual,
    understanding,
) -> str:
    """
    Build the JSON blob stored in MarkingReport.report.
    Current schema: {"fields": {<key>: <value>, ...}}
    'justification' is blank — not captured this year.
    'validation_failures' is omitted (optional per schema).
    """
    return json.dumps(
        {
            "fields": {
                "duration": _safe_float(duration),
                "content": _safe_float(content),
                "structure": _safe_float(structure),
                "presentation": _safe_float(presentation),
                "visual": _safe_float(visual),
                "understanding": _safe_float(understanding),
                "justification": "",
            }
        }
    )


def _compute_grade(content, structure, presentation, visual, understanding) -> float:
    return (_safe_float(content) + _safe_float(structure) + _safe_float(presentation) + _safe_float(visual) + _safe_float(understanding)) * 5.0


# ---------------------------------------------------------------------------
# Core injection logic for a single assessor slot
# ---------------------------------------------------------------------------


def _process_assessor(
    *,
    session: Session,
    meta: MetaData,
    sub_record,
    workflow,
    assessor_user,
    slot_index: int,
    role_type: int,
    duration,
    content,
    structure,
    presentation,
    visual,
    understanding,
    feedback_positive: str,
    now: datetime,
    dry_run: bool,
    verbose: bool,
    errors: list,
    warnings: list,
    student_email: str,
) -> bool:
    """Process one (student, assessor) pair.  Returns True if no fatal error."""

    t_roles = _tbl(meta, "submission_roles")
    t_sr = _tbl(meta, "submitter_reports")
    t_mr = _tbl(meta, "marking_reports")

    # --- Locate SubmissionRole ---
    role = _find_submission_role(session, meta, sub_record["id"], assessor_user["id"], role_type)

    if role is None:
        msg = (
            f"[{student_email}] Assessor{slot_index} '{assessor_user['email']}': "
            f"no PRESENTATION_ASSESSOR SubmissionRole on submission_record id={sub_record['id']}"
        )
        if dry_run:
            errors.append(msg)
            return False
        warnings.append(f"{msg} — creating missing SubmissionRole")
        result = session.execute(
            t_roles.insert().values(
                submission_id=sub_record["id"],
                user_id=assessor_user["id"],
                role=role_type,
                mute=False,
                prompt_after_event=True,
                prompt_at_fixed_time=False,
                prompt_delay=1,
                prompt_in_reminder=True,
            )
        )
        session.flush()
        role_id = result.inserted_primary_key[0]
        role = _find_submission_role(session, meta, sub_record["id"], assessor_user["id"], role_type)

    # --- Locate SubmitterReport ---
    sr = _find_submitter_report(session, meta, sub_record["id"], workflow["id"])

    if sr is None:
        msg = (
            f"[{student_email}] No SubmitterReport for submission_record id={sub_record['id']} in workflow '{workflow['name']}' (id={workflow['id']})"
        )
        if dry_run:
            errors.append(msg)
            return False
        warnings.append(f"{msg} — creating missing SubmitterReport")
        # NOT_READY = 999 (SubmitterReportWorkflowStates)
        session.execute(
            t_sr.insert().values(
                record_id=sub_record["id"],
                workflow_id=workflow["id"],
                workflow_state=999,
                out_of_tolerance=False,
                convenor_intervention=False,
            )
        )
        session.flush()
        sr = _find_submitter_report(session, meta, sub_record["id"], workflow["id"])

    # --- Locate or create MarkingReport ---
    mr = _find_marking_report(session, meta, role["id"], sr["id"])

    report_json = _build_report_json(duration, content, structure, presentation, visual, understanding)
    grade = _compute_grade(content, structure, presentation, visual, understanding)

    def _filter_cols(vals: dict) -> dict:
        """
        Strip keys that don't exist as columns in the reflected marking_reports table.
        This makes the script robust to pending migrations (columns present in the model
        but not yet applied to the database).  Skipped columns are reported as warnings.
        """
        present = {c.name for c in t_mr.columns}
        filtered, skipped = {}, []
        for k, v in vals.items():
            if k in present:
                filtered[k] = v
            else:
                skipped.append(k)
        if skipped:
            warnings.append(
                f"[{student_email}] Assessor{slot_index}: column(s) not present in "
                f"marking_reports table (pending migration?): {', '.join(skipped)} — skipped"
            )
        return filtered

    if mr is None:
        msg = f"[{student_email}] Assessor{slot_index}: no MarkingReport for role id={role['id']}, submitter_report id={sr['id']}"
        if dry_run:
            errors.append(msg)
            return False
        warnings.append(f"{msg} — creating missing MarkingReport")
        insert_vals = _filter_cols(
            {
                "role_id": role["id"],
                "submitter_report_id": sr["id"],
                "report": report_json,
                "distribution_state": 3,  # NOT_REQUIRED — no email needed for ROLE_PRESENTATION_ASSESSOR
                "report_submitted": True,
                "grade": grade,
                "grade_submitted_by_id": None,
                "grade_submitted_timestamp": now,
                "feedback_positive": feedback_positive,
                "feedback_improvement": None,
                "feedback_submitted": True,
                "feedback_timestamp": now,
                "weight": 1,
            }
        )
        session.execute(t_mr.insert().values(**insert_vals))
    else:
        label = f"[{student_email}] Assessor{slot_index} '{assessor_user['email']}'"
        if verbose:
            action = "DRY-RUN update" if dry_run else "updating"
            print(f"  [OK] {label}: {action} MarkingReport id={mr['id']}, grade={grade:.1f}")
        if not dry_run:
            update_vals = {
                "report": report_json,
                "grade": grade,
                "report_submitted": True,
                "distribution_state": 3,  # NOT_REQUIRED — no email needed for ROLE_PRESENTATION_ASSESSOR
                "feedback_positive": feedback_positive,
                "feedback_improvement": None,
                "feedback_submitted": True,
            }
            if mr["grade_submitted_timestamp"] is None:
                update_vals["grade_submitted_timestamp"] = now
            if mr["feedback_timestamp"] is None:
                update_vals["feedback_timestamp"] = now
            session.execute(t_mr.update().where(t_mr.c.id == mr["id"]).values(**_filter_cols(update_vals)))

    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    args = _parse_args()

    db_uri = args.db_uri or os.environ.get("DB_URI")
    if not db_uri:
        raise SystemExit(
            "ERROR: No database URI supplied.  Use --db-uri or set the DB_URI "
            "environment variable.\n\n"
            "Example (SSH tunnel on local port 13306):\n"
            "  ssh -N -L 13306:127.0.0.1:3306 <user>@mps026298.phys.susx.ac.uk\n"
            "  export DB_URI='mysql+pymysql://user:pass@127.0.0.1:13306/mpsdb'\n"
            "  python inject_presentation_marks.py --spreadsheet ... --bsc-workflow ... --mphys-workflow ..."
        )

    role_type: int = args.role_constant
    dry_run: bool = args.dry_run
    verbose: bool = args.verbose

    if dry_run:
        print("=== DRY RUN — no database changes will be made ===\n")

    # Connect
    print(f"Connecting to database...")
    try:
        engine, session, meta = _connect(db_uri)
    except Exception as exc:
        raise SystemExit(f"ERROR: Cannot connect to database: {exc}")
    print("Connected.\n")

    # Resolve workflows
    bsc_wf = _find_workflow(session, meta, args.bsc_workflow)
    mphys_wf = _find_workflow(session, meta, args.mphys_workflow)
    print(f"BSc  workflow : id={bsc_wf['id']}  name='{bsc_wf['name']}'")
    print(f"MPhys workflow: id={mphys_wf['id']}  name='{mphys_wf['name']}'")

    # Resolve MarkingEvent -> SubmissionPeriodRecord -> ProjectClassConfig for each workflow
    def _config_id_for_workflow(wf):
        event = _get_marking_event(session, meta, wf["event_id"])
        if event is None:
            raise SystemExit(f"ERROR: MarkingWorkflow id={wf['id']} references missing MarkingEvent id={wf['event_id']}")
        # MarkingEvent.period_id -> submission_periods.id -> project_class_config.id
        t_period = _tbl(meta, "submission_periods")
        period = session.execute(select(t_period).where(t_period.c.id == event["period_id"])).mappings().first()
        if period is None:
            raise SystemExit(f"ERROR: MarkingEvent id={event['id']} references missing SubmissionPeriodRecord id={event['period_id']}")
        return period["config_id"]

    bsc_config_id = _config_id_for_workflow(bsc_wf)
    mphys_config_id = _config_id_for_workflow(mphys_wf)
    print(f"BSc  config id : {bsc_config_id}")
    print(f"MPhys config id: {mphys_config_id}\n")

    LEVEL_TO_WORKFLOW = {
        "Final Year Project (BSc)": (bsc_wf, bsc_config_id),
        "Final Year Project (MPhys)": (mphys_wf, mphys_config_id),
    }

    # Read spreadsheet
    df = pd.read_excel(args.spreadsheet, header=1)
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")

    errors = []
    warnings = []
    processed = 0
    now = datetime.now()

    for idx, row in df.iterrows():
        email = str(row.get("Email", "")).strip()
        level = str(row.get("Level", "")).strip()
        a1_name = str(row.get("Assessor1", "")).strip()
        a2_name = str(row.get("Assesssor2", "")).strip()  # note typo in source column header

        sheet_row = idx + 2  # 1-indexed, offset for header row

        if not email or email.lower() == "nan":
            if verbose:
                print(f"  [SKIP] Row {sheet_row}: empty email")
            continue

        # Resolve workflow + config
        mapping = LEVEL_TO_WORKFLOW.get(level)
        if mapping is None:
            errors.append(f"Row {sheet_row} [{email}]: unrecognised Level '{level}'")
            continue
        workflow, config_id = mapping

        # Resolve student
        student_user = _find_user_by_email(session, meta, email)
        if student_user is None:
            errors.append(f"Row {sheet_row}: no User with email '{email}'")
            continue

        student_data = _get_student_data(session, meta, student_user["id"])
        if student_data is None:
            errors.append(f"[{email}]: User id={student_user['id']} has no StudentData row")
            continue

        # Resolve SubmissionRecord
        sub_record = _find_submission_record(session, meta, config_id, student_data["id"])
        if sub_record is None:
            errors.append(f"[{email}]: no SubmissionRecord in ProjectClassConfig id={config_id} (workflow '{workflow['name']}')")
            continue

        if verbose:
            print(f"[{email}] -> SubmissionRecord id={sub_record['id']}, workflow='{workflow['name']}'")

        # Resolve assessors
        a1_user, a1_warn = _find_user_by_name(session, meta, a1_name)
        a2_user, a2_warn = _find_user_by_name(session, meta, a2_name)

        if a1_warn:
            (errors if a1_user is None else warnings).append(f"[{email}] Assessor1: {a1_warn}")
        if a2_warn:
            (errors if a2_user is None else warnings).append(f"[{email}] Assessor2: {a2_warn}")
        if a1_user is None or a2_user is None:
            continue

        common = dict(
            session=session,
            meta=meta,
            sub_record=sub_record,
            workflow=workflow,
            role_type=role_type,
            now=now,
            dry_run=dry_run,
            verbose=verbose,
            errors=errors,
            warnings=warnings,
            student_email=email,
        )

        ok1 = _process_assessor(
            **common,
            assessor_user=a1_user,
            slot_index=1,
            duration=row.get("Duration1"),
            content=row.get("Content1"),
            structure=row.get("Structure1"),
            presentation=row.get("Presentation1"),
            visual=row.get("Visual1"),
            understanding=row.get("Understanding1"),
            feedback_positive=str(row.get("Feedback1", "")) if pd.notna(row.get("Feedback1")) else "",
        )
        ok2 = _process_assessor(
            **common,
            assessor_user=a2_user,
            slot_index=2,
            duration=row.get("Duration2"),
            content=row.get("Content2"),
            structure=row.get("Structure2"),
            presentation=row.get("Presentation2"),
            visual=row.get("Visual2"),
            understanding=row.get("Understanding2"),
            feedback_positive=str(row.get("Feedback2", "")) if pd.notna(row.get("Feedback2")) else "",
        )

        if ok1 and ok2:
            processed += 1

    # ------------------------------------------------------------------
    # Commit or rollback
    # ------------------------------------------------------------------
    if not dry_run and not errors:
        session.commit()
        print(f"\nCommitted. Rows fully processed: {processed}")
    elif not dry_run and errors:
        session.rollback()
        print(f"\nRolled back due to errors. Rows attempted: {processed}")
    else:
        session.rollback()
        print(f"\nDry run complete. Rows that would be processed: {processed}")

    session.close()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if warnings:
        print(f"\n--- WARNINGS ({len(warnings)}) ---")
        for w in warnings:
            print(f"  WARNING: {w}")

    if errors:
        print(f"\n--- ERRORS ({len(errors)}) ---")
        for e in errors:
            print(f"  ERROR: {e}")
        sys.exit(1)

    print("\nNo errors.")
    sys.exit(0)


if __name__ == "__main__":
    main()
