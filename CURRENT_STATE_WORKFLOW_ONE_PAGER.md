# Gold Drop - Current State Workflow One-Pager

This is the short-form version of the current shipped workflow from initial biomass opportunity through extraction result reporting.

## Workflow Summary

### 1. Buyer identifies biomass opportunity

- Entry points:
  - `Biomass Purchasing`
  - `Purchases`
  - standalone buyer app
- Record type:
  - same underlying `Purchase` record used from early intake through receiving
- Typical data captured:
  - supplier / farm
  - strain
  - expected or declared weight
  - expected price
  - availability date
  - testing notes
  - photos / notes

### 2. Purchase is reviewed and committed

- Main working surfaces:
  - `Biomass Pipeline`
  - `Purchases`
- Typical lifecycle:
  - `declared`
  - `in_testing`
  - `committed`
  - `delivered`
- Key control:
  - purchase approval gate before biomass can be treated as approved on-hand inventory

### 3. Receiving confirms delivery

- Main working surfaces:
  - standalone receiving app
  - `Purchases -> Edit Purchase`
- Receiving captures:
  - actual delivered weight
  - delivery date
  - testing state
  - notes
  - location / floor state
  - lot notes
  - delivery photos
- Important rule:
  - receiving remains editable until one of the lots is used downstream in a run

### 4. Lots become on-hand inventory

- Main working surfaces:
  - `Inventory`
  - `Purchases -> Edit Purchase`
  - `Batch Journey`
- Current lot actions:
  - `Edit`
  - `Charge`
  - `Scan`
  - `Label`
  - `Journey`
  - `Split Existing Lot` from purchase edit
- Current lot data includes:
  - strain
  - supplier
  - remaining lbs
  - potency
  - location
  - prep / floor state
  - tracking ID

### 5. Extractor charges biomass into a reactor

- Main working surfaces:
  - `Inventory -> Charge`
  - `Purchases -> Edit -> Charge Lot`
  - scan workflow
  - standalone extraction app
- Current charge record:
  - canonical `ExtractionCharge`
- Charge fields:
  - source lot
  - charged lbs
  - reactor
  - charge time
  - notes
  - source mode

### 6. Reactor lifecycle is managed

- Main working surfaces:
  - `Floor Ops`
  - standalone extraction `Reactors`
- Current states:
  - `pending`
  - `in_reactor`
  - `running`
  - `completed`
  - `cancelled`
- Current actions:
  - `Mark In Reactor`
  - `Mark Running`
  - `Mark Complete`
  - `Cancel Charge`
  - `Open Run`

### 7. Extractor opens the linked run

- Main working surfaces:
  - standalone extraction run screen
  - main run form when needed
- Inherited context:
  - reactor
  - source lot
  - strain
  - supplier/source context
  - biomass weight

### 8. Extractor records run execution details

- Current standalone run fields include:
  - run / fill timing
  - biomass blend `% milled / % unmilled`
  - number and weight of fills
  - number and weight of flushes
  - stringer basket count
  - CRC blend
  - notes
- Current defaulting:
  - extraction run defaults from Settings prepopulate repeated values

### 9. Extractor advances the run through guided progression

- Current guided actions:
  - `Start Run`
  - `Start Mixer`
  - `Stop Mixer`
  - `Start Flush`
  - `Stop Flush`
  - `Mark Run Complete`
- Current behavior:
  - writes timestamps automatically
  - shows current stage on the standalone run screen
  - stores `run_completed_at`
  - can also complete the linked charge

### 10. Extraction results are reported

- Main working surfaces:
  - standalone run screen
  - `Runs`
  - main run form
- Current output endpoint for this review:
  - wet THCA weight recorded on the run
  - wet HTE weight recorded on the run

## Current State Strengths

- one purchase record from opportunity through receiving
- approval gate before true on-hand use
- lot-level traceability with tracking IDs
- canonical extraction charge before run finalization
- reactor board and lifecycle history
- touch-first extraction workflow on iPad
- guided run progression on the tablet

## Main Current Friction

- the extractor workflow is still spread across multiple screens rather than one continuous reactor-centered process

## Likely Next Design Direction

- define a reactor-centered guided operator workflow
- make one reactor screen the primary operator surface
- keep the current screens as underlying system/fallback/admin paths
