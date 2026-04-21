# Gold Drop - Current State Workflow Swimlane

This version organizes the current shipped workflow by role so teams can review handoffs and responsibilities more easily.

## Roles

- Buyer
- Approver / Operations Lead
- Receiver / Intake
- Extractor / Assistant Extractor
- Supervisor / Admin

## Swimlane Workflow

### 1. Biomass opportunity identified

**Buyer**
- identifies a potential biomass lot
- creates or edits the opportunity / purchase record
- captures:
  - supplier / farm
  - strain
  - expected weight
  - expected price
  - availability date
  - testing notes
  - notes
  - photos when relevant

**Approver / Operations Lead**
- can review the same record in:
  - `Biomass Pipeline`
  - `Purchases`

**Current system note**
- this is the same underlying `Purchase` record used all the way through receiving

### 2. Review, testing context, and commitment

**Buyer**
- may refine details based on supplier communication
- may add updated opportunity or testing information

**Approver / Operations Lead**
- reviews pricing, notes, testing context, and readiness
- moves the record through early pipeline states such as:
  - `declared`
  - `in_testing`
  - `committed`
- handles approval / commitment decisions

**Current system rule**
- purchase approval is required before biomass can become approved on-hand inventory used downstream

### 3. Biomass received

**Receiver / Intake**
- opens the standalone receiving app or purchase review screen
- confirms receipt
- records:
  - actual delivered weight
  - delivery date
  - testing state
  - notes
  - location
  - floor state
  - lot notes
  - delivery photos

**Approver / Operations Lead**
- can review receiving details back on the purchase record

**Current system rule**
- receipt can be edited until downstream lot usage starts in a run

### 4. Lots created and managed

**Receiver / Intake**
- ensures delivered biomass becomes usable lot inventory

**Supervisor / Admin**
- can review and manage lots from:
  - `Inventory`
  - `Purchases -> Edit Purchase`
  - `Batch Journey`

**Available current lot actions**
- `Edit`
- `Charge`
- `Scan`
- `Label`
- `Journey`
- `Split Existing Lot` on purchase edit

### 5. Extractor selects biomass for production

**Extractor / Assistant Extractor**
- finds the lot by:
  - scanning a label
  - using `Inventory -> Charge`
  - using `Purchases -> Edit -> Charge Lot`
  - using the standalone extraction app
- records an extraction charge

**Current charge captures**
- source lot
- charged lbs
- reactor
- charge time
- notes

**Current system note**
- the system stores a canonical `ExtractionCharge` before the run is finalized

### 6. Reactor queue and lifecycle

**Extractor / Assistant Extractor**
- sees current work on:
  - standalone extraction `Reactors`
  - main app `Floor Ops`
- can act on reactor lifecycle using:
  - `Mark In Reactor`
  - `Mark Running`
  - `Mark Complete`
  - `Cancel Charge`
  - `Open Run`

**Supervisor / Admin**
- can monitor the same lifecycle in `Floor Ops`
- can review:
  - `Active Reactor Board`
  - `Reactor Charge Queue`
  - `Reactor History Today`
  - `Recently Applied Charges`

### 7. Linked run opened

**Extractor / Assistant Extractor**
- opens the linked run after charge
- usually from the standalone extraction app

**Current inherited context**
- reactor
- source lot
- strain
- supplier/source context
- biomass weight

**Supervisor / Admin**
- can still open the same run in the main app for deeper editing or review

### 8. Run execution details captured

**Extractor / Assistant Extractor**
- records execution details on the standalone run screen
- uses touch-first controls rather than keyboard-heavy entry

**Current captured fields**
- run / fill timing
- biomass blend `% milled / % unmilled`
- number and weight of fills
- number and weight of flushes
- stringer basket count
- CRC blend
- notes

**Current defaults**
- values can be prepopulated from `Settings -> Operational Parameters -> Extraction run defaults`

### 9. Run progression advanced

**Extractor / Assistant Extractor**
- advances the run through the current guided progression:
  - `Start Run`
  - `Start Mixer`
  - `Stop Mixer`
  - `Start Flush`
  - `Stop Flush`
  - `Mark Run Complete`

**Current system behavior**
- timestamps are written automatically
- current stage is shown on the standalone run screen
- `run_completed_at` is stored
- linked charge can be completed as part of this flow

### 10. Extraction results reported

**Extractor / Assistant Extractor**
- records extraction results on the run

**Supervisor / Admin**
- reviews final run record in:
  - standalone run screen when needed
  - `Runs`
  - main run form

**Current endpoint for this review**
- wet THCA weight is recorded
- wet HTE weight is recorded

## Current Handoff Summary

### Buyer -> Approver / Operations Lead

- early commercial and sourcing context
- supplier, strain, expected biomass, testing context

### Approver / Operations Lead -> Receiver / Intake

- committed / approved purchase ready for receipt

### Receiver / Intake -> Extractor

- delivered biomass converted into on-hand tracked lots
- location, floor state, testing state, and receiving notes carried forward

### Extractor -> Supervisor / Admin

- charged biomass linked to reactor
- run execution data
- progression timestamps
- wet THCA / wet HTE reported on the run

## Current Strengths

- one shared purchase record from intake through receiving
- lot-level traceability
- reactor-centered visibility in `Floor Ops`
- dedicated extraction charge record
- standalone extraction app for floor use
- guided run progression already exists

## Main Current Friction

- extractor work is still split across multiple screens instead of one continuous guided reactor workflow

## Likely Next Design Direction

- define the exact per-reactor workflow with the team
- then design a reactor-centered guided screen that lets the extractor move top-to-bottom through the process without screen hopping
