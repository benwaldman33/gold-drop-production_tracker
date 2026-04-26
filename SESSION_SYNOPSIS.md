# Session Synopsis - 2026-04-23

This file is the current continuity checkpoint so work can resume quickly after an interruption.

## Current state

- Local working branch: `Claude_Consolidation`
- Production branch: `main`
- The extractor workflow is now live across:
  - main app `Floor Ops`
  - main app purchase / inventory lot actions
  - standalone extraction lab iPad app
  - main app `Downstream Queues`

## What is working now

### 1. Main extraction workflow

Implemented and live:

- persisted `ExtractionCharge` lifecycle
- lot charging from:
  - `Purchases -> Edit -> Charge Lot`
  - `Inventory -> Biomass On Hand -> Charge`
  - scanned lot workflow
- `Floor Ops` now shows:
  - `Floor Snapshot`
  - `Extraction Readiness`
  - `Floor State Rollup`
  - `Active Reactor Board`
  - `Reactor Charge Queue`
  - `Reactor History Today`
  - `Recent Scan Activity`
  - `Recently Applied Charges`

### 2. Reactor lifecycle controls

Implemented and live:

- explicit charge states:
  - `pending`
  - `in_reactor`
  - `running`
  - `completed`
  - `cancelled`
- lifecycle actions on reactor cards:
  - `Mark In Reactor`
  - `Mark Running`
  - `Mark Complete`
  - `Cancel Charge`
- same-day lifecycle visibility and history
- settings controls under `Settings -> Operational Parameters` for:
  - showing / hiding lifecycle states
  - making states required / optional
  - requiring a linked run before `Mark Running`
  - board history visibility

### 3. Standalone extraction lab app

Implemented and live:

- touch-first standalone app served from `/extraction-lab/`
- `Home`
- `Reactors`
- `Lots`
- `Scan / Enter Lot`
- camera scan, Bluetooth scanner entry, and manual tracking-id entry
- default `100 lbs` charge preset per reactor when available
- additional presets:
  - `Half lot`
  - `Full lot`
  - `Last used`
- last-reactor recall
- scan guidance and auto-focus for faster iPad use

### 4. Standalone run execution workflow

Implemented and live:

- after charge, extractor can open a dedicated standalone run-execution screen
- inherited context is prefilled from the charge:
  - reactor
  - source lot
  - strain
  - source / supplier
  - biomass weight context
- structured run execution fields now exist in the backend and main run form for:
  - run/fill start and end
  - biomass blend `% milled / % unmilled`
  - flush count and total weight
  - fill count and total weight
  - stringer basket count
  - CRC blend
  - mixer start and end
  - flush start and end
  - notes
- touch-first timer buttons are available for time capture instead of relying on keyboard entry
- `Settings -> Operational Parameters -> Extraction run defaults` now prepopulates:
  - default milled %
  - fill count
  - total fill weight
  - flush count
  - total flush weight
  - stringer basket count
  - CRC blend

### 5. Guided run progression

Implemented and live:

- the standalone run screen now shows the current stage and the next allowed actions
- progression is now guided through:
  - `Confirm Vacuum Down`
  - `Record Solvent Charge`
  - `Start Primary Soak`
  - `Start Mixer`
  - `Stop Mixer`
  - `Confirm Filter Clear`
  - `Start Pressurization`
  - `Begin Recovery`
  - `Begin Flush Cycle`
  - `Verify Flush Temps`
  - `Record Flush Solvent Charge`
  - `Start Flush`
  - `Stop Flush`
  - `Confirm Flow Resumed`
  - `Start Final Purge`
  - `Stop Final Purge`
  - `Confirm Final Clarity`
  - `Complete Shutdown`
  - `Mark Run Complete`
- the mobile extraction run endpoint now returns a derived `progression` payload
- `POST /api/mobile/v1/extraction/charges/<charge_id>/run` now accepts `progression_action`
- a dedicated `run_completed_at` timestamp is now stored on `Run`
- when a run is completed from the standalone workflow, the linked charge is also completed when that charge is still the active reactor event
- the main run form now shows:
  - current extraction progression stage
  - progression description
  - completed timestamp

