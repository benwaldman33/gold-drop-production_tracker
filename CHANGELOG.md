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
- Phase 1 of post-extraction orchestration is now live on the existing run: operators can select the downstream pathway (`100 lb pot pour` or `200 lb minor run`), start the post-extraction handoff, and confirm the initial wet THCA / wet HTE outputs from the standalone extraction run screen or the main run form.
- Phase 2 downstream state tracking is now live on the run record: operators can capture pot-pour warm off-gas timing and stir count, THCA oven/milling/destination, and HTE off-gas / clean-dirty / Prescott / queue-routing decisions before a dedicated downstream screen exists.
- Phase 3 guided downstream workflow is now live in the standalone extraction app, turning the downstream portion of `Open Run` into a numbered, pathway-driven sequence instead of a flat block of fields.
- Phase 4 downstream queue surfaces are now live in the main app: `Downstream Queues` groups completed post-extraction runs into `Needs Queue Decision`, `GoldDrop production queue`, `Liquid Loud hold`, `Terp strip / CDT cage`, `HP base oil hold`, and `Distillate hold`, with move/complete actions that update the existing run-level destination fields.

### Changed
- `Inventory` now includes `Import spreadsheet`, built on the shared import framework as a controlled update-only workflow over existing lots matched by tracking ID. It supports the same safe lot-edit fields as the manual lot editor: strain, potency, location, floor state, milled state, and notes.
- `Strains` now includes `Import spreadsheet`, built on the shared import framework as a safe supplier+current-strain -> new-strain rename workflow over matching purchase lots.
- `Suppliers` now includes `Import spreadsheet`, built on the same shared import framework as Purchases: upload, interactive column mapping, preview, duplicate-aware hints, and optional update of exact-name matches.
- `Purchases -> Import spreadsheet` now stages uploads through an interactive column-mapping preview, supports a broader set of purchase, pipeline/testing, and lot fields, and uses a reusable import-framework helper instead of a fixed header-only flow.
- `Settings -> Slack -> field mappings` now uses friendlier business labels, destination-specific field pickers, and clearer guidance so Super Admins can map Slack fields without having to memorize raw snake_case target names.
- Standalone extraction `Reactors` board filters now respect the selected `Board view` on live production data instead of always showing every reactor card.
- The standalone extraction app now exposes a dedicated `Scan / Enter Lot` screen, camera/manual tracking-ID lookup, a default `100 lbs` charge preset per reactor, and a faster post-charge loop (`Open Run`, `Back to Reactors`, `Charge Another Lot`).
- The standalone extraction app now auto-focuses the manual tracking-ID field, shows scan guidance on-screen, confirms successful lot resolution on the charge form, and remembers the last reactor used for the next charge.
- The standalone extraction app now includes a dedicated run-execution screen tied to each charge, with touch-first timers for run/fill, mixer, and flush timing plus structured fields for blend, fills, flushes, stringer baskets, CRC blend, and notes.
- The standalone extraction run screen now shows guided progression actions (`Start Run`, `Start Mixer`, `Stop Mixer`, `Start Flush`, `Stop Flush`, `Mark Run Complete`) so operators can advance the run from the tablet without relying on typed Slack timestamps.
- The standalone extraction run screen now continues directly into a post-extraction foundation card, with gated actions for `Start Post-Extraction` and `Confirm Initial Outputs` plus the shared wet THCA / wet HTE fields and the chosen downstream pathway.
- The standalone extraction run screen now also includes touch-first downstream state capture for pot-pour warm off-gas, THCA oven/milling/destination, and HTE off-gas plus clean/dirty, Prescott, potency, and queue-routing decisions.
- The standalone extraction run screen now promotes those downstream controls into a guided workflow stack with numbered steps, pathway-specific sequencing, and tap-first choice buttons so operators can work top-to-bottom on one screen.
- The main app now includes a dedicated `Downstream Queues` page plus sidebar navigation, giving supervisors an operational surface for post-extraction routing instead of forcing them to work from raw run-form fields only.
- Opening a run from `Downstream Queues` now preserves a `Back to Downstream Queues` return path in the run form.
- The standalone extraction reactor board now renders `Open Run` as a full-size primary action next to the lifecycle buttons so operators do not have to hunt for a small inline link before `Mark Running`.
- The main app sidebar now scrolls independently, so lower navigation items and `Logout` remain reachable on normal-height screens even as the left pane grows.
- `Settings -> Operational Parameters` now includes `Extraction run defaults`, letting operators preconfigure the standalone extraction run screen's default milled/unmilled blend, fill count, total fill weight, flush count, total flush weight, stringer basket count, and CRC blend.
- The extraction mobile API now exposes `GET/POST /api/mobile/v1/extraction/charges/<charge_id>/run` so the standalone app can fetch a draft run from a charge, receive a derived run-progression payload, accept `progression_action` writes, and save execution details without bouncing into the admin form.
- The main run form now stores the new extraction execution fields so supervisors can still review or edit the same data from the admin UI.
- The main run form now also shows the current extraction progression stage and stores a dedicated run-completed timestamp for supervisor review and corrections.
- The main run form now shows the Phase 1 post-extraction foundation state, including the selected downstream pathway and the timestamps for post-extraction start and initial-output confirmation.
- The main run form now exposes the same Phase 2 downstream fields as the standalone app so supervisors can review or correct pot-pour, THCA-path, and HTE-path state directly on the run.
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
- Added inventory import regression coverage for header detection, manual mapping overrides, preview rendering, and tracked lot updates by tracking ID.
- Added regression coverage for purchase edit round-trip of mobile opportunity fields, dedicated inventory lot editing, inventory label return paths, and confirmed-lot splitting from remaining inventory (`tests/test_refactor_safety.py`).
- Added duplicate-supplier regression coverage for mobile supplier create, main supplier create, and standalone buyer duplicate matching.
- Added extraction-charge, floor-queue, lifecycle-settings, inventory-action, and Slack-charge regression coverage for scan-to-charge, charge prefill into new run, charge-to-run linkage, pending/applied reactor queue visibility, active reactor board status rendering, direct inventory lot actions, lifecycle transition enforcement, cancel resolution redirects, and Slack import charge creation / split-allocation rejection; combined with the new extraction standalone coverage, the full Python suite now passes with `136` tests.
- Added standalone extraction mobile API regression coverage for workflow toggles, board and lot reads, charge creation, and lifecycle transitions, plus a standalone extraction app Node suite covering route parsing, touch-charge helpers, and API envelope handling.
- Added Phase 1 post-extraction regression coverage for charge-linked run handoff, pathway selection enforcement, wet-output confirmation enforcement, and standalone extraction mock API progression through the new post-extraction stage.
- Extended the extraction mobile and standalone regression coverage for Phase 2 downstream state fields, including pot-pour timing, THCA destination, and HTE decision / queue fields on the shared charge-linked run payload.
- Added downstream queue regression coverage for queue grouping, queue move actions, and run-form return context from the new queue page.

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
