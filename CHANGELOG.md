# Changelog

## 2026-04-25

### Added
- `Material Journey Viewer` now includes a live Journey Graphic in both `By Lot` and `By Run` modes, visually mapping supplier/source biomass through extraction or transformation into derivative product lots before the detailed timeline, revenue, correction, and reconciliation panels.
- Internal API client discovery now uses a shared `services/api_registry.py` source of truth for API scopes and endpoint metadata, with regression coverage that compares the registry against registered `/api/v1` routes.
- API documentation now reflects the scanner, scale, material-cost, and material-genealogy endpoints that had drifted behind the implemented Internal API surface.
- `Settings -> Audit Log` now provides a searchable manager/admin surface for audit history with filters for date, user, action, entity type, text/details, and result limit.
- `Journey -> Finance & Accounting` now provides period revenue, estimated COGS, gross margin, product summaries, channel summaries, projected inventory value, financial flag counts, revenue-event detail, and CSV export.
- `Settings -> Access Control` now provides a dedicated Super Admin screen for role permission templates and per-user grants/revokes, separate from user creation.
- Import and export actions are now protected as separate permissions from ordinary screen access, so a user can view a section without automatically being able to bulk import or export its data.
- Standalone purchasing, receiving, and extraction app write capabilities now use the same access-control permission matrix instead of only the broad legacy role flags.
- Finance-sensitive Journey actions now have explicit permissions for financial CSV export, revenue recording, revenue voiding, and genealogy correction workflows.
- Journey Home now acts as a stronger manager dashboard with an attention strip for blocked/stale work, critical genealogy issues, aging derivative lots, and low-margin runs.
- Journey Home now includes an evidence-based revenue forecast using recent genealogy-backed run value, recent run rate or the configured run-rate fallback, and current Journey price assumptions.
- Settings subgroups now have independent pages under `/settings/...` instead of all landing on one long System Settings page.
- Slack channel history sync moved out of Maintenance and into `Settings -> Slack & Notifications`, next to the Slack channel, token, webhook, notification, and mapping controls it depends on.
- Settings is now its own Super Admin-only collapsible sidebar group, with section links for operational parameters, Journey financials, extraction controls, Slack/notifications, users, field intake, API clients, scales, remote sites, and maintenance.
- The default sidebar group order now follows the operating workflow priority: `Purchasing`, `Inventory`, `Extraction`, `Downstream`, `Journey`, `Alerts`, `Settings`, and `More`.
- Journey now has a configurable financial projection layer on top of material genealogy:
  - `Settings -> Operational Parameters` includes per-output assumed selling prices in dollars per gram
  - `Journey Home` and `Genealogy Report` now show projected revenue and projected gross margin for open inventory, released output, source-lot descendants, and run yield/cost rows
  - the projections are explicitly based on configured assumptions, leaving actual sales capture as a later accounting layer
- Journey now has the first actual-revenue layer on top of genealogy:
  - material lots can store revenue events with sold quantity, unit price, buyer/channel, reference, and notes
  - the Material Journey Viewer lets editors record actual revenue directly from a lot's `Revenue Actuals` panel
  - Journey Home and Genealogy Report now roll actual revenue into open/released inventory, source-lot descendants, and run-level yield/cost rows
  - Journey Home now flags actuals below projected revenue in an `Actuals Below Projection` variance review table