### 6. Open Run usability fix

Implemented and live:

- on the standalone `Reactors` board, `Open Run` is now a full-size primary button in the same action area as:
  - `Mark In Reactor`
  - `Mark Running`
  - `Mark Complete`
- this was done because the small inline `Open Run` link was too easy to miss on iPad

### 7. Post-extraction queue surfaces

Implemented and live:

- the main app now includes `Downstream Queues`
- queue sections currently include:
  - `Needs Queue Decision`
  - `GoldDrop production queue`
  - `Liquid Loud hold`
  - `Terp strip / CDT cage`
  - `HP base oil hold`
  - `Distillate hold`
- queue cards show:
  - run date and reactor
  - source strain / supplier / tracking IDs
  - wet and dry THCA / HTE totals
  - current THCA destination and HTE decision context when present
  - `Open Run`
- supervisors can move a run between downstream queues/holds or mark the queue item complete without editing the full run
- opening a run from this page now preserves `Back to Downstream Queues`

### 8. GoldDrop production queue workflow

Implemented and live:

- `GoldDrop Production Queue` now has its own dedicated main-app page
- the queue page is reached from `Downstream Queues -> Open GoldDrop Queue`
- each queue card now shows:
  - current queue state
  - source strain / supplier / lot context
  - wet and dry THCA / HTE totals
  - queue history with timestamps and operator names
- queue actions now include:
  - `Mark Reviewed`
  - `Queue For Production`
  - `Release Complete`
  - `Send Back For Re-routing`
- queue actions are stored in the new additive `DownstreamQueueEvent` table so production gets history without any destructive schema rewrite
- opening a run from this page now cleanly returns through the downstream queue context

### 9. Additional destination-specific queue workflows

Implemented and live:

- `Liquid Loud Hold` now has its own dedicated main-app page
- `Terp Strip / CDT Cage` now has its own dedicated main-app page
- `HP Base Oil Hold` now has its own dedicated main-app page
- `Distillate Hold` now has its own dedicated main-app page
- all three use the same additive `DownstreamQueueEvent` history model as GoldDrop
- `Liquid Loud Hold` can:
  - `Mark Reviewed`
  - `Reserve For Liquid Loud`
  - `Release To GoldDrop Queue`
  - `Release Complete`
  - `Send Back For Re-routing`
- `Terp Strip / CDT Cage` can:
  - `Mark Reviewed`
  - `Queue Prescott`
  - `Strip Complete`
  - `Send Back For Re-routing`
- `HP Base Oil Hold` can:
  - `Mark Reviewed`
  - `Confirm Hold`
  - `Release Complete`
  - `Send Back For Re-routing`
- `Distillate Hold` can:
  - `Mark Reviewed`
  - `Confirm Hold`
  - `Release Complete`
  - `Send Back For Re-routing`

## Tests status

Latest verified status before closeout:

- standalone extraction app tests: `8 passed`
- Phase 1 post-extraction foundation is now implemented on the run itself:
  - downstream pathway select (`100 lb pot pour` / `200 lb minor run`)
  - `Start Post-Extraction`
  - `Confirm Initial Outputs`
  - wet THCA / wet HTE confirmation gate
- Phase 2 downstream state tracking is now also implemented on the same run:
  - pot-pour warm off-gas timing, stir count, centrifuge handoff
  - THCA oven timing, milling time, THCA destination
  - HTE off-gas timing, clean/dirty, Prescott, potency, and queue-routing fields
- Phase 3 guided downstream workflow is now implemented in the standalone extraction app:
  - numbered downstream steps on `Open Run`
  - pathway-driven sequence
  - tap-first choice buttons for downstream decisions
- Phase 4 downstream queue surfaces are now implemented in the main app:
  - queue grouping and unresolved-routing visibility
  - move/complete actions
  - run-form return context from queue cards
