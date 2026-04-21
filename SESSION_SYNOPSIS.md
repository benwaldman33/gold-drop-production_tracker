# Session Synopsis - 2026-04-20

This file is the current continuity checkpoint so work can resume quickly after an interruption.

## Current state

- Local working branch: `Claude_Consolidation`
- Local branch head: `15e58d1`
- Production branch: `main`
- Latest pushed `main` commit: `660bed5`
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

### 5. Open Run usability fix

Implemented and live:

- on the standalone `Reactors` board, `Open Run` is now a full-size primary button in the same action area as:
  - `Mark In Reactor`
  - `Mark Running`
  - `Mark Complete`
- this was done because the small inline `Open Run` link was too easy to miss on iPad

## Tests status

Latest verified status before closeout:

- standalone extraction app tests: `8 passed`
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

## Immediate next production check

The latest thing shipped was the standalone `Open Run` button promotion.

If resuming tomorrow, first confirm in production:

1. open `/extraction-lab/` on the iPad
2. go to `Reactors`
3. confirm `Open Run` appears as a large button on reactor cards with linked charges
4. confirm it is visually obvious before `Mark Running`
5. confirm the button opens the standalone run-execution screen correctly

## Recommended next development step

The next major step should be the next slice of standalone extractor execution, not more buying/receiving work.

Recommended priority order:

1. deepen standalone run execution so extractors can complete more of the actual run from the iPad without bouncing into the admin app
2. refine touch-first controls for any remaining Slack-message fields still not represented cleanly
3. add run-state / execution-state continuity on the standalone side after the run is started
4. after that, evaluate whether end-of-run outputs and exception handling should also live in the standalone app

## Recommended concrete next sprint

If there is no urgent bug tomorrow, the next sprint should likely focus on:

1. standalone run execution polish
   - review every field extractors currently send in Slack
   - confirm none still require awkward manual typing
   - convert any remaining free-text numeric inputs to counters / steppers / segmented controls where reasonable

2. standalone run lifecycle continuity
   - clearer state after `Open Run`
   - better operator path once timing begins
   - explicit save / continue / return-to-reactors flow

3. optional run completion layer
   - determine which completion fields belong in the standalone app versus the admin app
   - only then build touch-first completion / closeout flow

## Local note

There is still a local screenshot file in the repo root that was intentionally not committed:

- `screenshot Start Extraction Charge.png`

That file should remain out of Git unless explicitly requested.