- Material revenue events can now be corrected or voided from the Material Journey Viewer without deleting audit history.
- Journey now surfaces financial completeness flags for missing cost basis, missing revenue assumptions, missing actual revenue on released lots, and open genealogy issues that may compromise financial reporting.
- Material Genealogy Report now has an `Export Financial CSV` action for product summaries, inventory groups, source-to-derivative rows, run yield rows, and financial completeness flags.
- Journey Home and Genealogy Report now include product-type financial summaries with quantity, cost basis, projected revenue, actual revenue, variance, actual margin, and flag counts.
- `Downstream -> Supervisor Console` now gives supervisors one launch-ready control surface for role coverage, open alerts, queue health, blocked/stale/unassigned downstream work, and handoffs into Floor Ops, Alerts, Journey, and destination queues.
- `LAUNCH_ROLE_COVERAGE.md` now documents the four operational launch roles: buyer, receiver/inventory, extractor, and supervisor/downstream.
- `Settings -> Launch Readiness` now provides an in-app blocker register for acceptance testing, with default launch items, owner/target/notes fields, and classifications for launch blockers, pilot blockers, post-launch items, and wishlist items.
- The grouped left sidebar is now collapsible by section, so users can expand only the workflow area they are using and keep other submenu items out of the way.
- `Departments` has been demoted inside `More` and relabeled `Scorecards (beta)` to reflect that it is not currently a primary operating workflow.
- The UX role/workflow restructuring phases are now implemented in the main app:
  - grouped top-level sidebar navigation for `Purchasing`, `Inventory`, `Extraction`, `Downstream`, `Journey`, `Alerts`, `Settings`, and `More`
  - role-aware home routing with session memory for the last active top-level workflow area
  - dedicated `Alerts Home` and `Journey Home` manager hubs
  - clearer separation between extraction overview (`Extraction dashboard`), execution (`Floor Ops`), record management (`Runs`), downstream overview (`Downstream Queues`), and investigation (`Journey`)
- `Journey Home` now consolidates genealogy visibility with manager-facing cost-basis context:
  - open vs released derivative output mix
  - recent run yield and derivative cost review
  - downstream blocked-work visibility
- The standalone purchasing and receiving apps are now more explicitly scoped as focused operational tools, with clearer purpose copy and direct `Open Purchase Review` / `Open in Main App` handoff links back to the main app.
- The first derivative-lot genealogy foundation is now live in the data model with additive `MaterialLot`, `MaterialTransformation`, `MaterialTransformationInput`, `MaterialTransformationOutput`, and `MaterialReconciliationIssue` tables.
- `PurchaseLot` now has a genealogy bridge field (`material_lot_id`) so each biomass inventory lot can map to a first-class material lot without changing the current lot workflow.
- A new genealogy helper service now backfills biomass `MaterialLot` rows from active `PurchaseLot` rows and resolves source biomass material lots for a run.
- The first genealogy reconciliation checks are now available for runs, including missing source-allocation / missing-input-link and negative-balance detection.
- Extraction runs with accountable dry outputs now auto-create additive genealogy records:
  - one `MaterialTransformation(type=extraction)` per eligible run
  - `dry_hte` and `dry_thca` derivative `MaterialLot` rows
  - transformation input/output rows linking biomass source lots to derivative extraction outputs
- The internal API now exposes first manager-facing derivative genealogy surfaces:
  - `/api/v1/material-lots/<lot_id>`
  - `/api/v1/material-lots/<lot_id>/journey`
  - `/api/v1/material-lots/<lot_id>/ancestry`
  - `/api/v1/material-lots/<lot_id>/descendants`
- Existing purchase / lot / run journey payloads now include derivative `material_lots`, so managers can trace biomass source lots forward into accountable dry HTE / THCA output lots.
- Reconciliation overview now includes open material genealogy issues alongside the existing Slack/import exception summary.
- Material genealogy now supports correction-backed workflows instead of silent rewrites:
  - quantity adjustment creates a correction transformation plus a replacement material lot
  - parent replacement creates a correction transformation plus a replacement material lot
  - mistaken derivative lots can be voided through a correction transformation with no replacement output
