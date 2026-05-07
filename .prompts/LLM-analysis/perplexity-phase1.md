We are refactoring AI calibration storage from a JSON blob on the Tenant
model to a first-class TenantAICalibration model. Here is the proposed design:

```python
class TenantAICalibration(db.Model):
    """
    One calibration object for a tenant, covering a specific combination of
    project class group and LLM configuration (or no LLM config for
    lexical-only 3D calibrations).
    """
    __tablename__ = "tenant_ai_calibrations"

    id = db.Column(db.Integer, primary_key=True)
    tenant_id = db.Column(db.Integer, db.ForeignKey("tenants.id"), nullable=False)

    # --- Calibration provenance ---
    calibrated_at = db.Column(db.DateTime, nullable=False)
    n_samples = db.Column(db.Integer, nullable=False)
    included_years = db.Column(db.Text)  # JSON list of ints
    included_pclass_ids = db.Column(db.Text)  # JSON list of ints

    # --- LLM configuration (null for lexical-only calibrations) ---
    llm_model_name = db.Column(db.String(DEFAULT_STRING_LENGTH), nullable=True)
    llm_context_window = db.Column(db.Integer, nullable=True)

    # --- Feature space ---
    # "lexical"  → 3D (MATTR, MTLD, sentence_cv)
    # "full"     → 5D (MATTR, MTLD, sentence_cv, mean_nll, nll_cv)
    feature_set = db.Column(db.String(32), nullable=False, default="lexical")

    # --- Mahalanobis parameters ---
    # mu and sigma_inv stored as JSON; dimensions implied by feature_set
    mu = db.Column(db.Text, nullable=False)  # JSON list
    sigma_inv = db.Column(db.Text, nullable=False)  # JSON row-major matrix

    # --- Relationships ---
    tenant = db.relationship("Tenant", backref=db.backref("ai_calibrations", cascade="all, delete-orphan"))

    __table_args__ = (
        db.UniqueConstraint(
            "tenant_id", "feature_set", "llm_model_name", "llm_model_version",
            name="uq_tenant_calibration",
        ),
    )

    @property
    def mu_data(self) -> list:
        return json.loads(self.mu)

    @property
    def sigma_inv_data(self) -> list:
        return json.loads(self.sigma_inv)

    @property
    def n_features(self) -> int:
        return {"lexical": 3, "full": 5}.get(self.feature_set, 3)

    @property
    def is_llm_matched(self, model_name: str, model_version: str) -> bool:
        return (
                self.llm_model_name == model_name
                and self.llm_model_version == model_version
        )

    def validate_pclass_exclusivity(self, session) -> list[int]:
        """
        Return a list of pclass IDs that are already assigned to another
        calibration for this tenant/feature_set/llm combination.
        Raise or return empty list if clean.
        """
        my_ids = set(json.loads(self.included_pclass_ids or "[]"))
        conflicts = []

        siblings = (
            session.query(TenantAICalibration)
            .filter_by(
                tenant_id=self.tenant_id,
                feature_set=self.feature_set,
                llm_model_name=self.llm_model_name,
                llm_context_window=self.llm_context_window,
            )
            .filter(TenantAICalibration.id != self.id)  # exclude self on update
            .all()
        )

        for sibling in siblings:
            sibling_ids = set(json.loads(sibling.included_pclass_ids or "[]"))
            conflicts.extend(my_ids & sibling_ids)

        return conflicts
```

and a helper method on `Tenant`:

```python
class Tenant:
    def get_calibration(
            self,
            feature_set: str = "lexical",
            llm_model_name: str | None = None,
            llm_context_window: int | None = None,
    ) -> "TenantAICalibration | None":
        """Return the matching calibration object, or None."""
        for cal in self.ai_calibrations:
            if cal.feature_set != feature_set:
                continue
            if feature_set == "full" and (
                    cal.llm_model_name != llm_model_name
                    or cal.llm_context_window != llm_context_window
            ):
                continue
            return cal
        return None
```

Constraints:

- A project class may belong to at most one TenantAICalibration per
  (tenant, feature_set, llm_model_name, llm_model_version) combination.
  Enforce this via a validate_pclass_exclusivity() method called at
  creation/update time, not a DB constraint.
- feature_set is an enum: "lexical" (3D) or "full" (5D)
- llm_model_name and llm_model_version are nullable (null for lexical-only)
- The unique constraint is on (tenant_id, feature_set, llm_model_name,
  llm_model_version)

Please:

1. Create the TenantAICalibration model in the appropriate models file
2. Update Tenant to replace the ai_calibration blob column with an
   ai_calibrations relationship and a get_calibration() helper
3. Write an Alembic migration that reads each existing Tenant.ai_calibration
   blob and inserts a corresponding TenantAICalibration row with
   feature_set="lexical", llm_model_name=None, then drops the old column
4. Do not yet change any of the code that reads or writes calibration data —
   that comes in the next pass
