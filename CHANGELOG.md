# Changelog

## 2026-04-18

### Added
- Confirmed purchases can now split an existing lot from remaining inventory on the main purchase form, creating a traced child lot with its own tracking fields and audit history.
- Operators can now record an explicit extraction charge from a lot before opening the run form. The new charge workflow captures lot, pounds, reactor, timestamp, notes, and source mode (`main_app` or `scan`) in a persisted `ExtractionCharge` record.
- `Floor Ops` now shows a reactor charge queue with pending charges by reactor plus recently applied charges already linked to saved runs.
- `Floor Ops` now also includes an active reactor board that shows each reactor as empty, charged/waiting, or run-linked, with the current lot, charged lbs, charge time, queue depth, operator label, and direct run links when available.

### Changed
- Purchase edit now round-trips `availability_date` and `testing_notes` so values saved from the mobile opportunity flow remain visible and editable in the main app.
- Standalone buying copy now uses clearer "ready to record delivery" wording instead of the older "delivery capture" phrasing.
- Supplier creation now warns on typo-close duplicate names in the standalone buyer app and on the main supplier create page before saving a new record.
- Main-app duplicate warnings now include an explicit "keep both suppliers" confirmation path for legitimate same-name/different-city cases.
- The scanned-lot page now routes operators into a dedicated extraction-charge form instead of jumping straight to a generic run prefill.
- The main purchase form now gives each active lot a direct **Charge Lot** action alongside the existing scan workflow.
- The on-hand `Inventory` table now exposes direct `Edit`, `Charge`, and `Scan` actions for each lot instead of forcing users to navigate indirectly through batch edit or labels.
- `Inventory -> Biomass On Hand -> Edit` now opens a dedicated lot editor instead of the parent purchase form, so changing lot-level fields no longer moves the batch out of on-hand inventory by mistake.
- Lot-label pages now preserve their navigation context, so opening a label from Inventory returns to Inventory instead of always saying `Back to purchases`.
- `Floor Ops` summary sections now use consistent card styling across snapshot metrics, floor-state rollups, reactor queues, and recent activity lists.

### Tests
- Added regression coverage for purchase edit round-trip of mobile opportunity fields, dedicated inventory lot editing, inventory label return paths, and confirmed-lot splitting from remaining inventory (`tests/test_refactor_safety.py`).
- Added duplicate-supplier regression coverage for mobile supplier create, main supplier create, and standalone buyer duplicate matching.
- Added extraction-charge, floor-queue, and inventory-action regression coverage for scan-to-charge, charge prefill into new run, charge-to-run linkage, pending/applied reactor queue visibility, active reactor board status rendering, and direct inventory lot actions; full Python suite now passes with `127` tests.

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
