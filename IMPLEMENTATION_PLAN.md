# Gold Drop - Next Sprint Implementation Plan

The standalone extraction lab app now covers charge creation and scan-first lot entry. The next sprint should carry extractors through the actual run without forcing them back into the admin form.

## Sprint Focus

Build `Standalone Extraction Run Execution` on top of the existing extraction charge workflow and standalone extraction app.

The business sequence remains:

1. Buy
2. Receive
3. Find or scan the lot
4. Charge into reactor / start extraction
5. Record run execution details
6. Complete / cancel / review

Testing can still happen before buy, after receipt, or after extraction depending on supplier trust and process stage.

## Product Goal

Let extractors and assistant extractors stay inside the standalone extraction app after charge creation, capture the same execution details they currently type into Slack, and use touch-first timers instead of keyboard-heavy timestamp entry.

## Why This Is Next

The repo already has:

- a deployed standalone extraction app
- charge-first and scan-first entry
- a reactor board with lifecycle transitions
- canonical `ExtractionCharge` persistence
- a main-app run form with lot allocations and downstream analytics

What is still missing is the extractor’s actual execution loop:

- open a run directly from the charge
- record fill / flush / mixer timing
- capture blend and hardware counts
- preserve inherited reactor / source / biomass data without re-entry

## User Stories

### Extractor

- As an extractor, I can open a run directly from a charged reactor in the standalone app.
- As an extractor, I can use `Start`, `Stop`, and `Now` style controls for timing fields instead of typing timestamps.
- As an extractor, I can record fill, flush, CRC, and stringer-basket details in the same workflow where I already charge the lot.

### Assistant extractor

- As an assistant extractor, I can see which values came from the charge step and which ones I still need to record.
- As an assistant extractor, I can save execution details on an iPad with large controls and minimal keyboard use.

### Operations / audit

- As operations, I keep the same canonical lot allocation and charge-to-run linkage as before.
- As operations, the extracted run metadata is structured, queryable, and editable later from the main app.

## Scope For This Sprint

### In scope

- structured extraction run-execution fields on `Run`
- schema bootstrap support for SQLite and PostgreSQL
- mobile extraction endpoints to fetch and save a charge-linked standalone run
- standalone run-execution screen inside `standalone-extraction-lab-app`
- touch-first timer controls for:
  - run / fill time
  - mixer time
  - flush start / end
- inherited charge context on the run screen:
  - reactor
  - source
  - strain
  - biomass weight
- first-pass structured fields for:
  - biomass blend `% milled / % unmilled`
  - number and weight of flushes
  - number and weight of fills
  - number of stringer baskets
  - CRC blend
  - notes
- targeted regression coverage for extraction run API + standalone route handling

### Out of scope

- per-fill or per-flush child tables
- full standalone yield-output editing
- Slack parser expansion for the new run fields
- scale capture directly inside the standalone run screen

## Field Mapping

### Inherited from charge / source lot

- `Reactor`
- `Strain`
- `Source`
- `Biomass Weight`
- charge timestamp as the initial execution context

### Captured in the standalone run workflow

- `Run / Fill Start Time`
- `Biomass Blend (% milled / % unmilled)`
- `Number and Weight of Flushes`
- `Number and Weight of Fills`
- `Number of Stringer Baskets`
- `CRC Blend`
- `Mixer Time`
- `Flush Start Time`
- `Flush End Time`
- `Notes`

## UX Surfaces

### 1. Run screen

Add a dedicated standalone route:

- `#/runs/charge/<charge_id>`

That screen should:

- show inherited charge / lot context at the top
- show touch-first time controls
- let operators save structured execution details without leaving the app
- still offer `Open in Main App` as a secondary path

### 2. Touch-first timers

The standalone run screen should prefer buttons over manual datetime typing:

- `Start / Now`
- `Stop / Now`

This applies first to:

- run / fill timing
- mixer timing
- flush timing

### 3. Counter-style controls

For count fields, prefer quick `- / +` adjustments over typing:

- flush count
- fill count
- stringer basket count

### 4. Blend control

Use a single slider for `% milled`, with `% unmilled` automatically derived to total `100`.

## Backend Changes

### Run fields

Add structured execution fields to `Run`, including datetime, numeric, and text fields needed for the extractor workflow.

### Extraction mobile API

Add a charge-linked run endpoint:

- `GET /api/mobile/v1/extraction/charges/<charge_id>/run`
- `POST /api/mobile/v1/extraction/charges/<charge_id>/run`

Behavior:

- `GET` returns either the linked run or a draft payload built from the charge without allocating inventory yet
- `POST` creates the linked run on first save, applies the existing lot allocation, and stores the execution fields

## Test Plan

### Targeted tests during implementation

- mobile extraction run endpoint returns draft payloads and saved structured fields
- charge-to-run linkage does not allocate inventory on `GET`
- standalone route parsing includes `#/runs/charge/<charge_id>`
- mock/live standalone API run methods unwrap correctly

### Full-suite closeout before final commit

- standalone extraction app test suite
- full Python suite

## Definition Of Done

This sprint is done when:

- a charge can open a standalone run-execution screen
- extractors can save structured execution fields without leaving the standalone app
- timer buttons capture the relevant timestamps
- inherited charge data is shown and not re-entered manually
- the main app can still open and edit the saved run with the new fields
- tests and docs are updated
