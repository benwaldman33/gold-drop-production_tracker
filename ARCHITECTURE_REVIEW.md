# Architecture & Code Health Review (April 10, 2026)

This review answers:
1. Are there major problems in the codebase?
2. Should the product be split into separate department apps or remain one omnibus app?

## Executive summary

The current product direction in the PRD is a **shared-data system with department-focused views** (not duplicate apps), and that direction is still the right default for this domain.

However, the implementation currently has several high-priority issues that make the app feel "Frankenstein":

- Environment fragility in tests/import behavior.
- Hidden coupling between utility logic and Flask app context.
- Security hardening gap (unsafe fallback SECRET_KEY).
- Documentation drift in inventory status rules.
- Very large single-file app (`app.py`) increasing cognitive load and change risk.

## Major code / engineering problems

### 1) Test runner/import fragility
- `pytest -q` fails collection in this environment with `ModuleNotFoundError: No module named 'app'` unless `PYTHONPATH=.` is set.
- This indicates repo/tooling assumptions about import paths are not codified in test config (e.g., `pytest.ini`, package layout).

### 2) Pure-function leakage into Flask app context
- Multiple Slack-mapping tests fail with `RuntimeError: Working outside of application context`.
- The stack shows helper logic (mapping preview / date conversion paths) reading `SystemSetting` during non-request execution, making otherwise deterministic logic context-dependent.
- This is a maintainability/testability smell and can produce surprising runtime failures when reused in scripts/jobs.

### 3) Security hardening: default Flask secret in source
- App config currently includes fallback `SECRET_KEY` value in source for missing env var.
- In production, this risks predictable session signing if environment configuration is wrong.
- Recommended posture: fail fast at startup in non-dev environments when `SECRET_KEY` is not provided.

### 4) Requirements/docs drift on inventory statuses
- Engineering notes state on-hand inventory statuses are (`delivered`, `in_testing`, `available`, `processing`) and explicitly exclude `complete`.
- FAQ currently says on-hand includes `complete`.
- Rule drift between docs and implementation causes operator confusion and trust erosion.

### 5) Monolithic file complexity
- `app.py` has grown into a large multi-domain module (auth, purchasing, runs, Slack sync, imports, dashboards, settings, admin, etc.).
- This does not necessarily require separate deployable apps, but it does require internal modularization (Blueprints/services) to control defect rate.

## Should this become separate department apps?

## Recommendation: **No split into separate deployable apps yet**

Keep one deployable system with one canonical database and one domain model, but refactor into a **modular monolith**.

### Why this is better for your current workflow

- PRD explicitly requires **shared business rules** and department views over the same records.
- Critical workflows cross boundaries naturally (pipeline → purchase approval → inventory eligibility → run costing → finance rollups).
- A multi-app split would multiply consistency risks in approvals, status transitions, and cost logic unless you also invest in strong platform contracts and integration tooling.

### When separate apps might make sense later

Split by bounded contexts only if/when you hit one or more of these:
- Independent scaling/availability needs (e.g., Slack ingestion throughput vs operator UI).
- Team autonomy with separate release cadences.
- Strict isolation/compliance boundaries.

If that happens, start by extracting integration-heavy edges first (e.g., Slack ingestion worker) instead of slicing core transactional domains prematurely.

## Suggested target architecture (next phase)

1. **Modular monolith now**
   - Flask Blueprints per domain (`runs`, `purchases`, `inventory`, `slack`, `settings`, `departments`).
   - Service layer for business rules (approval gates, inventory eligibility, budget enforcement).
   - Shared policy module for status transitions and permission checks.

2. **Contract-first domain rules**
   - Centralize status constants and transition validation.
   - Generate docs/help text from the same constants where possible.

3. **Testability improvements**
   - Make mapping/date helpers accept settings via injection/arguments.
   - Reserve DB lookups for route/service boundary, not low-level utility transforms.

4. **Operational hardening**
   - Fail startup on weak/missing secrets in production mode.
   - Add CI command parity (`PYTHONPATH`, test env) so local/CI behavior matches.

5. **UI/UX consistency for departments**
   - Keep department pages as lenses over shared queries.
   - Avoid custom rule forks per department.

## Practical decision

- **Short term:** Keep one app, reduce Frankenstein feel via internal modularization and rule centralization.
- **Medium term:** Extract only clearly separable integration workloads (background sync/import workers), not core domain CRUD and eligibility logic.
- **Long term:** Re-evaluate decomposition once domain boundaries and team ownership are stable.

---

## Addendum (Apr 2026 follow-up)

Since this review was drafted, several action items were completed:

- Test bootstrap is now codified (`pytest.ini`, `tests/conftest.py`) and local `pytest -q` runs cleanly without manual `PYTHONPATH` intervention.
- Purchases/Journey logic is now routed through a dedicated purchases Blueprint + service module.
- Journey endpoints were hardened to use shared purchase-loading/error helpers and explicit export-format validation.
- A `SystemSetting.get` legacy ORM access path was modernized to `db.session.get(...)`.

Remaining recommendations still stand (secret-key hardening posture, continued modular extraction, and doc/implementation parity checks).