- Phase 5 destination-specific queue workflow is now implemented for `GoldDrop Production Queue`:
  - dedicated queue page
  - queue-state history
  - review / production / release / send-back actions
- Phase 5 destination-specific queue workflow is now also implemented for:
  - `Liquid Loud Hold`
  - `Terp Strip / CDT Cage`
  - `HP Base Oil Hold`
  - `Distillate Hold`
- full Python suite: `164 passed`

The following policy is in effect for future work:

- targeted tests during implementation/debugging
- full Python suite before final commit
- relevant standalone app test suites before final commit when those apps change

## Deployment pattern now required for standalone extraction changes

For extraction-app changes, production deployment requires both backend sync and static file copy:

```bash
cd /opt/gold-drop
git fetch origin
git checkout main
git pull --ff-only origin main
sudo systemctl restart golddrop
sudo systemctl status golddrop --no-pager -l
sudo rsync -av --delete /opt/gold-drop/standalone-extraction-lab-app/ /var/www/extraction-lab/
```

Notes:

- no `nginx` reload is needed unless Nginx config itself changes
- after `rsync`, the iPad browser must be reloaded

## Known deferred issue

Slack integration is currently deferred pending Slack-side investigation.

Current known state:

- none of the Slack integration is believed working end-to-end right now
- likely issue is on the Slack app / channel / scope side rather than Gold Drop code
- previously observed channel-history failure:
  - `Could not sync: #extraction-support`
- likely causes already identified:
  - bot not invited to channel
  - channel may now be private
  - missing `groups:read` / `groups:history`
  - stale channel name vs channel ID
  - app not reinstalled after scope/token changes

User planned next action on Slack:

- check with the Slack Administrator to confirm what changed

Do not resume Slack code changes unless new evidence suggests the Gold Drop side is actually broken.

## Immediate checkpoint

There is no urgent production bug open right now.

The active work area is now the extraction booth SOP alignment layer that sits between charge creation and downstream post-processing.

## Project status summary

### Done

- upstream extraction workflow is live end-to-end:
  - charge creation
  - reactor lifecycle management
  - standalone extraction iPad workflow
  - guided run progression through completion
- post-extraction foundation is live on the `Run` record:
  - pathway selection
  - wet output confirmation
  - THCA / HTE downstream state fields
- downstream operational queue surfaces are live:
  - shared `Downstream Queues` board
  - dedicated destination pages for:
    - `GoldDrop Production Queue`
    - `Liquid Loud Hold`
    - `Terp Strip / CDT Cage`
    - `HP Base Oil Hold`
    - `Distillate Hold`
