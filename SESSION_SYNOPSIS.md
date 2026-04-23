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
  - `Start Run`
  - `Start Mixer`
  - `Stop Mixer`
  - `Start Flush`
  - `Stop Flush`
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
- full Python suite: `163 passed`

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

The active work area is now the post-extraction / post-processing workflow, not the upstream extraction reactor flow.

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

The next major build should be the next post-extraction phase after queues:

- turn the downstream queue surfaces into richer role-based work queues with next-step actions and completion/rework handling by destination

Likely next queue-oriented surfaces:

1. `GoldDrop production queue`
2. `Liquid Loud hold`
3. `Terp strip / CDT cage`
4. `HP base oil hold`
5. `Distillate hold`

## Recommended concrete next session

When work resumes, decide the first destination-specific queue to deepen and confirm:

1. what the operator sees as the "next action" for that queue
2. whether queue completion should simply clear the queue or stamp a dedicated downstream completion state later
3. whether each queue needs its own role-specific screen or can stay on one shared board for now
4. which destination should become the first detailed workflow after queue placement

The likely implementation order is:

1. queue-specific next-step actions and labels
2. destination-specific detail surfaces
3. stronger downstream completion/rework tracking

## Local note

There is still a local screenshot file in the repo root that was intentionally not committed:

- `screenshot Start Extraction Charge.png`

That file should remain out of Git unless explicitly requested.
