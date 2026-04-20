# Gold Drop - Next Sprint Implementation Plan

The main-app extraction workflow is now operational. The next sprint should package that workflow into a dedicated standalone app for extractors and assistant extractors.

## Sprint Focus

Build `Standalone Extraction Lab App` on top of the existing extraction-charge, reactor-board, and lifecycle APIs.

The business sequence remains:

1. Buy
2. Receive
3. Charge into reactor / start extraction
4. Run / complete / cancel
5. Testing can occur before buy, after receipt, or after extraction depending on supplier trust and process stage

This sprint is about isolating the extractor-facing UI, not creating a second extraction process model.

## Product Goal

Give extractors and assistant extractors a fast, touch-friendly interface that mirrors the main extraction workflow without the noise of the broader admin app.

## Why This Is Next

The repo already has:

- persisted `ExtractionCharge`
- reactor lifecycle controls
- `Floor Ops` board, queue, and history
- charge creation from purchases, scans, and Slack preview
- mobile session-cookie auth and capability envelopes for standalone apps

What is still missing is a dedicated frontend that lets floor operators do their work without navigating the full desktop app.

## User Stories

### Extractor

- As an extractor, I can sign into a focused extraction app and immediately see reactor status, pending charges, and ready lots.
- As an extractor, I can charge a lot into a reactor with large touch targets instead of a dense admin form.
- As an extractor, I can move a charge through `In Reactor`, `Running`, `Completed`, or `Cancelled` from the same board.

### Assistant extractor

- As an assistant extractor, I can search or scan for a lot, review its readiness warnings, and record a charge with minimal typing.
- As an assistant extractor, I can use sliders, segmented controls, and quick time shortcuts instead of relying on a keyboard.

### Operations / audit

- As operations, I can keep using the same `ExtractionCharge` records, audit history, and run-prefill handoff that the main app already understands.

## Scope For This Sprint

### In scope

- new `standalone-extraction-lab-app/` frontend
- extraction workflow toggle in Settings and mobile capabilities
- extraction mobile API endpoints for board, lots, lot detail, lookup, charge create, and lifecycle transition
- touch-friendly charge form and reactor board UI
- run handoff link back into the main app when a charge is recorded
- regression coverage for the new extraction mobile endpoints

### Out of scope

- full standalone run-editing UI
- scanner camera UI inside the standalone extraction app
- connected-scale automation beyond current saved charge/run handoff
- post-extraction testing UI
- Slack remediation work

## UX Surfaces

### 1. Standalone home

Surface:

- floor snapshot
- active reactor board
- pending charge count
- ready-lot count

### 2. Reactor board

Each reactor card should show:

- current state
- lot / supplier / strain
- lbs
- charge time
- queue depth
- direct lifecycle actions

### 3. Lots screen

Operators should be able to:

- search lots by tracking id, supplier, strain, or batch id
- tap into a lot detail card
- open a charge form quickly

### 4. Charge form

The charge form should prefer:

- range slider for weight
- `- / +` nudges
- segmented reactor buttons
- `Now` shortcut for charge time
- optional notes field only when needed

### 5. Lifecycle continuity

After a charge is recorded, the app should:

- show success immediately
- return to the board or lot context cleanly
- offer a direct `Open Run in Main App` handoff

## Backend Changes

### Service boundary

Reuse the existing extraction-charge service and floor-board helpers.

Add or finish:

- extraction workflow toggle in Settings / bootstrapping
- extraction capability envelope in the mobile write API
- extraction mobile endpoints inside `gold_drop/mobile_module.py`

### Data rules

- `ExtractionCharge.source_mode = "standalone_extraction"` for charges created from the new app
- write `SCAN_RUN_PREFILL_SESSION_KEY` so the existing run form opens with the charge attached
- lifecycle transitions should reuse the same validation and audit history as `Floor Ops`

## Proposed Route / Entry Changes

Add standalone frontend routes within the app:

- `#/login`
- `#/home`
- `#/reactors`
- `#/lots`
- `#/lots/<id>`
- `#/lots/<id>/charge`

Use existing backend endpoints:

- `GET /api/mobile/v1/extraction/board`
- `GET /api/mobile/v1/extraction/lots`
- `GET /api/mobile/v1/extraction/lots/<id>`
- `GET /api/mobile/v1/extraction/lookup/<tracking_id>`
- `POST /api/mobile/v1/extraction/lots/<id>/charge`
- `POST /api/mobile/v1/extraction/charges/<id>/transition`

## Test Plan

### Targeted tests during implementation

- extraction capabilities expose the workflow toggle correctly
- extraction board and lot endpoints return operator-facing payloads
- standalone extraction charge creation records `source_mode="standalone_extraction"` and writes run-prefill session data
- lifecycle transition endpoint updates the charge state correctly
- standalone frontend API/domain tests cover board, lot search, and charge payload helpers

### Full-suite closeout before final commit

- full Python suite
- standalone extraction app test suite

## Definition Of Done

This sprint is done when:

- an operator can log into the standalone extraction app
- the app shows the active reactor board and ready lots
- the app can create an extraction charge with a touch-friendly UI
- the app can advance charge lifecycle states
- the created charge still appears correctly in the main app `Floor Ops`
- regression tests and docs are updated