- destination queue history is live through additive `DownstreamQueueEvent` records
- extraction booth SOP foundation is now live:
  - additive `ExtractionBoothSession`, `ExtractionBoothEvent`, and `ExtractionBoothEvidence`
  - booth-stage progression from vacuum confirmation through shutdown completion
  - booth-specific validation for solvent charge, flush temps, flow resumed, final clarity, and shutdown checklist
  - booth evidence upload support for solvent chiller and plate temperature photos
  - exception/retry loops for flow adjustment and additional final-purge work
  - timing targets and timing-status payloads for the core booth timers
  - supervisor booth-review surface on the main run form
  - supervisor notifications inbox on the main dashboard
  - acknowledgement and resolve actions for booth/run alerts
  - supervisor `Approve Deviation` / `Require Rework` control actions with recorded reasons
  - outbound Slack routing by notification class (`completions`, `warnings`, `reminders`)
  - required operator reasons for off-target timing and booth exception paths
  - per-step timing-policy enforcement for booth timers:
    - defaults remain permissive (`warning` for primary soak / mixer / flush and `informational` for final purge)
    - steps can be tightened to `Require supervisor override` or `Hard stop`
    - override-required timing misses now block later booth progression until a supervisor approves the deviation
    - active timing policy blocks are visible in the main-app `Booth Review` surface
  - reminder automation for unresolved supervisor alerts:
    - warning / critical booth alerts can emit one durable reminder after a configurable delay
    - reminder delay is configured separately for `critical` vs `warning` alerts
    - reminders route through the existing `reminders` Slack webhook class when outbound Slack delivery is enabled
    - resolving the source supervisor alert automatically resolves its reminder
  - first downstream queue deepening slice is now live in `GoldDrop Production Queue`:
    - GoldDrop is no longer a flat action list
    - runs move through `Reviewed`, `Queued for production`, `In production`, `Packaging ready`, and `Released complete`
    - available actions are now stage-specific
    - final release is blocked until the run reaches packaging-ready state
  - second downstream queue deepening slice is now live in `Liquid Loud Hold`:
    - Liquid Loud is no longer a flat hold/release list
    - runs move through `Reviewed`, `Reserved for Liquid Loud`, and `Release ready`
    - release actions are now stage-specific
    - `Release To GoldDrop Queue` / `Release Complete` are blocked until release-ready state is reached
  - third downstream queue deepening slice is now live in `Terp Strip / CDT Cage`:
    - Terp Strip is no longer a flat strip-action list
    - runs move through `Reviewed`, `Queued for Prescott`, `Strip in progress`, and `Strip complete`
    - strip actions are now stage-specific
    - `Strip Complete` is blocked until strip work has started
  - downstream queue ownership / accountability is now first-class across active downstream destinations:
    - queue items can now be assigned to a specific editor from the shared `Downstream Queues` board or the dedicated destination queue pages
    - current owner, assignment time, and assigning user are visible on both surfaces
    - owner state clears automatically when a queue item leaves active downstream management
  - downstream queue reporting is now visible directly on the queue surfaces:
    - the shared board shows queue aging, blocked count, stale count, completions in the last 7 days, and rework in the last 30 days
    - individual queue cards now show queue age plus stale / blocked status
    - dedicated destination pages show the same age / stale / blocked view for their own queue
  - `HP Base Oil Hold` and `Distillate Hold` are now staged workflows instead of flat hold/release surfaces:
    - both now move through `Reviewed`, `Hold confirmed`, `Release ready`, and `Released complete`
    - final release is blocked until release-ready state is reached

### In progress

- the active product area is no longer only downstream execution
- the current product area is downstream queue deepening on top of the booth-SOP foundation:
  - making destination queues behave like real work surfaces instead of generic hold lists
  - deciding how far to push downstream completion / rework semantics now that all current destination surfaces are staged or owned
  - deciding where queue reporting should live beyond the queue surfaces themselves

### Next

- deepen the downstream operating model after queue staging:
  - decide whether downstream completion should stamp stronger final outcome states instead of simply removing the item from queue management
  - decide whether rework / send-back paths now need richer destination-specific reasons or resolution tracking
  - decide whether queue reporting should also surface on the main dashboard or a dedicated reporting page
- keep repeated reminder escalation on the future list, but not on the current critical path

## Current planning baseline

`IMPLEMENTATION_PLAN.md` has been replaced with the new planning target:

- `Post-Extraction Workflow Orchestration`

The documented source flow now begins after:

- charge
- reactor execution
- guided run progression
- initial output capture

and then branches into:

- `100 lb pot pour`
- `200 lb minor run`

with downstream:

- `THCA path`
- `HTE path`
- timers / hold steps
- decision gates
- queue / hold / rework outcomes

## Recommended next development step

The next major build should stay in downstream execution, but move past queue staging itself:

- turn downstream completion and rework into stronger tracked outcomes instead of mostly queue removal
- decide whether queue reporting now belongs on the main dashboard or a dedicated reporting surface

## Recommended concrete next session

When work resumes, decide the next downstream operating slice after queue reporting and staged holds and confirm:

1. whether downstream completion should simply clear a queue item or stamp a stronger destination-specific completion state
2. what rework needs next: send-back reasons, rework categories, or tracked resolution states
3. whether queue reporting should stay embedded in queue surfaces or expand into dashboard / reporting pages
4. whether ownership should later expand from single-owner assignment into explicit handoff / team-state tracking

