# Feasibility study: soft-constraint infeasibility diagnosis for the matching optimizer

**Scope**: `MatchingAttempt` optimizer in `app/tasks/matching.py` only. The scheduling
optimizer (`app/tasks/scheduling.py`) is explicitly out of scope for now, but the design
should keep the diagnostic machinery generic enough to roll out there later.

**Goal**: when a matching problem is infeasible, report *which* constraints are in conflict
and *which* students/supervisors/markers/projects are involved, without requiring the user to
export the LP file and compute an IIS in Gurobi.

---

## 1. Inventory of constraints in `_create_PuLP_problem`

Every `prob +=` in `_create_PuLP_problem` (matching.py:1343–2214), classified by role.

### 1.1 Structural / definitional — can never cause infeasibility

These define auxiliary variables in terms of primary ones, or tension free continuous
variables one-sidedly. They are always satisfiable and must stay hard:

| Constraint | Location | Notes |
|---|---|---|
| `ss[k,j] <= S[k,j]`, `UNBOUNDED*ss >= S` | 1744, 1758 | boolean-izes S |
| `Z[k] <= ΣS`, `Z[k] >= ss[k,j]` | 1833, 1842 | supervisor-has-work flag |
| `Ysel[i,j] == Σ_l Y[i,j,l]` | 1893 | slice definition |
| `Ymark[l,j] == Σ_i Y[i,j,l]` | 1911 | slice definition |
| `yy[i,j] <= Ysel`, `UNBOUNDED*yy >= Ysel` | 1925, 1938 | boolean-izes Y |
| Levelling: supMax/supMin, markMax/markMin, supMarkMax/supMarkMin, globalMax/globalMin, maxProjects, maxMarking | 2140–2210 | one-sided against free vars; always satisfiable |

### 1.2 Eligibility — encode *who may do what*; keep hard

| Constraint | Location | Meaning |
|---|---|---|
| `X[l,j] <= R[l,j]` where `R = 0` | 1636 | selector did not rank project j (and it is not an alternative) |
| `S[k,j] <= capacity[j]*P[k,j]` where `P = 0` | 1725 | k does not own project j / not in its supervisor pool |
| `Σ_l Y[i,j,l] <= M[i,j]` where `M = 0` | 1875 | i not in assessor pool for j |
| `Σ S = 0` (nosupv), `Σ Ysel = 0` (nomark) | 1789, 1974 | project class does not use that role |

