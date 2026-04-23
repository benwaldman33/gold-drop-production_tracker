# Gold Drop - Next Sprint Implementation Plan

The reactor-side extraction workflow is now live through charge creation, standalone run execution, and guided run progression. The next major product area starts **after extraction has already happened** and the run outputs exist.

This plan is now anchored to the `Extraction & Post-Processing Flowchart` provided on `2026-04-22`.

## Sprint Focus

Build `Post-Extraction Workflow Orchestration` on top of the existing extraction system.

The business sequence is now:

1. Buy
2. Receive
3. Inventory / lot tracking
4. Charge into reactor
5. Execute extraction run
6. Record initial outputs (`wet THCA`, `wet HTE`)
7. Route material through the correct post-extraction path
8. Record downstream holds, decisions, and queue placements

## Product Goal

Let operators and supervisors move material from the completed extraction run into the correct **THCA** and **HTE** downstream paths without relying on Slack messages, memory, or ad hoc notes.

The system should become the source of truth for:

- which post-extraction path a run took
- what timed holds happened
- what decisions were made
- whether material was held, reworked, or routed to a downstream queue

## Why This Is Next

The current system already covers the extraction-side workflow:

- lot charging
- active reactor board
- standalone extraction app
- guided run progression through completion
- settings-driven defaults for repeated extraction inputs

What is still missing is the workflow **after outputs are collected**:

- run-type branching after extraction
- post-processing timers and hold states
- explicit THCA and HTE path decisions
- downstream queue / hold / rework routing
- traceable disposition of extracted material

## Source Workflow To Implement

### Start condition

This workflow begins **after extraction run execution**, not before.

The source run already exists, and the system has or should have:

- reactor
- source lot(s)
- run metadata
- wet THCA output
- wet HTE output

### Run-type branch

After extraction, the operator must identify which run path applies:

1. `100 lb pot pour`
2. `200 lb minor run`

### Pot pour path

`100 lb pot pour` currently follows:

1. warm off-gas area
2. 10 days
3. stir daily once
4. move to post-processing lab
5. centrifuge process
6. outputs collected `THCA + HTE`
7. record final weights
8. end

### Minor run path

`200 lb minor run` currently follows:

1. initial outputs `THCA + HTE`
2. split into:
   - `THCA path`
   - `HTE path`

### THCA path

Current target flow:

1. THCA oven
2. 16 hours
3. mill THCA
4. product-path decision:
   - sell THCA
   - make LD
   - formulate in badders / sugars
5. decarb sample for LD clarity
6. upload picture
7. end

### HTE path

Current target flow:

1. landing zone
2. off-gas 48 hours
3. tested
4. clean decision:
   - if no: move to cage upstairs for terp stripping / CDTs
   - if yes: terp tube refinement
5. oil darker / thick / harder to filter decision:
   - if yes:
     - Prescott machine
     - testing
     - potency decision:
       - low -> held for HP base oil
       - high -> held to be made into distillate
   - if no:
     - clean HTE
     - menu ready path
     - terp profile standard for Liquid Loud decision:
       - yes -> hold ~2kg for Liquid Loud processing, then move to GoldDrop production queue
       - no -> move to GoldDrop production queue
6. end

## Gap Analysis Against Current System

### Already implemented

- extraction-side run execution
- guided progression through extraction completion
- wet output capture support on the run
- HTE pipeline concepts already exist in the data model and reporting surfaces
- department/reporting language already references parts of the HTE downstream path

### Missing

- explicit `run type` selection for the post-extraction branch
- post-extraction workflow screen(s)
- timed holds for:
  - 10-day warm off-gas
  - 48-hour off-gas
  - 16-hour THCA oven
- explicit branch tracking for:
  - THCA path
  - HTE path
- decision nodes captured as structured data instead of notes
- hold / rework / downstream queue states
- post-processing operator workflow surfaces
- final disposition tracking for:
  - sell THCA
  - make LD
  - formulate into badders / sugars
  - HP base oil hold
  - distillate hold
  - Liquid Loud hold
  - GoldDrop production queue

## Recommended Build Order

### Phase 1 - Post-extraction session foundation

Build a new post-extraction session layer linked to a completed run.

Scope:

- select `100 lb pot pour` vs `200 lb minor run`
- record initial outputs:
  - wet THCA
  - wet HTE
- create canonical post-extraction session records tied to the run

**Status:** shipped on the existing `Run` record.

Current implementation:
- `post_extraction_pathway`
- `post_extraction_started_at`
- `post_extraction_initial_outputs_recorded_at`
- touch-first `Start Post-Extraction` and `Confirm Initial Outputs` actions in the standalone extraction run screen
- matching visibility/editing on the main run form

What remains for later phases is the actual THCA-path / HTE-path branching and orchestration after this handoff.

### Phase 2 - THCA and HTE path state tracking

Add structured path/state models for downstream workflow.

Scope:

- THCA path states
- HTE path states
- timed holds
- explicit branch decisions
- same-day / current-state visibility in the app

**Status:** shipped on the existing `Run` record.

Current implementation:
- pot-pour warm off-gas start/end, stir count, and centrifuge timestamp
- THCA oven start/end, milling timestamp, and THCA destination
- HTE off-gas start/end, clean/dirty decision, filter outcome, Prescott timestamp, potency disposition, and queue destination
- matching fields on both the main run form and the standalone extraction run screen

