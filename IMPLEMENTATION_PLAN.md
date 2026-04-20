# Gold Drop - Next Sprint Implementation Plan

The standalone extraction lab app is now scan-first. The next sprint should polish the operator continuity around that flow.

## Sprint Focus

Build `Scan-To-Charge Continuity Polish` on top of the existing standalone extraction app and extraction mobile API.

The business sequence remains:

1. Buy
2. Receive
3. Find or scan the lot
4. Charge into reactor / start extraction
5. Run / complete / cancel
6. Testing can occur before buy, after receipt, or after extraction depending on supplier trust and process stage

This sprint is about reducing friction after the scan screen is already in place: fewer taps, better guidance, and clearer handoff into the charge form.

## Product Goal

Let extractors and assistant extractors open the standalone extraction app, scan or enter a lot label, land on a clearly confirmed charge form, and keep their recent reactor preference without extra typing or guesswork.

## Why This Is Next

The repo already has:

- a deployed standalone extraction app
- extraction board, lot browser, and lifecycle actions
- `GET /api/mobile/v1/extraction/lookup/<tracking_id>`
- browser-camera barcode detection in the main app scan center
- canonical `ExtractionCharge` persistence and run handoff

What is still missing is the continuity around that entry path:

- the manual field should be ready immediately
- scan guidance should be explicit on the iPad screen
- successful lookup should be obvious when the operator lands on charge
- repeat charges should reuse the last reactor selection

## User Stories

### Extractor

- As an extractor, I can open `Scan / Enter Lot` and start typing or scanning immediately because the manual field is already focused.
- As an extractor, I can see clear scan guidance on the iPad without having to remember camera constraints or scanner behavior.
- As an extractor, I land on a charge form that clearly confirms the scanned lot and preselects the reactor I used most recently.

### Assistant extractor

- As an assistant extractor, I can still manually enter a tracking ID when camera scanning is unavailable.
- As an assistant extractor, I can repeat similar charges faster because the app remembers the last reactor used.

### Operations / audit

- As operations, I keep the same `ExtractionCharge` audit trail, lifecycle history, and `Floor Ops` continuity as before.

## Scope For This Sprint

### In scope

- auto-focus on manual tracking-ID entry when the scan route opens
- stronger scan guidance copy directly on the scan screen
- persisted recent-lot success context between scan and charge
- remembered last-used reactor on the charge form
- targeted frontend regression coverage for reactor default helpers and scan route continuity

### Out of scope

- new backend entities
- full standalone run editing
- device-scale integration inside the standalone app
- Slack work
- broader post-extraction testing UI

## UX Surfaces

### 1. Scan route continuity

Keep `#/scan` as the primary entry point, but tighten the screen so:

- the manual field is focused automatically
- scan guidance is visible without opening help text
- the operator sees the most recent resolved lot after a successful scan

### 2. Charge handoff clarity

When a lookup succeeds and the app lands on `#/lots/<id>/charge`:

- show a visible success banner that confirms the source tracking ID
- indicate whether the lookup came from the camera or manual entry
- make it clear that the last-used reactor is already selected

### 3. Reactor continuity

Persist the last-used reactor in local UI preferences so the next charge form:

- preselects the most recently used reactor
- still clamps that selection to configured reactor count

### 4. Preserve current presets and loop

Keep the existing fast-entry controls:

- `100 lbs`
- `Half lot`
- `Full lot`
- `Last used`
- `Open Run in Main App`
- `Back to Reactors`
- `Charge Another Lot`

## Backend Changes

No new backend objects are required.

Reuse existing endpoints:

- `GET /api/mobile/v1/extraction/lookup/<tracking_id>`
- `GET /api/mobile/v1/extraction/lots/<lot_id>`
- `POST /api/mobile/v1/extraction/lots/<lot_id>/charge`
- `POST /api/mobile/v1/extraction/charges/<charge_id>/transition`

## Proposed Route / Entry Changes

Standalone frontend routes should become:

- `#/login`
- `#/home`
- `#/reactors`
- `#/lots`
- `#/lots/<id>`
- `#/lots/<id>/charge`
- `#/scan`

## Test Plan

### Targeted tests during implementation

- route parsing still includes `#/scan`
- charge preset helpers still clamp `100 lbs` correctly
- reactor default helper clamps to configured reactor count
- mock/live standalone API lookup path still works

### Full-suite closeout before final commit

- standalone extraction app test suite
- full Python suite

## Definition Of Done

This sprint is done when:

- the scan screen focuses the manual field automatically
- scan guidance is visible on the scan screen
- a successful lookup leaves a clear visual confirmation on the charge form
- the charge form remembers and preselects the last-used reactor
- tests and docs are updated
