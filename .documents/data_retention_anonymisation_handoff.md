# Data Retention, Anonymisation & Exemplar Consent — Design Handoff

**Status:** Design agreed in principle; pending DPO sign-off, ROPA update, and implementation.
**Scope:** `User`, `StudentData`, `SubmissionRecord`, exemplar consent workflow, and faculty-facing report search.

---

## 1. Background

The projects application retains personal data about students (name, email,
programme, SEND flags) and their submitted reports indefinitely. The University's
Master Records Retention Schedule (MRRS 3.0) does not map cleanly onto this
system, but the closest applicable sections are:

- **§3.1.1** — core student record: graduation/departure + 6 years (general),
  perpetual for transcript-relevant data items.
- **§3.4.6** — submitted assessments/dissertations: graduation/departure + 1 year minimum.
- **§3.5.4** — academic misconduct files: last action + 6 years.
- **§3.6.10** — disability/reasonable adjustments records: graduation/departure + 6 years.

The design below reconciles these with two legitimate operational purposes:
(a) plagiarism/misconduct detection against a historical corpus, and (b)
supervisor recall of past projects — while complying with UK GDPR storage
limitation (Art. 5(1)(e)) and respecting student copyright in submitted reports.

---

## 2. Tiered anonymisation policy

### Tier 0 — SEND flags (`dyspraxia_sticker`, `dyslexia_sticker` on `StudentData`)

- **Action:** Null immediately after each marking cycle completes.
- **Repopulated** by the convenor at the start of each new cycle.
- **Rationale:** These flags can change year to year, so retaining stale values
  is actively harmful, not just unnecessary. Nulling promptly also removes
  special-category data (GDPR Art. 9) from scope entirely — it is never present
  long enough to fall under the 6-year window below.

### Tier 1 — On graduation/departure (start of next academic cycle)

Null the following on `User` and set `active = False`:

- `password`
- `last_login_ip`, `current_login_ip`, `login_count`, `last_login_at`, `last_active`
- `fs_uniquifier`, `fs_webauthn_user_handle`
- `confirmed_at`
- `canvas_API_token` (never used for students)
- `box_access_token`, `box_refresh_token`, `box_token_valid`, `box_updated_at` (never used for students)
- `default_license_id`
- Email preference fields (`group_summaries`, `summary_frequency`, `last_email`) — lower priority

**Effect:** Student can no longer log in. No ongoing operational purpose is served
by any of these fields post-departure.

**Open item:** `StudentData` needs an explicit `departed_at` timestamp to anchor
the Tier 2 clock precisely (departure can occur via graduation, withdrawal,
unresolved intermission, etc. — cohort/academic-year arithmetic alone is not
a reliable trigger).

### Tier 2 — 6 years post-departure

On `User`:

- Null `email`, `username`, `first_name`, `confirmed_at` (if not already)
- Replace `last_name` with the value of `User.uuid` (the existing UUID field —
  **do not introduce a second pseudonymous identifier**; `last_name` should
  simply mirror `uuid` so there is one canonical pseudonymous key)

On `StudentData`:

- Null `registration_number`, `exam_number`

**Retain (do not delete):**

- The `User` and `StudentData` rows themselves — see §5.
- `cohort`, `programme_id` and other non-identifying academic metadata.
- All `SubmissionRecord`, `SubmissionRole`, `LiveProject` data — these are
  institutional/staff records, not student personal data, and are unaffected.
- Report content (file + extracted text in MongoDB) — see §3.

---

## 3. Report retention rationale

**Plagiarism/misconduct corpus (strong justification):**
Retaining report *content* indefinitely for similarity checking is well
established in UK HE practice (cf. Turnitin) and does not require retaining
the student's identity — a pseudonymised corpus serves this purpose equally
well. This is the basis for retaining report text/embeddings past 6 years
even after the `User` row is anonymised.

**Supervisor recall (weaker justification):**
"A supervisor might want to browse an old report they remember" is closer to
convenience than necessity, and is not a strong standalone basis for retaining
*personal data*. However, it does **not** require personal data either —
supervisors search via their own `SubmissionRole` links, project metadata
(`LiveProject`, immutable per-cycle snapshot), academic year, and grade. None
of this is affected by Tier 2 anonymisation.