- A minimal manager correction route is now available at `/material-lots/<lot_id>/correct` for logged-in editors.
- Material genealogy cost visibility now includes `/api/v1/summary/material-costs`, which summarizes open derivative lots by lot type, quantity, and rolled-forward cost basis.
- Downstream queue genealogy is now visible directly on the shared `Downstream Queues` board and the dedicated destination queue pages. Queue cards now show linked derivative lot type/tracking badges plus direct journey drill links for any derivative lots already created from that run.
- Downstream genealogy now extends beyond extraction outputs into destination-native material transformations:
  - GoldDrop queue release can create `golddrop` lots through `golddrop_production`
  - THCA destination routing can create `wholesale_thca` or `liquid_diamonds` lots through `thca_split`
  - terp strip completion can create `terp_strip_output` lots
  - HP base oil release can create `hp_base_oil` lots
  - distillate release can create `distillate` lots
- Material genealogy now has a first reporting layer:
  - `/reports/material-genealogy` in the main app
  - `/api/v1/summary/material-genealogy` in the internal API
  - reporting now covers open/released derivative inventory by type, source-to-derivative yield, rework volume, open reconciliation issues, and recent derivative lots with lineage links
- Material genealogy reporting now includes actual revenue, actual margin, and projected-vs-actual variance wherever revenue events have been recorded.
- Material genealogy reporting now includes financial completeness flag counts and a review table for lots that need cost, revenue, or lineage cleanup before financial results should be trusted.
- Material genealogy now has a real in-app journey viewer at `/journeys/material-genealogy` with `By Lot` and `By Run` modes. It turns the earlier `lot-journey-v2` mockup direction into a logged-in HTML surface backed by the existing genealogy payloads, so managers can path-trace from a derivative lot to its source biomass or from a run to its derivative lots without landing in raw JSON.
- The `Genealogy Report` page and downstream queue cards now route managers into the HTML genealogy viewer instead of only offering raw API journey links.
- The `Genealogy Report` sidebar label/icon rendering was normalized to avoid stray leading mojibake characters, and engineering guidance now explicitly requires checking new sidebar items for malformed icon text before final commit.
- Logged-in browser-safe raw genealogy links are now available under `/journeys/material-genealogy/raw`, so `Raw Journey`, `Raw ancestry`, and `Raw descendants` no longer fail with missing bearer-token errors when opened from the main app.
- The shared left sidebar now uses ASCII-safe icon tokens for all navigation items, removing the broader mojibake artifact that was leaking malformed leading characters across the menu.
- The `Material Journey Viewer` now exposes genealogy operating controls instead of only passive read surfaces:
  - `Correct This Lot` links directly into the existing correction workflow
  - open reconciliation issues render in-context on the lot view
  - correction-forward history renders inline from correction transformations already recorded on the lot
- The `By Run` view in `Material Journey Viewer` now includes `Run Reconciliation`, showing open genealogy issues tied to the run, source-allocation exceptions from the run journey, and direct drill links into affected derivative lots.
- A managed `Genealogy Issue Queue` now exists at `/reports/material-genealogy/issues`:
  - ownership / assignee support on reconciliation issues
  - issue statuses for `open`, `investigating`, `needs_follow_up`, and `resolved`
  - working notes on the issue itself
  - recent issue history rendered from audit-log updates
- The genealogy report and viewer now both link directly into that issue queue.
- `Material Genealogy Report` now includes genealogy-based cost and yield reporting:
  - source-lot input quantity plus rolled descendant cost basis
  - run-level yield/cost review rows
  - correction-impact reporting for replacement quantity and replacement cost basis
  - expanded rework summary including rolled output cost basis
- Correction-form navigation now supports a safe `return_to` path back into the viewer, so manager correction work can stay inside the genealogy workflow instead of bouncing back to the run or dashboard by default.
- `Raw Detail` and `Raw Journey` were relabeled to `View JSON`, and report-side raw lineage links are now labeled `Ancestry JSON` / `Descendants JSON` for clarity.
- The genealogy issue lifecycle is now operationally stronger:
  - explicit `Resolve With Note`, `Reopen`, `Start Investigating`, and `Mark Follow-Up` actions in the issue queue
  - queue filters for status, severity, owner, and age
  - reminder metadata plus overdue escalation for unresolved genealogy issues
  - correction-form follow-up controls so linked lot issues can be resolved, left open, or kept in follow-up when a correction is recorded
