# Changelog

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