What remains for later phases is the guided downstream operator workflow on top of these stored states.

### Phase 3 - Guided downstream operator screens

Add touch-first workflow screens similar to the standalone extraction approach.

Scope:

- guided post-extraction session screen
- touch-first branching for `100 lb pot pour` vs `200 lb minor run`
- numbered step cards and tap-first decision controls in the standalone extraction app

**Status:** shipped in the standalone extraction app.

Current implementation:
- pathway-first guided downstream workflow on `Open Run`
- numbered step cards for post-extraction handoff plus pot-pour / minor-run branches
- tap-first decision buttons for THCA destination and HTE downstream decisions
- main run form retained as the supervisor correction/edit surface

### Phase 4 - Queue and hold operational surfaces

Build working queue pages from the downstream destination data already stored on the run.

Scope:

- `Needs Queue Decision`
- `GoldDrop production queue`
- `Liquid Loud hold`
- `Terp strip / CDT cage`
- `HP base oil hold`
- `Distillate hold`
- direct move / complete actions without opening every run first

**Status:** shipped in the main app.

Current implementation:
- new `Downstream Queues` page in the sidebar
- queue grouping derived from `hte_queue_destination` and `hte_potency_disposition`
- unresolved minor-run outputs show up under `Needs Queue Decision`
- queue cards show run, source context, wet/dry outputs, THCA destination, HTE decision labels, and `Open Run`
- direct move actions update the existing run-level queue / hold fields and preserve audit history

### Phase 5 - Destination-specific queue workflow

Deepen one downstream destination into a real working queue instead of a generic bucket.

Scope:

- dedicated `GoldDrop Production Queue` page
- queue-state history per run
- explicit next-step actions after placement
- queue completion / release and send-back handling

**Status:** shipped for `GoldDrop production queue`.

Current implementation:
- dedicated `/downstream-queues/golddrop` page
- additive `DownstreamQueueEvent` table for queue action history
- queue actions:
  - `Mark Reviewed`
  - `Queue For Production`
  - `Release Complete`
  - `Send Back For Re-routing`
- queue notes and timestamped history shown on each card

Phase 5 is now also shipped for:
- `Liquid Loud Hold`
- `Terp Strip / CDT Cage`
- `HP Base Oil Hold`

Current implementation for those additional destinations:
- each has its own dedicated queue page opened from `Downstream Queues`
- each page shows queue history via `DownstreamQueueEvent`
- each page exposes destination-specific next-step actions instead of only the generic move dropdown
- `Liquid Loud Hold` can release directly into `GoldDrop Production Queue`
- `Terp Strip / CDT Cage` can mark Prescott handling and strip completion
- `HP Base Oil Hold` can confirm or release the low-potency hold

What remains for later phases is repeating this pattern for the remaining downstream destinations and then layering role-specific views on top.
- top-to-bottom operator sequence
- minimal keyboard entry
- timers and decision buttons

**Status:** shipped inside the standalone extraction run screen.

Current implementation:
- numbered downstream workflow steps
- pathway-driven sequence on the tablet
- branch-specific pot-pour vs minor-run step blocks
- tap-first choice buttons for pathway and downstream decisions

What remains for later phases is a fuller downstream queue / hold surface and role-specific views beyond the extraction tablet.

### Phase 4 - Queue and hold destinations

Turn final path decisions into operational queue states.

Scope:

- GoldDrop production queue
- Liquid Loud hold
- HP base oil hold
- distillate hold
- terp stripping / cage hold

### Phase 5 - Reporting / department alignment

Align the existing department and reporting surfaces with the new structured data.

Scope:

- testing page
- HTE / terp / distillation views
- post-processing summary views
- better current-state and disposition visibility

## User Stories

### Extractor / post-processing operator

- As an operator, I can record whether a completed run is a pot pour or minor run.
- As an operator, I can move THCA and HTE through their downstream paths without relying on Slack notes.
- As an operator, I can start and stop the required hold/timer steps with one tap.
- As an operator, I can record downstream decisions as structured actions instead of free-text only.

### Supervisor

- As a supervisor, I can see exactly where each run's outputs are in post-processing.
- As a supervisor, I can see whether material is held, queued, clean, dirty, stripped, or routed elsewhere.
- As a supervisor, I can review the downstream decision history with timestamps.

### Operations / reporting

- As operations, I can report THCA and HTE post-processing paths from system data instead of reconstructing them from Slack.
- As operations, I can separate extraction execution from post-extraction disposition while preserving traceability.

## UX Direction

The likely operator surface should mirror the reactor-centered idea already discussed for extraction:

- one guided workflow screen per post-extraction session or output path
- top-to-bottom flow
- large tap targets
- timers for hold steps
- structured decision buttons for branch points

This should be designed only after the team confirms the exact real-world workflow sequence.

## Immediate Next Session

Do not build the downstream UI yet.

First:

1. confirm the real operator workflow with the team
2. validate which steps are required vs optional
3. validate which decisions must be structured
4. confirm whether THCA and HTE should be managed as one shared screen or two linked workflow screens

After that, the first implementation slice should be:

`Phase 1 - Post-extraction session foundation`

## Definition Of Done For Planning

This planning pass is complete when:

- the system boundary is clear:
  - extraction workflow ends at run completion / initial outputs
  - post-extraction workflow begins after that
- the target downstream paths are documented
- the build order is defined
- future implementation can start without re-litigating where extraction ends and post-processing begins