- The `Material Journey Viewer` lot/run reconciliation surfaces now show reminder state and link directly back into the issue queue.
- New planning documents now define the target model and phased rollout for true end-to-end material genealogy:
  - `DERIVATIVE_LOT_GENEALOGY_PLAN.md`
  - `DERIVATIVE_LOT_GENEALOGY_IMPLEMENTATION_PLAN.md`

### Changed
- Startup bootstrap now creates the genealogy foundation tables and backfills biomass material lots automatically using the same additive schema pattern the app already uses elsewhere.
- Startup bootstrap now also backfills the new genealogy issue lifecycle columns used for reopen tracking and reminder scheduling.

### Tests
- Added regression coverage for biomass material-lot backfill, run source-material resolution, and first-pass genealogy reconciliation issue creation.
- Added genealogy regression coverage for extraction transformation/output-lot creation, material-lot ancestry/descendant payloads, material-lot API endpoints, and the new route registration.
- Added correction-workflow regression coverage for replacement-lot quantity corrections and the new correction route registration.
- Added regression coverage for the material-cost summary endpoint and its route registration.
- Added downstream queue regression coverage ensuring GoldDrop queue cards render linked derivative lot genealogy without breaking the existing queue workflow surfaces.
- Added genealogy regression coverage for downstream child-lot creation across GoldDrop, THCA routing, terp strip, HP base oil, and distillate conversions.
- Added reporting regression coverage for the new material genealogy report page, the new summary endpoint, and route registration.
- Added regression coverage for the new HTML genealogy viewer in both lot and run modes, plus the updated report links into that viewer.
- Added regression coverage for the in-viewer correction entrypoint, issue rendering, and the browser-safe return path back to the genealogy viewer from the correction form.
- Added genealogy lifecycle regression coverage for reminder escalation, explicit resolve/reopen actions, filtered queue management, and correction-linked follow-up handling.

## 2026-04-24

### Added
- Extraction booth SOP alignment is now documented in `EXTRACTION_BOOTH_SOP_ALIGNMENT_PLAN.md`, translating the booth procedure into system behavior, fields, validations, and audit expectations.
- The extraction data model now includes additive booth-execution records: `ExtractionBoothSession`, `ExtractionBoothEvent`, and `ExtractionBoothEvidence`.
- The extraction mobile API now exposes `GET/POST /api/mobile/v1/extraction/charges/<charge_id>/run/evidence` for booth evidence uploads.

