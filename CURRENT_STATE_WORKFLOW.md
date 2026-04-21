# Gold Drop - Current State Workflow

This document describes the current shipped workflow from the moment a purchaser identifies a potential biomass lot through the point where extraction results are recorded as wet THCA and wet HTE output.

It is intended as a meeting reference for workflow review and future design decisions.

## Purpose

Use this document to answer:

- what the system supports today
- which screens or apps are used at each stage
- what information is captured at each step
- where approvals or handoffs happen
- where the current workflow is still screen-driven rather than operator-guided

## High-Level Flow

1. Purchaser identifies a potential lot of biomass
2. Opportunity / purchase record is created
3. Purchase is reviewed and moved through pipeline states
4. Purchase is approved / committed
5. Receiving confirms delivered biomass and creates on-hand lots
6. Lots are managed in Inventory / Purchases
7. Extractor chooses or scans a lot and records an extraction charge
8. Run is opened and linked to the charged lot
9. Extractor records run execution details
10. Run progression is advanced through execution
11. Wet THCA and wet HTE outputs are recorded on the run

## Stage 1 - Purchasing opportunity identified

### Trigger

A buyer or office user identifies a potential biomass lot from a farm or supplier.

### Current entry points

- Main app:
  - `Biomass Purchasing`
  - `Purchases`
  - `Biomass Pipeline`
- Standalone buyer app:
  - standalone purchasing workflow on phone/tablet

### Current record model

The system uses the same underlying `Purchase` object for:

- early opportunity intake
- biomass pipeline review
- committed purchase record
- receiving / delivered record

This means there is not a separate long-lived "opportunity" table in the operator workflow. It is one record moving through states.

### Data typically captured

- supplier / farm
- strain
- declared or expected biomass weight
- expected or offered price
- availability date
- testing notes
- notes
- photos when applicable

### Important current behavior

- iPad/mobile opportunity edits now round-trip to the same main purchase fields
- supplier duplicate warnings exist in both the standalone buyer flow and main supplier creation flow
- testing may happen before buy, after buy, after receipt, or after extraction depending on supplier trust and process stage

## Stage 2 - Purchase / pipeline review

### Main working surface

- `Biomass Pipeline`
- `Purchases`

### Current lifecycle concept

The same purchase record typically moves through statuses such as:

- `declared`
- `in_testing`
- `committed`
- `delivered`
- later inventory / processing related states

### What users do here

- review buyer-entered opportunity details
- edit commercial / operational details
- approve or commit the purchase when appropriate
- review photos and testing context

### Important rules

- on-hand inventory and downstream lot use require purchase approval
- the system enforces a purchase approval gate before lots can be treated as approved on-hand biomass

## Stage 3 - Receiving and intake

### Trigger

Committed or approved biomass physically arrives at the facility.

### Current entry points

- Standalone receiving app:
  - queue-based receiving flow for dock / intake staff
- Main app:
  - `Purchases -> Edit Purchase`

### What receiving records

- actual delivered weight
- delivery date
- testing state
- receiving notes
- location
- floor state
- lot notes
- delivery photos

### Current behavior

- receiving works on the existing purchase record rather than creating a separate receiving object
- confirming receipt updates the purchase to `delivered`
- the receiving app can later use `Edit Receipt` until downstream lot usage begins
- once a lot from that purchase is consumed by a run, receiving becomes locked and read-only

## Stage 4 - Lot creation and on-hand inventory

### Trigger

Received biomass becomes active on-hand inventory.

### Main working surfaces

- `Inventory`
- `Purchases -> Edit Purchase`
- `Batch Journey`

### What exists now

The system maintains explicit lots tied to the purchase, including:

- strain
- supplier
- original weight
- remaining weight
- potency when known
- location
- prep state
- floor state
- notes
- machine-readable tracking ID

### Lot management actions currently available

From `Inventory -> Biomass On Hand`:

- `Edit`
- `Charge`
- `Scan`
- `Label`
- `Journey`

From `Purchases -> Edit Purchase`:

- `Charge Lot`
- `Split Existing Lot`

### Important current behavior

- lot labels include barcode and QR code
- lots can be split after purchase confirmation using `Split Existing Lot`
- tracking IDs and labels support scan-based floor execution

## Stage 5 - Extractor selects biomass for production

### Trigger

An extractor is ready to put all or part of a lot into a reactor.

### Current entry points

- Main app:
  - `Inventory -> Charge`
  - `Purchases -> Edit -> Charge Lot`
  - scanned lot page via `/scan/lot/<tracking_id>`
  - `Floor Ops`
- Standalone extraction app:
  - `/extraction-lab/`
  - `Scan / Enter Lot`
  - `Lots`
  - `Reactors`