The likely implementation order is:

1. stronger downstream completion/rework tracking
2. broader reporting and management visibility
3. later ownership refinements if needed

## Genealogy foundation update

The app now has the first additive derivative-lot genealogy foundation in place:

- new first-class genealogy tables:
  - `MaterialLot`
  - `MaterialTransformation`
  - `MaterialTransformationInput`
  - `MaterialTransformationOutput`
  - `MaterialReconciliationIssue`
- `PurchaseLot` now bridges into genealogy through `material_lot_id`
- startup bootstrap now backfills active biomass lots into `MaterialLot(type=biomass)`
- helper logic now resolves source biomass material lots for a `Run`
- first-pass reconciliation now detects basic genealogy problems such as missing run source links and negative source balances

This is still foundation work only:

- no operator workflow changed yet
- current downstream queues still run off `Run`
- derivative output lots and manager-facing genealogy read surfaces are the next implementation slices

## Genealogy phase 4-6 update

The next genealogy milestone is now in:

- eligible extraction runs auto-create `MaterialTransformation(type=extraction)` rows
- accountable dry outputs now generate derivative `MaterialLot` rows for:
  - `dry_hte`
  - `dry_thca`
- extraction genealogy now records:
  - biomass source inputs
  - derivative output lots
  - cost basis on derivative dry-output lots when run cost-per-gram fields exist
- the internal API now exposes manager-facing derivative genealogy read surfaces:
  - `/api/v1/material-lots/<lot_id>`
  - `/api/v1/material-lots/<lot_id>/journey`
  - `/api/v1/material-lots/<lot_id>/ancestry`
  - `/api/v1/material-lots/<lot_id>/descendants`
- existing purchase / lot / run journeys now include derivative `material_lots`
- reconciliation overview now includes open material genealogy issues

Practical meaning:

- a manager can now start from a run and see the accountable dry HTE / THCA derivative lots created from it
- a manager can start from a biomass purchase lot and trace forward into derivative extraction outputs
- a manager can start from a derivative dry-output lot and trace back to its biomass ancestry

What still remains after this slice:

- correction workflows
- deeper cost roll-forward beyond extraction outputs
- queue linking to derivative lots
- destination-native downstream transformations
- reporting surfaces built directly on genealogy

## Genealogy phase 7 update

Correction-forward genealogy is now in place:

- managers/editors can open `/material-lots/<lot_id>/correct`
- correction actions now create explicit `MaterialTransformation` rows instead of silently rewriting existing genealogy
- supported correction actions:
  - `adjust_quantity`
  - `replace_parent`
  - `void_lot`
- quantity adjustments and parent replacements now:
  - close the original lot
  - preserve the original lineage record
  - create a replacement `MaterialLot`
- void actions now close the mistaken lot through a correction transformation with no replacement output
- open reconciliation issues on the corrected lot are automatically resolved with the correction note

Practical meaning:

- managers can now fix a bad derivative-lot quantity without deleting history
- managers can now replace an incorrect parent link without hiding the original mistake
- the genealogy layer now has the first real correction trail instead of being read-only

## Genealogy phase 8 update

Cost roll-forward visibility is now exposed directly:

- extraction-created derivative lots already carried cost basis from run cost-per-gram fields
- correction-created replacement lots now preserve cost-per-unit context from the corrected lot
- the internal API now exposes `/api/v1/summary/material-costs`
- that summary groups open derivative lots by `lot_type` and shows:
  - lot count
  - open quantity
  - open cost basis total
  - average cost basis per unit

Practical meaning:

- managers can now answer not just "what derivative lots exist?" but also "what open cost basis is sitting in derivative inventory by type?"
- the genealogy layer now supports the first real cost-aware inventory summary without waiting for the broader reporting phase

## Genealogy phase 9 update

Derivative genealogy is now visible directly on downstream queue surfaces:

