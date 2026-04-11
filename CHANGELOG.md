# Changelog

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.
- Runtime probe endpoints: `/livez`, `/readyz`, and `/healthz` readiness alias.
- Version diagnostics endpoint: `/version` exposing `APP_VERSION` + normalized app env.
- Migration CLI scaffold via `manage.py` + Flask-Migrate dependency.
- Ops preflight enhancements for production env-var checks.
- `SEED_DEMO_DATA` controls and minimal demo baseline seeding across core modules.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
- Added regression checks for demo-seed env policy, preflight production env requirements, and non-admin archived Journey access gating.