### Current charge workflow

The system creates a canonical `ExtractionCharge` event before the run is finalized.

Charge fields include:

- source lot
- charged lbs
- reactor
- charge time
- notes
- source mode

### Important current behavior

- charge can be started from scan flow, desktop flow, or standalone extraction app
- charge is now a first-class record, not just a prefilled run draft
- once created, the charge appears in main-app `Floor Ops`

## Stage 6 - Reactor queue and lifecycle

### Main working surface

- `Floor Ops`
- standalone extraction app `Reactors`

### Current shared reactor lifecycle

Charges can move through:

- `pending`
- `in_reactor`
- `running`
- `completed`
- `cancelled`

### Current actions

- `Mark In Reactor`
- `Mark Running`
- `Mark Complete`
- `Cancel Charge`
- `Open Run`

### Current supporting views

Main app `Floor Ops` includes:

- `Active Reactor Board`
- `Reactor Charge Queue`
- `Reactor History Today`
- `Recently Applied Charges`

Standalone extraction app includes:

- `Reactors`
- board filters
- linked `Open Run` action as a large primary button

### Important current behavior

- lifecycle state changes are audited with timestamps
- `Mark Running` can require a linked run depending on settings
- completed/cancelled charges remain visible for the rest of the day

## Stage 7 - Run creation and linkage

### Trigger

After a charge is created, the extractor or supervisor opens the linked run.

### Current entry points

- `Open Run` from standalone extraction app
- `Open Run in Main App`
- `Open Run` from `Floor Ops`
- `New Run` opened automatically after charge in some flows

### Current linkage behavior

The run is linked to the existing `ExtractionCharge`, and lot allocation is carried forward from the charge context.

### Current inherited context

The run screen already knows:

- reactor
- source lot
- strain
- source/supplier context
- biomass weight context

## Stage 8 - Run execution capture

### Main entry point for extractors

- standalone extraction app run screen

### Current structured fields captured

- run / fill timing
- biomass blend `% milled / % unmilled`
- number and weight of fills
- number and weight of flushes
- number of stringer baskets
- CRC blend
- notes

### Current defaults

`Settings -> Operational Parameters -> Extraction run defaults` can prepopulate:

- default milled %
- fill count
- total fill weight
- flush count
- total flush weight
- stringer basket count
- CRC blend

### Current interaction model

- touch-first controls
- sliders
- `- / +` nudges
- timer buttons instead of keyboard-heavy timestamp entry

## Stage 9 - Guided run progression

### Current progression model

The standalone run screen now supports guided progression through:

- `Start Run`
- `Start Mixer`
- `Stop Mixer`
- `Start Flush`
- `Stop Flush`
- `Mark Run Complete`

### Current behavior

- each action writes the matching time fields
- the screen shows the current stage and next action
- a completed timestamp is stored on the run
- when appropriate, completing the run also completes the linked charge

## Stage 10 - Extraction results recorded

### Main working surface

- `Runs`
- standalone extraction app run screen
- main run form for supervisor review/editing

### Current expected extraction result fields

At minimum, the system supports recording extraction outputs on the run including:

- wet THCA weight
- wet HTE weight

The run model and reporting surfaces are built around THCA / HTE outputs, with later dry and downstream post-processing fields available elsewhere in the run workflow.

### Current endpoint of this document

For this workflow review, the process ends when:

- biomass has been charged into a reactor
- a linked run exists
- the extractor has progressed the run through execution
- wet THCA and wet HTE results are recorded on the run

## Current State Summary

Today’s workflow is operationally complete from:

- buyer opportunity intake
- through receiving
- through inventory/lot creation
- through extraction charge
- through run execution
- through extraction result recording

## Current State Strengths

- one shared purchase record from early opportunity through receiving
- explicit approved / on-hand gating
- real lot tracking with machine-readable IDs
- canonical extraction charge event before final run save
- shared main-app and standalone extraction surfaces
- structured reactor lifecycle with audit history
- touch-first iPad extraction workflow
- guided run progression on the tablet

## Current State Friction Points

These are not failures, but they are the main remaining workflow issues:

1. the extractor workflow is still somewhat screen-driven rather than one continuous reactor-centered process
2. some settings and admin surfaces remain dense and technical
3. Slack integration is currently deferred pending Slack-side review
4. import/mapping workflows are still inconsistent across modules

## Likely Next Design Conversation

The next major workflow design topic is the proposed reactor-centered guided operator screen.

That discussion should answer:

- what the exact per-reactor step order should be
- which steps are required vs optional
- what defaults belong in each step
- what should be visible all at once vs progressively revealed
- what the end-of-run closeout should look like before downstream processing