- the shared `Downstream Queues` board now shows any linked derivative lots already created from a run
- dedicated destination queue pages now show the same derivative lot context on each queue card
- queue cards now render:
  - derivative lot type
  - derivative lot tracking ID
  - direct journey links for each linked derivative lot
- queue workflow ownership remains on `Run`; this slice only attaches genealogy visibility to the existing downstream operations UI

Practical meaning:

- supervisors can now move from queue management directly into derivative lot lineage review without leaving the queue surfaces blind
- the genealogy layer is now visible in the real downstream operating workflow, not only in API or journey endpoints
- the next remaining genealogy milestones are destination-native downstream transformations and reporting built directly on those new genealogy nodes

## Genealogy phase 10 update

Destination-native downstream genealogy is now in place:

- the genealogy layer no longer stops at `dry_hte` / `dry_thca`
- downstream completion states can now create accountable child lots through explicit `MaterialTransformation` records:
  - `golddrop_production` -> `golddrop`
  - `thca_split` -> `wholesale_thca` or `liquid_diamonds`
  - `terp_strip` -> `terp_strip_output`
  - `hp_base_oil_conversion` -> `hp_base_oil`
  - `distillate_conversion` -> `distillate`
- parent extraction-output lots now update their consumed / remaining inventory state from downstream transformation usage instead of staying indefinitely open by default
- descendant chains can now continue beyond extraction and answer source-to-finished-product questions inside the genealogy model itself

Practical meaning:

- a manager can now follow biomass -> extraction output -> downstream product lot in one lineage chain
- downstream completion no longer only clears a queue item; it can now create the next accountable lot node for genealogy
- the remaining genealogy milestone is the reporting layer built directly on these new downstream lot and transformation records

## Genealogy phase 11 update

The first genealogy reporting layer is now in place:

- the main app now has a dedicated `Genealogy Report` page at `/reports/material-genealogy`
- the internal API now exposes `/api/v1/summary/material-genealogy`
- reporting now covers:
  - open derivative inventory by type
  - released derivative inventory by type
  - source-to-derivative yield rows by biomass lot
  - rework volume from correction-backed genealogy transformations
  - open reconciliation issues
  - recent derivative lots with direct ancestry / descendants / journey links

Practical meaning:

- genealogy is no longer just a set of point lookups; managers now have a working summary surface
- the app can now answer both the lineage question and the “what is sitting open / released / problematic right now?” question from one reporting layer
- the initial phased genealogy implementation is now functionally complete from schema through downstream reporting

## Genealogy phase 12 update

The HTML genealogy viewer is now in place:

- the main app now has a dedicated `Material Journey Viewer` page at `/journeys/material-genealogy`
- the viewer supports:
  - `By Lot`
  - `By Run`
- `By Lot` now renders:
  - material-lot summary
  - journey timeline
  - ancestry chain
  - descendant transformations
- `By Run` now renders:
  - run summary
  - run timeline
  - source lots / allocations
  - derivative-lot drill links
- the `Genealogy Report` page now links into this viewer
- downstream queue cards now open linked derivative lots in this viewer instead of landing only on raw API JSON
- the left-sidebar `Genealogy Report` label was also normalized to remove the recurring malformed leading-character artifact for that item
- browser-safe raw payload links now exist at `/journeys/material-genealogy/raw`, so logged-in users can open raw run/material genealogy JSON without hitting bearer-token API auth errors
- the full left sidebar now uses ASCII-safe icon tokens, eliminating the broader malformed leading-character issue across the menu

Practical meaning:

- the earlier `lot-journey-v2.html` concept now exists as a real in-app surface instead of only a mockup
- managers can start from a lot or a run and stay inside the app while tracing lineage
- the genealogy stack now has both:
  - reporting
  - interactive HTML path tracing
- the main app no longer mixes session-auth HTML navigation with token-only API links in this genealogy flow

## Genealogy phase 13 update

The genealogy viewer now supports correction-forward manager work in context:

