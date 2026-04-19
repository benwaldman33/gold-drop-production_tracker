# Changelog

## 2026-04-18

### Added
- Confirmed purchases can now split an existing lot from remaining inventory on the main purchase form, creating a traced child lot with its own tracking fields and audit history.

### Changed
- Purchase edit now round-trips `availability_date` and `testing_notes` so values saved from the mobile opportunity flow remain visible and editable in the main app.
- Standalone buying copy now uses clearer "ready to record delivery" wording instead of the older "delivery capture" phrasing.
- Supplier creation now warns on typo-close duplicate names in the standalone buyer app and on the main supplier create page before saving a new record.
- Main-app duplicate warnings now include an explicit "keep both suppliers" confirmation path for legitimate same-name/different-city cases.

### Tests
- Added regression coverage for purchase edit round-trip of mobile opportunity fields and for confirmed-lot splitting from remaining inventory (`tests/test_refactor_safety.py`).
- Added duplicate-supplier regression coverage for mobile supplier create, main supplier create, and standalone buyer duplicate matching.

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
