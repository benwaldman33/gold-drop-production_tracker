# Gold Drop - Next Sprint Implementation Plan

The standalone extraction lab app is now live. The next sprint should make it truly scan-first for floor operators.

## Sprint Focus

Build `Scan-First Extraction Entry` on top of the existing standalone extraction app and extraction mobile API.

The business sequence remains:

1. Buy
2. Receive
3. Find or scan the lot
4. Charge into reactor / start extraction
5. Run / complete / cancel
6. Testing can occur before buy, after receipt, or after extraction depending on supplier trust and process stage

This sprint is about reducing keyboard dependence and shortening the path from label scan to reactor charge.

## Product Goal

Let extractors and assistant extractors open the standalone extraction app, scan or enter a lot label, apply a default 100 lb reactor charge when appropriate, and move straight into the next action without unnecessary navigation.

## Why This Is Next

The repo already has:

- a deployed standalone extraction app
- extraction board, lot browser, and lifecycle actions
- `GET /api/mobile/v1/extraction/lookup/<tracking_id>`
- browser-camera barcode detection in the main app scan center
- canonical `ExtractionCharge` persistence and run handoff

What is still missing is the fastest operator entry path:

- scan lot
- land on the lot immediately
- charge using presets
- charge another lot or open the run

## User Stories

### Extractor

- As an extractor, I can scan a lot label on the iPad and open the correct lot without typing.
- As an extractor, I can use a default 100 lb reactor charge preset instead of manually dragging a slider every time.
- As an extractor, I can record a charge and immediately choose whether to open the run, return to the reactor board, or charge another lot.

### Assistant extractor

- As an assistant extractor, I can still manually enter a tracking ID when camera scanning is unavailable.
- As an assistant extractor, I can use large preset buttons such as `100 lbs`, `Half lot`, `Full lot`, and `Last used`.

### Operations / audit

- As operations, I keep the same `ExtractionCharge` audit trail, lifecycle history, and `Floor Ops` continuity as before.

## Scope For This Sprint

### In scope

- new standalone route for `Scan / Enter Lot`
- camera barcode scanning in the standalone extraction app when the browser supports it
- manual tracking-ID fallback entry
- charge presets with default `100 lbs per reactor`
- post-charge action loop:
  - `Open run now`
  - `Back to reactors`
  - `Charge another lot`
- targeted frontend regression coverage for route parsing, presets, and lookup behavior

### Out of scope

- new backend entities
- full standalone run editing
- device-scale integration inside the standalone app
- Slack work
- broader post-extraction testing UI

## UX Surfaces

### 1. Scan / Enter Lot

Add a dedicated route:

- `#/scan`

It should support:

- browser camera scan when `BarcodeDetector` is available
- manual tracking-ID entry
- Bluetooth scanner keyboard-wedge entry through the same input

### 2. Charge presets

The charge form should expose:

- `100 lbs`
- `Half lot`
- `Full lot`
- `Last used`

Default behavior:

- the initial suggested charge should be `100 lbs` when the lot has at least `100 lbs` remaining
- otherwise use the remaining lot weight

### 3. Post-charge loop

After a charge is recorded, the operator should immediately see:

- `Open Run in Main App`
- `Back to Reactors`
- `Charge Another Lot`

### 4. Navigation polish

Make `Scan / Enter Lot` a first-class action from:

- sidebar
- home
- reactors
- lots

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

- route parsing includes `#/scan`
- charge preset helpers clamp `100 lbs` correctly
- mock/live standalone API lookup path works
- camera/manual scan helpers can route into a resolved lot

### Full-suite closeout before final commit

- standalone extraction app test suite
- full Python suite

## Definition Of Done

This sprint is done when:

- the standalone extraction app has a dedicated `Scan / Enter Lot` screen
- an operator can scan or manually enter a tracking ID and open the right lot
- the charge form defaults to `100 lbs` when possible
- preset buttons speed up charge entry
- the post-charge loop lets operators continue without backing through the app manually
- tests and docs are updated