**Conclusion:** Both purposes are adequately served by the Tier 1/2 policy
above. Neither purpose justifies retaining student personal data (name, email,
registration number) past 6 years. The report content itself may be retained
indefinitely under the academic-integrity legitimate interest, provided this
is documented in the ROPA and disclosed to students at submission time.

**Action item:** Confirm assessment regulations/student contract licence
language ("legitimate academic purposes" or similar) explicitly covers
indefinite retention of report content for a plagiarism corpus. If the
licence is narrower (e.g. "for the purposes of assessment"), this needs
broadening or a separate basis.

---

## 4. Name redaction at text layer

A redaction feature has been implemented that strips student names from the
text layer of submitted reports during processing (`report_redaction_count`
on `SubmissionRecord` tracks how many redactions were applied). This is best-
effort — most cases are caught, but some will get through (e.g. unusual
formatting, names embedded in images). Remaining identifiers in reports are
candidate numbers, which are low-risk but not zero-risk re-identifiers.

**Implication:** Treat retained report text as *pseudonymised*, not fully
anonymous, for GDPR purposes — at least until candidate-number mappings are
also destroyed at Tier 2. This does not block the retention policy above, but
should be reflected accurately in the ROPA (don't overclaim anonymity).

---

## 5. Why `User` rows are not deleted

Deleting Tier-2 `User`/`StudentData` rows would require either cascading
deletes (destroying the academic record — unacceptable) or making FKs
nullable throughout the schema and adding null-guards everywhere (large
effort, no benefit).

After Tier 2, these rows are inert (mostly null, fixed-width) and cost is
negligible — at ~200–300 new students/year, this is a few thousand rows/year
across affected tables. The bulk of storage cost is in `language_analysis`
JSON blobs and MongoDB scraped text, not the relational identity tables.

**No rationale exists now or in any foreseeable future for a single-department
system.** Revisit only if the institution scaled to thousands of
students/year *and* join performance through `User` measurably degraded —
and even then, archiving to a separate read-only schema would be preferable
to deletion, since it preserves FK-based historical queries.

---

## 6. `User.name` as the anonymisation choke point

`User.name` (and `simple_name`, `initials`) is the single property most views
use to display student identity. Updating it to detect the anonymised state
(`first_name is None`) and return a non-identifying label (e.g.
`f"Anonymised student [{self.uuid[:8]}]"`) fixes most of the UI for free.

A companion `is_anonymised` property (`self.first_name is None`) lets views
suppress actions that are meaningless for anonymised records (send email,
view profile, etc.) without scattering null-checks.

**Remaining work:** grep for direct `.first_name` / `.last_name` access in
templates, queries (especially `.order_by()` / `.filter()` on these columns,
which will behave oddly once `first_name` is null and `last_name` is a UUID),
export/CSV functions, and email-generation code. Most hits will already be
mediated through `User.name`; the rest need individual fixes.

---

## 7. Exemplar / open-day consent and withdrawal

### Consent collection (at submission time)

Two **separate, opt-in, non-bundled** declarations, framed as "permissions"
rather than headlined "consent" (to avoid raising the Art. 7 bar unnecessarily
while still meeting its substance):

1. **Exemplar use for teaching** — report (with candidate number visible,
   name redacted) may be shown to future cohorts, possibly annotated.
2. **Open day / promotional use** — title/abstract/extract only, candidate
   number visible, name not shown.

Both declarations must state explicitly that declining has no effect on
assessment, and that consent can be withdrawn at any time.

### Withdrawal mechanism — the token

Because Tier 2 anonymisation removes the name→report mapping, withdrawal
cannot rely on staff looking up a student by name after 6 years. Instead:

- At consent time, generate a unique opaque token (UUID, distinct from
  `User.uuid`) and store it on `SubmissionRecord`.
- Include a permanent withdrawal URL (`/consent/withdraw/<token>`) in the
  submission confirmation email. Possession of the URL is the authentication
  — no login required.
- This token works identically before and after Tier 2 anonymisation, and
  serves as the mechanism for **both** GDPR consent withdrawal (while the
  record is personal data) **and** copyright licence withdrawal (after
  anonymisation, when the GDPR consent question becomes moot but the
  copyright withdrawal right persists).

**New `SubmissionRecord` fields:**

```python
exemplar_consent_token = db.Column(
    db.String(36, collation="utf8_bin"), unique=True, nullable=True, default=None
)
exemplar_consent_granted_at = db.Column(db.DateTime(), default=None)
exemplar_withdrawn = db.Column(db.Boolean(), default=False, nullable=False)
exemplar_withdrawn_at = db.Column(db.DateTime(), default=None)
```

Withdrawal is not retroactive for materials already distributed to a cohort —
only future use is prevented.

### Policy statement (for ROPA / privacy notice)

> At the point of submission, students are invited to grant optional consent
> for their project report to be used as an exemplar for future cohorts or
> displayed at open day and promotional events. These consents are independent
> of each other and of the submission itself; declining has no effect on
> assessment.
>
> When consent is granted, a unique withdrawal token is generated and included
> in the submission confirmation sent to the student. This token is the sole
> mechanism for withdrawing consent and students are advised to retain it.
>
> Withdrawal requests received while the student's identity record remains in
> the system (within 6 years of graduation or departure) will be matched by
> token or by identity verification through normal University channels. After
> that point, withdrawal can only be actioned by presenting the token, since
> the personal data linking the student's identity to their submission will
> have been deleted in accordance with the University's data retention
> schedule.
>
> Once anonymisation has occurred, the report no longer contains personal data
> within the meaning of UK GDPR. Any residual withdrawal right is a copyright
> matter. The University will honour withdrawal requests made by token
> regardless of when they are received.
>
> Reports for which consent has been withdrawn will not be used in future
> exemplar contexts. Where a report has already been distributed to a cohort,
> recall is not possible, but no further distribution will occur.

---

## 8. Faculty report search ("back-library")

### Search model

Supervisors search by **project**, not by student name — even though
supervisors typically *do* remember student names, the anonymisation policy
removes that as a search key, so the search surface is built around what
survives anonymisation:

- **Structured filters** (MySQL): `SubmissionRole.user_id` (= me), academic
  year (`period → config → year`), project class/programme, `LiveProject.name`
  (immutable per-cycle snapshot — confirmed no snapshotting column is needed,
  since `LiveProject` itself does not mutate after the cycle), grade,
  `report_exemplar` flag.
- **Full-text / semantic search** (MongoDB): existing scraped-text store
  already holds `scraped_text`, LLM-classified `sections` (abstract,
  introduction, etc.), and `minhash_signatures` per `record_id`.

### Recommended implementation

1. **Embedding step** (new, appended after `extract_chunks`): compute a
   `sentence-transformers` (`all-MiniLM-L6-v2`) embedding over
   `sections["abstract"] + sections["introduction"]`, store alongside the
   existing MongoDB document. Model is already loaded by the similarity
   pipeline — minimal marginal cost.
2. **Search endpoint:** embed the query string with the same model, run
   cosine/ANN search against stored embeddings (brute-force numpy is fine at
   department scale — low thousands of documents), join resulting `record_id`s
   back to MySQL for structured filters and display metadata.
3. **MongoDB `$text` index** over `scraped_text`/`sections` as a fallback/
   complement for exact keyword matches — note MongoDB allows only one text
   index per collection, and lacks semantic matching (vector search handles
   that gap).

### Access control

After anonymisation, a supervisor may only **open** records where they hold a
`SubmissionRole`, or where `report_exemplar` is set. Search results can list
matches; access to content is gated by this rule.

---

## 9. Outstanding action items

- [ ] Add `departed_at` to `StudentData` to anchor the Tier 2 clock.
- [ ] Confirm assessment regulations/licence language covers indefinite
      retention of report content for plagiarism corpus purposes.
- [ ] Update ROPA: document SEND-nulling, credential-nulling, Tier 2
      anonymisation, exemplar consent/withdrawal, and report-corpus retention
      as distinct processing activities with their respective legal bases.
- [ ] Update student-facing submission workflow with exemplar/open-day
      declarations (separate, non-bundled, "permissions" framing).
- [ ] Implement `exemplar_consent_token` + withdrawal endpoint.
- [ ] Update `User.name`/`simple_name`/`initials` + add `is_anonymised`.
- [ ] Grep audit for direct `.first_name`/`.last_name` access (templates,
      queries, exports, email generation) and refactor.
- [ ] Implement embedding step in similarity pipeline + search endpoint.
- [ ] DPO sign-off on overall policy.