### Changed
- The `GoldDrop Production Queue` is now a staged downstream workflow instead of a flat action list. GoldDrop runs now move through `Reviewed`, `Queued for production`, `In production`, `Packaging ready`, and `Released complete`, with only the appropriate next actions available at each stage.
- The `Liquid Loud Hold` is now a staged downstream workflow instead of a flat hold/release list. Liquid Loud runs now move through `Reviewed`, `Reserved for Liquid Loud`, `Release ready`, and then into either `Release To GoldDrop Queue` or `Release Complete`, with release actions gated until the hold is marked release-ready.
- The `Terp Strip / CDT Cage` is now a staged downstream workflow instead of a flat strip-action list. Terp strip runs now move through `Reviewed`, `Queued for Prescott`, `Strip in progress`, and `Strip complete`, with completion gated until strip work has actually started.
- The `HP Base Oil Hold` and `Distillate Hold` now also behave like staged downstream workflows instead of flat hold/release lists. Both now move through `Reviewed`, `Hold confirmed`, `Release ready`, and `Released complete`, with final release blocked until the hold has been marked release-ready.
- The shared downstream destination queue template now shows stage-specific next-step guidance and hides queue actions once a run reaches a terminal queue state.
- Downstream queue ownership is now first-class on active queue items: supervisors can assign a queue owner from the shared `Downstream Queues` board or any dedicated destination queue page, and both surfaces now show the current owner plus assignment timing/context.
- Downstream queue ownership now clears automatically when a run leaves active downstream queue management through completion, release, or send-back actions.
- The shared `Downstream Queues` board and dedicated destination queue pages now include queue-reporting visibility for age, stale/blocked items, recent completions, and recent rework volume.
- The standalone extraction workflow now follows booth-SOP checkpoints instead of only the earlier coarse progression buttons. The current guided flow covers vacuum confirmation, solvent charge, primary soak, mixer, filter clear, pressurization, recovery, flush-cycle setup, flush temperature verification, flush solvent charge, flow-resumed confirmation, final purge, final clarity, shutdown checklist completion, and final run completion.
- The standalone extraction run screen now captures booth-specific SOP data including primary solvent charge, flush temperatures, flush solvent charge, flow-resumed decision, final clarity decision, final purge timing, shutdown checklist confirmations, and booth evidence uploads.
- The shared extraction progression service now drives booth-session stage state from the backend so the main app, mobile API, and standalone extraction app remain aligned on the active checkpoint, validations, and event history.
- Extraction run payloads now include booth-session history, evidence counts, and booth-specific timestamps alongside the existing run summary and downstream handoff fields.
- Startup schema bootstrap now creates and backfills the booth-session and booth-evidence schema needed for the new extraction workflow in this environment.
- Booth exception handling now supports non-happy-path loops: operators can mark flow as still adjusting, return to the flow check, mark final clarity as not yet acceptable, and resume another purge pass without breaking the run workflow.
- `Settings -> Operational Parameters` now also includes extraction booth timing targets for primary soak, mixer, flush soak, and optional final purge duration.
- Extraction run payloads and the standalone extraction UI now include timing-control status for the core booth timers so operators can see whether each timed step is not started, active, on target, or short against the configured SOP targets.
- The main run form now includes a supervisor-facing `Booth Review` surface showing current booth stage, timing status, deviation flags, recent booth history, and linked booth evidence without leaving the admin edit screen.
- The main dashboard now includes a `Supervisor Notifications` inbox for open booth/run alerts, with acknowledge and resolve actions plus direct run links for review.
- Booth workflow deviations and run completion now create durable `SupervisorNotification` records with linked `NotificationDelivery` rows so supervisor alerting is stored in-app before any Slack delivery is attempted.
- Slack settings now support outbound notification routing by class (`completions`, `warnings`, `reminders`) through optional class-specific webhook URLs, while keeping Slack read/sync concerns separate.
- Booth deviations that proceed off-target now require an operator reason, and that reason is stored on both the booth event trail and the linked supervisor notification.
- Supervisor notification cards now support explicit `Approve Deviation` and `Require Rework` decisions with a required supervisor reason, so deviation handling is recorded as a real control action instead of only an acknowledgement.
- `Settings -> Operational Parameters` now includes per-step extraction timing policies for primary soak, mixer, flush soak, and final purge. Defaults stay permissive (`warning` for soak/mixer/flush and `informational` for final purge), but each step can now be tightened to `Require supervisor override` or `Hard stop` for training or intervention cases.
- Booth progression now enforces those timing policies: `warning` and `informational` continue the workflow, `Require supervisor override` records a critical deviation and blocks later progression until approval exists, and `Hard stop` prevents the off-target stop action immediately.
- The main run form now shows timing policy labels and any active booth policy block directly in `Booth Review` so supervisors can see why a run cannot advance.
- Supervisor reminder automation is now live for unresolved booth alerts. The app can emit one durable `reminder` notification after a configurable delay for unresolved warning/critical supervisor alerts, and those reminders can route to the dedicated Slack reminders webhook.
- `Settings -> Slack Integration` now includes reminder automation controls for enabling/disabling reminders plus separate delay thresholds for critical vs warning alerts.