Relaxing these produces nonsense diagnoses ("assign the student a project they never
ranked", "make a non-pool member the supervisor"). The infeasibility they participate in is
caught more legibly by relaxing the *demand* constraints below (e.g. "student X could not
receive their required number of projects" rather than "eligibility violated for 40
student–project pairs"). Recommendation: treat R=0 / P=0 / M=0 entries as *fixed-zero
variables*, not candidate violations.

### 1.3 Resource / demand — the real infeasibility sources (candidates for slack)

| # | Constraint | Location | Typical conflict |
|---|---|---|---|
| C1 | Selector multiplicity `Σ_j X[l,j] == m_l` | 1654 | student's ranked projects all full / eligible supply exhausted |
| C2 | Require hints & custom offers `X[idx] == 1` (`cstr`) | 1668 | forced assignment conflicts with capacity or another force |
| C3 | Base-match force `X[idx] == 1`, `Y[idx] == base_Y[idx]` | 1689, 2017 | base match incompatible with current capacities/pools |
| C4 | Project capacity `S[k,j] <= capacity[j]` (where P=1) | 1725 | more demand than capacity |
| C5 | Supervisor parity `Σ_k S = Σ_l X` per project | 1782 | couples demand to supervisor supply — keep hard, let C4/C7 slacks absorb |
| C6 | Max distinct projects `group_projects <= group_limit`, `all_projects <= all_limit` | 1812, 1822 | pool members capped out |
| C7 | Marker capacity `Σ_l Y[i,j,l] <= M[i,j]` (where M>0) | 1875 | assessor pool too small for cohort |
| C8 | Marker parity `valence[j]*X[l,j] == Ymark[l,j]` | 1967 | keep hard; C7 slack absorbs |
| C9 | Supervisor ≠ marker `ss[k,j] + yy[i,j] <= 1` | 1993 | only eligible marker is the supervisor |
| C10 | Global CATS limits | 2076, 2112 | **already elastic** (`sup_elastic_CATS` / `mark_elastic_CATS`) |
| C11 | Per-project-class CATS limits | 2087, 2123 | **hard** — asymmetric with C10; a likely real-world infeasibility source |

### 1.4 Pre-solve hard failures (RuntimeError before the solver even runs)

These are "trivially detectable infeasibilities" that currently kill the Celery task with an
opaque failure rather than producing a diagnosis:

- Existing supervisor CATS > limit (matching.py:2070)
- Existing marker CATS > limit (matching.py:2106)
- Selector has no valid LiveProjects on their preference list (matching.py:995)
- Custom offer targets a missing LiveProject (matching.py:938)

Whatever reporting channel is built should also carry these (they are the *cheapest*
diagnoses of all — no solve needed).

### 1.5 Existing assets worth reusing

1. **The elastic-CATS mechanism (C10) already implements the requested pattern** for one
   constraint family: slack variables (`A_k`, `B_i`), a penalty term weighted by the
   per-attempt `CATS_violation_penalty` parameter, and units chosen so penalties are
   commensurate with the score function. The pattern is proven in this codebase.
2. **Post-solve validation layer** — `_MatchingAttempt_is_valid` /
   `_MatchingRecord_is_valid` in `app/models/matching_validation.py` already compute
   structured `errors`/`warnings` dicts against a *stored* solution and surface them in the
   matching UI. The infeasibility report can plug into the same presentation vocabulary.
3. **Serialized enumerations** — `MatchingEnumeration` rows (stored by
   `_store_enumeration_details`) allow a problem to be reconstructed offline
   (`read_serialized=True`). This is a ready-made testing hook: diagnostics can be re-run
   against historical infeasible attempts.
4. **Constraint names already encode entities** (e.g. `_C{first}{last}_supv_CATS`), but
   parsing names back is fragile; the design below uses an explicit slack registry instead.

---

## 2. Architecture options

### Option A — all-soft single solve (as literally proposed)

Replace every hard constraint in the production problem with a soft constraint + slack,
keep the existing score objective, subtract large slack penalties, inspect slacks post-solve.

**Assessment: workable but not recommended as the primary architecture.** Specific problems:

1. **Penalty calibration vs. the score function.** To guarantee the solver never trades a
   constraint violation for score, each penalty must exceed the maximum achievable score gain
   from violating (a big-M argument). The objective already mixes ranking score, levelling
   terms, and the existing CATS penalties; adding ~10 more penalty families with dominating
   coefficients invites numerical trouble (CBC works in double precision; coefficient ranges
   above ~1e6–1e7 degrade its LP relaxations) and makes the existing tuning parameters
   (`levelling_bias`, `intra_group_tension`, …) harder to reason about.
2. **`gapRel=0.25` is fatal to soft-constraint correctness.** Both CBC paths run with a 25%
   relative MIP gap (matching.py:2970–2972). With penalties in the objective, a solution
   carrying spurious violations can sit comfortably inside a 25% gap and be reported as
   "Optimal". Users would see phantom violations on problems that are actually feasible.
   (The existing elastic-CATS terms are already exposed to this, but only for one family and
   with a user-tunable penalty; generalizing it multiplies the exposure.)
3. **Silent violations become deployable.** Today OUTCOME_INFEASIBLE is an unmissable stop.
   If everything is soft, every attempt reports "Optimal" and the violation report becomes
   the only guard. `solution_usable` (models/matching.py:130) would need to learn about
   violations, the UI would need hard gates, and a convenor skimming past a warning could
   publish a match that violates a require hint.
4. Solve times likely degrade: feasibility-repair penalties flatten the objective landscape
   and weaken pruning.

### Option B — two-phase: hard production solve, elastic diagnostic solve on infeasibility (recommended)

Keep the production problem **exactly as it is today**. When (and only when) the solver
returns `Infeasible`:

1. Rebuild (or re-parameterize, see §3.4) the problem in **diagnostic mode**: slacks added to
   families C1–C4, C6, C7, C9, C11; eligibility and structural constraints stay hard; the
   score objective is **discarded** and replaced by weighted slack minimization.
2. Solve with CBC at `gapRel=0` (feasibility-repair MILPs of this shape usually solve much
   faster than the scoring problem; keep the timeLimit safety net).
3. Walk the slack registry, collect every slack > tolerance, map indices back to
   selectors/faculty/projects via the enumeration dicts, and store a structured report.

Why this shape:

- Zero risk to the production optimization path — behaviour on feasible problems is
  byte-for-byte unchanged.
- The diagnostic objective is pure (`min Σ w·u`), so no penalty-vs-score calibration problem
  and no gap-tolerance pollution.
- **Every independent conflict surfaces simultaneously** — each disjoint infeasibility forces
  its own slack. This is actually *better* than a Gurobi IIS, which reports one irreducible
  set at a time and typically requires several fix-and-repeat cycles.
- The construction cost is paid twice only in the infeasible case (construction is minutes at
  worst per the existing `Timer` instrumentation; acceptable for a failure path).

**Recommendation: Option B**, with two elements of Option A adopted as standalone quick wins
(§4 Phase 0): making per-pclass CATS limits (C11) elastic in the *production* problem to
match C10, and converting the pre-solve RuntimeErrors into structured report items.

---

## 3. Design detail for Option B

### 3.1 Slack variable design per family

One-sided slacks only — relax each constraint in the single direction that can restore
feasibility. Directions and interpretations:

| Family | Relaxation | Slack type | Report reads as |
|---|---|---|---|
| C1 multiplicity | `Σ_j X[l,j] + u_l == m_l`, keep `Σ X <= m_l` implicit | integer ≥ 0 | "Student «name» could only be assigned {m−u} of {m} required projects" |
| C2 require/offer | `X[idx] + u_idx >= 1` | binary | "Required assignment of «student» to «project» could not be honoured" |
| C3 base force | `X[idx] + u >= 1`; `Y[idx] + u >= base_Y[idx]` | binary | "Base-match assignment … could not be reproduced" |
| C4 capacity (P=1) | `S[k,j] <= capacity[j] + u_kj` | integer ≥ 0 | "Project «name» needed {u} places beyond its capacity {c}" (aggregate per project for display) |
| C6 distinct-project limits | `… <= limit + u_k` | integer ≥ 0 | "«name» needed {u} more distinct (group) projects than the configured limit {L}" |
| C7 marker capacity (M>0) | `Σ_l Y <= M[i,j] + u_ij` | integer ≥ 0 | "«name» needed {u} extra marking assignments on «project» beyond the multiplicity limit" |
| C9 sup≠marker | `ss + yy <= 1 + u_kj` | binary | "The only way to staff «project» makes «name» both supervisor and marker" |
| C10 global CATS | reuse existing `A_k`/`B_i` | continuous | "«name» exceeds supervising/marking CATS limit {lim} by {u} CATS" |
| C11 pclass CATS | `… <= fac_limits + u` | continuous ≥ 0 | "«name» exceeds their «pclass» CATS limit {lim} by {u} CATS" |

Kept hard: everything in §1.1 and §1.2, plus parity constraints C5/C8 (any conflict routed
through parity is absorbed by C4/C7/C10 slacks and attributed to the resource side, which is
the actionable side).

### 3.2 Weights: controlling where blame lands

Minimal-total-slack is not an IIS: within a single conflict, the solver chooses *which*
constraint to blame, and ties are broken arbitrarily. Encode the preferred blame order in the
weights so diagnoses point at the most actionable lever. Suggested ordering (heaviest = least
preferred to blame):

1. **C2/C3 forced assignments — heaviest** (say 100·mean_CATS_per_project per unit): a
   violated require hint should only be reported when genuinely unavoidable.
2. **C1 multiplicity — heavy** (say 20·mean_CATS_per_project): "student left without a
   project" is the worst outcome; prefer to blame capacity/CATS instead.
3. **C4/C6/C7/C9 count-type resource slacks — medium** (mean_CATS_per_project per unit, i.e.
   one project-place ≈ one project's worth of CATS).
4. **C10/C11 CATS slacks — light** (1 per CATS): CATS relaxation is the cheapest, most
   politically acceptable repair, so it should absorb blame first.

This mirrors the existing convention that CATS violations are *warnings* while unassigned
students are *errors* (`matching_validation.py` §3 comment). Weights should be named
constants in one place; no need for per-attempt tunability in phase 1.

### 3.3 Slack registry (avoid parsing constraint names)

During constraint construction in diagnostic mode, record each slack in a registry:

```python
@dataclass
class SlackEntry:
    var: pulp.LpVariable
    category: str            # "multiplicity" | "force" | "capacity" | ...
    weight: float
    # enumeration indices, resolved to ORM ids at report time:
    selector: Optional[int] = None
    project: Optional[int] = None
    supervisor: Optional[int] = None
    marker: Optional[int] = None
    config_id: Optional[int] = None
    limit_value: Optional[float] = None   # the RHS being relaxed
```

Post-solve, filter `pulp.value(e.var) > 0.5` (integer/binary) or `> eps` (continuous, use
eps ≈ 0.01 CATS), and render messages from the category + resolved entities. Put the
registry, the `SlackEntry` type, and the report renderer in a new shared module —
`app/tasks/optimization_diagnostics.py` — so `scheduling.py` can reuse them later.

### 3.4 Wiring into `_create_PuLP_problem` and the task flow

Two implementation routes:

- **Route 1 (recommended): `diagnostic: bool = False` parameter.** Inside
  `_create_PuLP_problem`, at each of the ~9 elasticizable sites, branch: normal mode emits
  the constraint as today; diagnostic mode emits the relaxed form and appends to the
  registry. Objective: in diagnostic mode skip `_build_score_function` and set
  `min Σ w·u`. Return the registry in an extended `PuLPProblem` namedtuple (add a
  `slack_registry` field, `None` in normal mode). This is verbose but obvious and keeps the
  existing code path untouched when `diagnostic=False`.
- **Route 2: build once, activate slacks by bounds.** Always create slack variables with
  `upBound=0`, then on infeasibility reset `upBound` and swap the objective via
  `prob.setObjective(...)`, then re-solve. Avoids the second construction pass, but pollutes
  the production LP with dead columns (slower solve, larger exported LP files, and the
  offline-solution path `_execute_from_solution` reads variables by name so the extra
  variables leak into that flow). Not worth it; construction time on the failure path is
  acceptable.

Task-flow change, in `_process_PuLP_solution` (matching.py:3203) — on
`state == "Infeasible"`:

```python
elif state == "Infeasible":
    record.outcome = MatchingAttempt.OUTCOME_INFEASIBLE
    _diagnose_infeasibility(record, init_data, base_data)   # inline, same task
```

Run inline in the same Celery task (all inputs — `init_data`, `base_data` — are already in
memory; a separate task would have to rebuild from serialized enumerations for no benefit).
Add a `progress_update(... "Match was infeasible; diagnosing conflicting constraints...")`
so the user sees why the task is still running. Wrap the whole diagnostic in a
`try/except` that logs and degrades gracefully: a diagnosis failure must never turn an
INFEASIBLE outcome into a task failure. Budget the diagnostic solve with its own
`timeLimit` (suggest 600 s to start) and `gapRel=0`.

Edge case: if the *diagnostic* problem itself comes back infeasible, one of the
kept-hard constraints is implicated (a modelling bug, or an eligibility contradiction such
as a `cstr` force targeting a project with `R=0` — note `cstr` indices always have
`R ≥ 1` by construction, but base-match forces have no such guarantee). Report "diagnosis
could not isolate the conflict" and fall back to today's behaviour; log for investigation.

Solver for the diagnostic pass: always packaged CBC, regardless of `record.solver` —
the point of the feature is that users *don't* have commercial solvers, and infeasibility
of the diagnostic must not depend on external tooling.

### 3.5 Storage and reporting

- **Model**: new nullable `infeasibility_report` column on the `PuLPMixin`
  (`db.Column(db.Text(collation="utf8_bin"))` per the SQLAlchemy column rules, JSON-encoded)
  — putting it on the mixin makes it available to `ScheduleAttempt` for free later.
  Hand-written Alembic migration (check chain tip per CLAUDE.md procedure). Store:
  `{"generated": iso-ts, "diagnostic_solve_time": float, "status": "diagnosed"|"failed",
  "violations": [{"category", "message", "severity", "amount", entity ids...}]}`.
  Entity ids (not names) plus a pre-rendered message: ids allow future UI linking; the
  message survives entity deletion.
- **Pre-solve failures** (§1.4): instead of raising bare RuntimeErrors, collect them into
  the same report structure, set `OUTCOME_INFEASIBLE`, and finish the task cleanly — these
  cases currently don't even reach the solver and give the user nothing actionable.
- **UI**: in the matching attempt list (`app/ajax/admin/matching/matches_v2.py`), the
  INFEASIBLE outcome chip gains a "View diagnosis" link when a report is present. Detail
  view: violations grouped by category, ordered errors-first (forced assignments,
  unassignable students) then warnings (CATS), reusing the visual vocabulary of the
  existing match validation error/warning display. A flat grouped list is appropriate
  (reports will have a handful of entries, not thousands); no DataTables needed.

### 3.6 Interpretation caveats to surface in the UI

- The report is **one minimal-cost repair**, not a unique explanation. Alternative repairs
  may exist; wording should be "the optimizer found the following minimal set of
  relaxations that would make the problem solvable", not "these constraints are wrong".
- Blame attribution follows the §3.2 weight policy (CATS first, forced assignments last);
  a note in the UI ("violations are attributed to workload limits in preference to student
  assignments where possible") prevents misreading.
- Amounts are the *minimum* relaxation needed, jointly — useful directly ("raise capacity
  of project P by 2, or free 15 CATS across these three supervisors").

---

## 4. Phased implementation plan

**Phase 0 — quick wins, independent of the diagnostic machinery** (small; could ship first):
1. Make per-pclass CATS limits (C11) elastic in the *production* problem, mirroring C10 and
   reusing `CATS_violation_penalty`. Removes a whole class of avoidable hard infeasibilities
   and fixes the C10/C11 asymmetry.
2. Convert the four pre-solve RuntimeErrors (§1.4) into structured report items +
   `OUTCOME_INFEASIBLE` with a clean task finish. Requires the report column, so pairs
   naturally with the phase-1 migration; can also ship with a simpler message-only column.

**Phase 1 — core diagnostic pass** (the main effort):
- `app/tasks/optimization_diagnostics.py`: `SlackEntry`, registry, weights, report renderer.
- `diagnostic` mode in `_create_PuLP_problem` (~9 constraint sites + objective swap +
  extended namedtuple).
- `_diagnose_infeasibility` inline call from `_process_PuLP_solution`.
- Migration for `infeasibility_report`; `log_db_commit` on storing a diagnosis.
- UI surfacing in the matching views.
- Estimated touch: `_create_PuLP_problem` is the risky file region (870 lines); the
  diagnostic branches are additive and guarded, so production behaviour is provably
  unchanged when `diagnostic=False`.

**Phase 2 — refinements** (optional, data-driven):
- Lexicographic second pass minimizing the *number* of violated constraints (binary
  indicators over slacks) for crisper attribution when reports look smeared.
- Diagnostic export: write the elastic LP file to the download centre alongside the
  existing `_write_LP_file` output for offline scrutiny.
- Roll-out to `scheduling.py` (out of scope now; the shared module and mixin column make
  this mostly mechanical).

**Testing strategy** (no project test suite): drive `_create_PuLP_problem` +
`_diagnose_infeasibility` against historical attempts re-hydrated from `MatchingEnumeration`
(`read_serialized=True`), plus synthetic minimal fixtures: (a) two students forced onto a
capacity-1 project; (b) require hint vs. full project; (c) assessor pool smaller than
cohort × valence; (d) sole eligible marker == supervisor; (e) per-pclass CATS limit below
existing commitments. Each should produce exactly the expected violation category, and a
feasible control fixture should produce none.

---

## 5. Verdict

Feasible, with moderate effort concentrated in one function. The all-soft single-solve
variant (Option A) is technically possible but fights the existing `gapRel=0.25` solver
settings and the score-function calibration, and converts a loud failure into a quiet one.
The two-phase variant (Option B) delivers the same diagnostic power — arguably more, since
all independent conflicts surface in one pass rather than one IIS at a time — at zero risk
to the production solve path, and both the elastic-slack pattern (C10) and the
error/warning reporting vocabulary (`matching_validation.py`) already exist in the codebase
to build on.
