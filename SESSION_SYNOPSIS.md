# Session Synopsis - 2026-04-21

This file is the current continuity checkpoint so work can resume quickly after an interruption.

## Current state

- Local working branch: `Claude_Consolidation`
- Local branch head: `87f16d1`
- Production branch: `main`
- Latest pushed `main` commit: `2a94685`
- The extractor workflow is now live across:
  - main app `Floor Ops`
  - main app purchase / inventory lot actions
  - standalone extraction lab iPad app

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
- full Python suite: `138 passed`

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

The extraction-side workflow is intentionally paused at the design boundary.

The important clarification from the latest session:

- the newly supplied flow chart is **not** the extraction workflow itself
- it is the workflow **after extraction is complete**
- the next product area is therefore **post-extraction / post-processing orchestration**

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

Do not continue coding the extraction UX until the team confirms the real-world downstream process.

The next major build should be:

- `Phase 1 - Post-extraction session foundation`

which will introduce:

- run-type selection after extraction
- initial output capture confirmation
- a canonical post-extraction session linked to the run

## Recommended concrete next session

Before more implementation:

1. confirm the team-approved downstream workflow sequence
2. confirm which steps are required vs optional
3. confirm which decisions must be structured data
4. confirm whether THCA and HTE should be handled on one combined downstream screen or two linked screens

Only after that should development begin on the post-extraction workflow.

Tomorrow's work should start by defining:

1. the exact step order for one reactor
2. which steps are required
3. which steps are optional
4. which fields belong in each step
5. which defaults should prepopulate each step
6. which steps should be hidden until earlier steps are complete
7. what the completion / closeout experience should be

Once that is defined, the next build should be:

1. workflow spec for the guided reactor screen
2. screen layout / step model
3. implementation of the guided operator flow on top of the already-shipped charge + run progression system

## Local note

There is still a local screenshot file in the repo root that was intentionally not committed:

- `screenshot Start Extraction Charge.png`

That file should remain out of Git unless explicitly requested.