### Tests
- Extended extraction mobile API regression coverage for the booth-SOP sequence through shutdown and run completion.
- Extended standalone extraction app regression coverage for the booth-SOP sequence and aligned mock-mode progression with the backend stage model.
- Added regression coverage for booth exception-handling loops and timing-control payloads.
- Added run-form regression coverage for the new supervisor booth-review surface.
- Added regression coverage for the supervisor dashboard notification surface and acknowledgement flow.
- Added regression coverage for operator-reason validation on booth deviations and supervisor deviation approval recording.
- Added regression coverage for timing-policy enforcement, including permissive default continuation and supervisor-override blocking until approval.
- Added regression coverage for reminder creation, deduplication across repeated dashboard loads, and automatic reminder resolution once the source alert is closed.
- Added GoldDrop queue regression coverage for the deeper staged workflow, including stage-specific action visibility and blocking final release until packaging-ready state is reached.
- Added Liquid Loud queue regression coverage for staged hold/release flow, including gating release actions until the run reaches release-ready state.
- Added Terp Strip queue regression coverage for staged strip flow, including gating strip completion until active strip work has started.
- Added downstream queue ownership regression coverage for owner assignment visibility on the shared board and dedicated queue pages, plus automatic owner clearing when a queue item is released complete.
- Added downstream queue reporting regression coverage for queue-age display plus stale/blocked/rework/completion reporting on the shared board.
- Added staged hold regression coverage for `HP Base Oil Hold` and `Distillate Hold`, including gating release until the hold reaches release-ready state.
- Added regression coverage for material revenue-event capture, Journey Viewer revenue actuals, Genealogy Report actual revenue, and projected-vs-actual variance display.
- Added regression coverage for revenue-event update/void controls and financial completeness flag rendering.
- Added regression coverage for the material genealogy financial CSV export and product financial summary surfaces.
- Added regression coverage for the new Supervisor Console smoke path.
- Added regression coverage for Launch Readiness rendering and persisted register updates.

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
- The first destination-specific queue workflow is now live: `GoldDrop Production Queue` has its own dedicated main-app page with queue state history plus `Mark Reviewed`, `Queue For Production`, `Release Complete`, and `Send Back For Re-routing` actions.
- Additional destination-specific downstream workflows are now live in the main app: `Liquid Loud Hold`, `Terp Strip / CDT Cage`, and `HP Base Oil Hold` each now have dedicated queue pages with queue history plus destination-specific next-step actions instead of forcing supervisors to manage those holds from the generic routing board only.
- `Distillate Hold` now also has its own dedicated downstream workflow page, matching the same queue-history and action pattern as the other destination-specific hold surfaces.

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
- Opening a run from the dedicated `GoldDrop Production Queue` page now also returns cleanly to that queue surface via `Back to Downstream Queues`.
- The main app sidebar template now uses clean Unicode icons again, fixing the stray leading characters that appeared before `Downstream Queues` and other navigation labels when mixed-encoding bytes slipped into `base.html`.
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
- Added dedicated GoldDrop queue regression coverage for queue-page rendering, queue event history, and review/release actions.
- Added dedicated downstream destination queue regression coverage for Liquid Loud release-to-GoldDrop flow, Terp Strip / CDT cage progression, and HP Base Oil hold confirmation/release actions.
- Added dedicated Distillate hold regression coverage for queue-page rendering plus confirm/release actions.

## 2026-04-11

### Added
- Batch Journey documentation refresh across README, PRD, USER_MANUAL, FAQ, ENGINEERING, IMPLEMENTATION_PLAN, and ARCHITECTURE_REVIEW.

### Changed
- Journey routes now share centralized purchase-loading and error-handling helpers in `blueprints/purchases.py`.
- Journey export now validates `format` explicitly (`json`/`csv` only) and returns `400` with supported formats when invalid.
- `SystemSetting.get` now uses `db.session.get(...)` for SQLAlchemy 2.x-aligned model access.

### Tests
- Integration coverage includes unknown Journey export format handling (`tests/test_purchase_journey_api.py`).