- `By Lot` now shows:
  - open reconciliation issues
  - correction history for that lot
  - a direct `Correct This Lot` action
- the existing correction form at `/material-lots/<lot_id>/correct` now accepts a safe `return_to` path and returns the user to the viewer after a correction when launched from genealogy
- viewer labels were also clarified:
  - `Raw Detail` -> `View JSON`
  - `Raw Journey` -> `View JSON`
  - report-side raw lineage links now read `Ancestry JSON` / `Descendants JSON`

Practical meaning:

- genealogy is no longer only reporting plus tracing; it now supports the first real manager correction loop in the same workflow
- a manager can now:
  - identify a lineage problem
  - open the correction action
  - record the fix
  - return to the same genealogy surface without dropping out to unrelated admin screens

## Genealogy phase 14 update

Run reconciliation is now in the viewer:

- `By Run` now includes a `Run Reconciliation` section
- that section shows:
  - open genealogy issues tied to the run
  - source-allocation exceptions already present on the run journey
  - direct links into affected derivative lots when an issue is lot-specific

Practical meaning:

- a manager can now investigate lineage problems from the run outward instead of starting only from a lot
- the genealogy viewer now supports both:
  - lot-level correction workflow
  - run-level reconciliation review

## Genealogy phase 15 update

The genealogy issue queue is now in place:

- the main app now has a dedicated `Genealogy Issue Queue` at `/reports/material-genealogy/issues`
- issues now support:
  - owner assignment
  - statuses:
    - `open`
    - `investigating`
    - `needs_follow_up`
    - `resolved`
  - working notes
  - recent audit-history display
- both `Genealogy Report` and `Material Journey Viewer` now link into the queue

Practical meaning:

- unresolved genealogy problems can now be managed as a work queue instead of only being discovered ad hoc
- the reconciliation workflow now has:
  - run-level investigation
  - lot-level correction
  - issue ownership and status tracking

## Genealogy phase 16 update

Genealogy-based cost and yield reporting is now in place:

- `Material Genealogy Report` now includes:
  - source-lot input quantity plus rolled descendant cost basis
  - `Run Yield And Cost Review`
  - `Correction Impact On Reported Yield`
  - rework summary with output cost basis

Practical meaning:

- genealogy reporting now ties together:
  - lineage
  - reconciliation
  - rolled-forward cost
  - recent yield / correction impact
- managers can now use one report surface to answer not just "where did this come from?" but also "what did it cost, and how much correction/rework affected the reported output?"

## Genealogy phase 17 update

Genealogy issue lifecycle automation is now in place:

- the issue queue now supports explicit actions:
  - `Start Investigating`
  - `Mark Follow-Up`
  - `Resolve With Note`
  - `Reopen`
- the queue now supports manager filters for:
  - status
  - severity
  - owner
  - age / overdue state
- unresolved genealogy issues now track reminder metadata:
  - `reminder_count`
  - `last_reminded_at`
  - `next_reminder_due_at`
- stale unresolved issues now escalate automatically into `needs_follow_up`
- the lot correction form now asks how linked genealogy issues should be handled after a correction:
  - resolve linked issues
  - keep linked issues in follow-up
  - leave linked issues open
- the lot and run reconciliation surfaces inside `Material Journey Viewer` now show issue reminder state and link directly back into the issue queue

Practical meaning:

- genealogy issues are now actively supervised instead of only being assignable
- managers can focus on the oldest, highest-risk, or unowned genealogy problems quickly
- correction work now closes the loop more cleanly with issue management instead of leaving follow-up implicit

## UX / product-structure planning update

A first-pass UX restructuring plan is now documented in:

- `UX_ROLE_WORKFLOW_PLAN.md`
- `UX_ROLE_WORKFLOW_IMPLEMENTATION_PLAN.md`

Core direction:

- stop treating all functions as first-level peers in the main app
- reorganize the product by role, frequency, and device context
- keep high-frequency operational work visually primary
- move low-frequency / specialist / admin functions into second-level navigation
- use standalone apps more aggressively for focused operational workflows
- treat journey / genealogy as a daily manager workflow, not just a secondary reporting feature
- treat journey data as the foundation for future cost-to-produce and revenue forecasting

Recommended product split:

- standalone extraction app:
  - charge workflow
  - reactor board
  - booth SOP execution
  - immediate post-extraction handoff capture
- standalone receiving app:
  - receiving queue
  - receipt confirmation / correction
  - delivery photo capture
- standalone purchasing app:
  - buyer/mobile purchase opportunity workflow
- main app:
  - supervisor control surfaces
  - downstream routing and queue management
  - inventory and purchase review
  - genealogy and reporting
  - admin / maintenance

Recommended first implementation step:

- do a sidebar / information-architecture cleanup first
- add grouped top-level navigation, including a first-level `Journey` area plus a `More` bucket
- avoid changing deep workflows in the same sprint

Implementation sequencing is now documented separately in `UX_ROLE_WORKFLOW_IMPLEMENTATION_PLAN.md`, with the recommended order:

1. sidebar / navigation cleanup
2. role-based landing defaults
3. workflow rationalization across extraction / downstream / alerts / journey
4. standalone-app scope tightening
5. journey + financial visibility consolidation

The implementation phases are now shipped:

- the main app sidebar is grouped into `Purchasing`, `Inventory`, `Extraction`, `Downstream`, `Journey`, `Alerts`, `Settings`, and `More`
- users now land on a role-relevant workflow area, with last-section memory during the session
- `Alerts Home` and `Journey Home` now exist as dedicated manager surfaces
- extraction/downstream/journey copy now better distinguishes overview vs execution vs investigation
- the standalone purchasing and receiving apps now have clearer focused-purpose copy and direct handoffs back to main-app purchase review
- Journey now acts as a daily manager visibility surface for lineage plus cost-basis review, not just a secondary reporting area
- the grouped left sidebar is now collapsible by section, and `Departments` has been demoted to `Scorecards (beta)` inside `More`
- Journey now includes assumption-backed financial projections: Settings stores per-output expected selling prices, and Journey/Genealogy Report show projected revenue and gross margin for derivative inventory, source-lot descendants, and run yield/cost rows
- Settings is now a dedicated Super Admin-only sidebar group with section links into operational parameters, Journey financials, extraction controls, Slack/notifications, users/access, field intake, API clients, scales, remote sites, and maintenance
- Settings section links now open independent `/settings/...` subpages instead of scrolling one monolithic page, and Slack channel history sync has moved from Maintenance into `Settings -> Slack & Notifications`
- Journey Home now includes a manager dashboard layer for blocked/stale work, critical issues, aging derivative lots, low-margin runs, inventory value leaders, and 7/30 day projected revenue and margin based on recent genealogy-backed runs

## Deployment note

Current rollout commit:

- branch: `Claude_Consolidation`
- commit: `56b7d88`

Production deployment steps:

1. update the production checkout:
   - `git fetch origin`
   - `git checkout Claude_Consolidation`
   - `git pull --ff-only origin Claude_Consolidation`
2. restart the backend so the new grouped navigation, role-home routing, alerts/journey hubs, and mobile purchase-review handoff URLs are live
3. sync the standalone purchasing app static files
4. sync the standalone receiving app static files
5. verify in production:
   - the left sidebar is grouped into `Purchasing`, `Inventory`, `Extraction`, `Downstream`, `Journey`, `Alerts`, `Settings`, and `More`
   - `Alerts Home` renders at `/alerts`
   - `Journey Home` renders at `/journey`
   - `Role Home` sends users into a relevant workflow area
   - the standalone purchasing app shows `Open Purchase Review` on an opportunity detail
   - the standalone receiving app shows `Open Purchase Review` on a receiving detail

## Local note

There is still a local screenshot file in the repo root that was intentionally not committed:

- `screenshot Start Extraction Charge.png`

That file should remain out of Git unless explicitly requested.
