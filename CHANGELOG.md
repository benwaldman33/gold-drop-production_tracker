# Changelog

## 2026-04-18

### Added
- Confirmed purchases can now split an existing lot from remaining inventory on the main purchase form, creating a traced child lot with its own tracking fields and audit history.
- Operators can now record an explicit extraction charge from a lot before opening the run form. The new charge workflow captures lot, pounds, reactor, timestamp, notes, and source mode (`main_app` or `scan`) in a persisted `ExtractionCharge` record.
- `Floor Ops` now shows a reactor charge queue with pending charges by reactor plus recently applied charges already linked to saved runs.
- `Floor Ops` now also includes an active reactor board that shows each reactor as empty, charged/waiting, or run-linked, with the current lot, charged lbs, charge time, queue depth, operator label, and direct run links when available.
- `Floor Ops` now supports explicit reactor lifecycle transitions for charged lots: `Mark In Reactor`, `Mark Running`, `Mark Complete`, and `Cancel Charge`, with timestamped audit history for each state change.
- `Settings -> Operational Parameters` now includes reactor lifecycle controls so Super Admin can show/hide each lifecycle state, make states required or optional, require a linked run before `Mark Running`, and choose whether state history is shown on the active reactor board.
- A new `standalone-extraction-lab-app` now mirrors the extractor workflow with a touch-first reactor board, lot browser, charge form, and lifecycle actions that still hand off into the main run form when needed.

### Changed
- Standalone extraction `Reactors` board filters now respect the selected `Board view` on live production data instead of always showing every reactor card.
- The standalone extraction app now exposes a dedicated `Scan / Enter Lot` screen, camera/manual tracking-ID lookup, a default `100 lbs` charge preset per reactor, and a faster post-charge loop (`Open Run`, `Back to Reactors`, `Charge Another Lot`).
- The standalone extraction app now auto-focuses the manual tracking-ID field, shows scan guidance on-screen, confirms successful lot resolution on the charge form, and remembers the last reactor used for the next charge.
- The standalone extraction app now includes a dedicated run-execution screen tied to each charge, with touch-first timers for run/fill, mixer, and flush timing plus structured fields for blend, fills, flushes, stringer baskets, CRC blend, and notes.
- The standalone extraction reactor board now renders `Open Run` as a full-size primary action next to the lifecycle buttons so operators do not have to hunt for a small inline link before `Mark Running`.
- The main app sidebar now scrolls independently, so lower navigation items and `Logout` remain reachable on normal-height screens even as the left pane grows.
- `Settings -> Operational Parameters` now includes `Extraction run defaults`, letting operators preconfigure the standalone extraction run screen's default milled/unmilled blend, fill count, flush count, stringer basket count, and CRC blend.
- The extraction mobile API now exposes `GET/POST /api/mobile/v1/extraction/charges/<charge_id>/run` so the standalone app can fetch a draft run from a charge and save execution details without bouncing into the admin form.
- The main run form now stores the new extraction execution fields so supervisors can still review or edit the same data from the admin UI.
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
- Completed or cancelled charges now stay visible on the active reactor board for the rest of the local day before dropping back to history-only visibility.
- Cancelling a charge from `Floor Ops` now records whether the operator chose to abandon the charge or jump into the linked run to modify it.
- `Open Run` links from `Floor Ops` now carry a return path back to the operator context instead of always dropping users onto a generic `Back to Runs` link.
- The active reactor board and charge forms now stay aligned with the greater of configured reactor count and observed reactor numbers, so a higher-numbered reactor does not disappear from the board just because settings lag reality.
- `Floor Ops` now includes board-level reactor filters plus a same-day `Reactor History Today` section so extractors can focus on active/running/completed work and review recent per-reactor activity without opening each run.
- Slack import preview now includes `Create extraction charge from Slack`, which records a canonical `ExtractionCharge` from the Slack message, tags it with `source_mode="slack"`, and opens `runs/new` with that saved charge attached.

### Tests
- Added regression coverage for purchase edit round-trip of mobile opportunity fields, dedicated inventory lot editing, inventory label return paths, and confirmed-lot splitting from remaining inventory (`tests/test_refactor_safety.py`).
- Added duplicate-supplier regression coverage for mobile supplier create, main supplier create, and standalone buyer duplicate matching.
- Added extraction-charge, floor-queue, lifecycle-settings, inventory-action, and Slack-charge regression coverage for scan-to-charge, charge prefill into new run, charge-to-run linkage, pending/applied reactor queue visibility, active reactor board status rendering, direct inventory lot actions, lifecycle transition enforcement, cancel resolution redirects, and Slack import charge creation / split-allocation rejection; combined with the new extraction standalone coverage, the full Python suite now passes with `136` tests.
- Added standalone extraction mobile API regression coverage for workflow toggles, board and lot reads, charge creation, and lifecycle transitions, plus a standalone extraction app Node suite covering route parsing, touch-charge helpers, and API envelope handling.

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
