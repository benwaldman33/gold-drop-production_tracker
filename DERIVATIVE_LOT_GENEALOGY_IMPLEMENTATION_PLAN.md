# Derivative Lot Genealogy Implementation Plan

## Goal

Implement true end-to-end lot genealogy in a way that is:

- additive to the current app
- safe for production rollout
- useful for managers early, before every downstream workflow is converted

This plan assumes the target design in [DERIVATIVE_LOT_GENEALOGY_PLAN.md](D:\OneDrive - Envista\Desktop\gold-drop-app\gold-drop-production_tracker\DERIVATIVE_LOT_GENEALOGY_PLAN.md:1).

## Implementation Principles

1. Do not break current production workflows.
2. Keep `PurchaseLot`, `Run`, `RunInput`, and current downstream queues as valid operational surfaces during rollout.
3. Introduce genealogy as a parallel source of truth first, then deepen workflow coupling later.
4. Add reconciliation early so bad genealogy data is visible immediately.
5. Prefer dry-output accountable lots first unless a real wet-stage need forces earlier expansion.

## Phase 1: Schema Foundation

### Deliverables

- add `MaterialLot`
- add `MaterialTransformation`
- add `MaterialTransformationInput`
- add `MaterialTransformationOutput`
- add `MaterialReconciliationIssue`

### Required fields

At minimum:

- `MaterialLot`
  - `id`
  - `tracking_id`
  - `lot_type`
  - `quantity`
  - `unit`
  - `inventory_status`
  - `workflow_status`
  - `source_purchase_lot_id`
  - `parent_run_id`
  - `origin_confidence`
  - `cost_basis_total`
  - `cost_basis_per_unit`
  - timestamps
- `MaterialTransformation`
  - `id`
  - `transformation_type`
  - `run_id`
  - `source_record_type`
  - `source_record_id`
  - `status`
  - `performed_at`
  - timestamps
- input/output link tables
  - foreign keys
  - quantity + unit
- reconciliation issues
  - issue type
  - severity
  - target references
  - status
  - resolution fields

### Notes

- use additive migrations only
- do not remove or repurpose existing columns
- write indexes for `tracking_id`, `lot_type`, `parent_run_id`, and transformation foreign keys up front

### Verification

- model tests
- migration/bootstrap tests
- idempotent schema init

## Phase 2: Biomass Bridge

### Goal

Bridge every active `PurchaseLot` into the new genealogy model.

### Deliverables

- add nullable `PurchaseLot.material_lot_id`
- backfill one `MaterialLot(type=biomass)` per active `PurchaseLot`
- preserve source `tracking_id`
- snapshot source supplier / strain
- set `origin_confidence = backfilled`

### Rules

- one active `PurchaseLot` maps to exactly one biomass `MaterialLot`
- backfill must be idempotent
- archived lots may be included later, but active lots come first

### Verification

- every active `PurchaseLot` has a linked biomass `MaterialLot`
- no duplicate biomass `MaterialLot` rows for the same `PurchaseLot`
- quantities match `PurchaseLot.weight_lbs` / `remaining_weight_lbs`

## Phase 3: Run Source Resolution Helpers

### Goal

Make genealogy usable internally before new UI is added.

### Deliverables

- helper to resolve biomass `MaterialLot` from `PurchaseLot`
- helper to resolve source biomass material lots for a `Run`
- helper to summarize source ancestry for reporting

### Usage targets

- journey payload builders
- reporting queries
- future downstream lot creation

### Verification

- unit tests for single-lot runs
- unit tests for multi-lot aggregate runs
- unit tests for partial-consumption source lots

## Phase 4: Extraction Output Lot Creation

### Goal

Create the first accountable derivative lots automatically from extraction runs.

### Deliverables

- create one `MaterialTransformation(type=extraction)` per eligible run
- create `dry_hte` lot when `dry_hte_g` is first recorded
- create `dry_thca` lot when `dry_thca_g` is first recorded
- create transformation inputs from biomass `MaterialLot` records linked through `RunInput`
- create transformation outputs for the derivative lots
- initialize cost basis from run-level cost where available

### Rules

- only create output lots once per accountable output
- updates should modify the existing derivative lot record rather than create duplicates
- if a run has no source allocations, create a reconciliation issue instead of inventing lineage

### Verification

- single-source run creates expected outputs
- multi-source run creates one extraction transformation with many inputs
- repeated save does not duplicate output lots
- missing-source run raises reconciliation issue

## Phase 5: Read Surfaces

### Goal

Expose genealogy to managers before changing downstream operations.

### Deliverables

- derivative lot detail endpoint
- derivative lot journey endpoint
- ancestry endpoint
- descendants endpoint
- enhancements to existing purchase / lot / run journeys to include derivative lots

Suggested endpoints:

- `/api/v1/material-lots/<lot_id>`
- `/api/v1/material-lots/<lot_id>/journey`
- `/api/v1/material-lots/<lot_id>/ancestry`
- `/api/v1/material-lots/<lot_id>/descendants`

### UI target

Use the merged `lot-journey-v2` direction as the transitional UI:

- `By Lot`
- `By Run`
- upstream trunk history
- run cards
- derivative descendant cards
- run genealogy section

### Verification

- managers can trace:
  - source lot -> runs -> derivative lots
  - run -> source lots -> derivative lots
  - derivative lot -> ancestry

## Phase 6: Reconciliation And Error Detection

### Goal

Catch bad genealogy and bad quantity state early.

### Deliverables

- reconciliation checks for:
  - negative balances
  - missing source links
  - orphan outputs
  - impossible closed/open combinations
  - missing cost basis on cost-bearing lots
- create `MaterialReconciliationIssue` rows
- basic manager read surface for unresolved issues

### Recommended first checks

1. output lot exists but no transformation input rows
2. transformation input quantity exceeds source lot available quantity
3. parent lot fully consumed but still marked open
4. run has derivative lots but no `RunInput`

### Verification

- automated tests for each issue type
- visible unresolved issue list

## Phase 7: Correction Workflows

### Goal

Make genealogy correctable without silent data loss.

### Deliverables

- admin or manager correction actions
- correction-backed transformations for:
  - wrong parent link
  - quantity adjustment
  - mistaken derivative lot creation
- correction audit logging

### Rules

- no silent genealogy rewrites
- prefer corrective transformations or explicit close-and-replace flows
- require note / reason for correction

### Verification

- correction leaves a visible trail
- ancestry / descendants still resolve after correction

## Phase 8: Cost Roll-Forward

### Goal

Carry cost with material instead of leaving genealogy and cost disconnected.

### Deliverables

- initialize extraction output lot cost from parent run
- split cost by quantity for split transformations
- sum input cost into blended lots
- expose cost basis on derivative lot detail and reporting

### Verification

- source lot cost -> run cost -> derivative lot cost remains internally consistent
- split and blend tests pass

## Phase 9: Downstream Queue Linking

### Goal

Connect the existing queue system to genealogy without forcing a full rewrite.

### Deliverables

- allow queue items to reference linked derivative lots
- show derivative lot tracking ID and lot type on queue cards
- show ancestry / descendants drill links on queue cards

### Important constraint

- keep current queue actions attached to `Run` at first
- do not move destination workflow ownership to `MaterialLot` yet

### Verification

- queue pages still function
- managers can open derivative lot lineage from queue surfaces

## Phase 10: Destination-Native Transformations

### Goal

Make downstream genealogy truly end-to-end.

### Deliverables

- GoldDrop transformation support
- THCa split support
- terp strip transformation support
- HP base oil conversion support
- distillate conversion support

### Example

- input `dry_hte` lot
- `MaterialTransformation(type=golddrop_production)`
- output `golddrop` lot

### Verification

- descendant chains now extend beyond extraction output lots
- management can answer source-to-finished-product questions

## Phase 11: Reporting Layer

### Goal

Turn genealogy into operational visibility.

### Deliverables

- lot ancestry report
- lot descendants report
- open derivative inventory by type
- released derivative inventory by type
- source-to-derivative yield report
- rework volume report
- reconciliation issue dashboard
- cost basis by open and released derivative lot

## Rollout Order Recommendation

Implement in this order:

1. schema foundation
2. biomass bridge
3. run source helpers
4. extraction output lot creation
5. read surfaces
6. reconciliation
7. correction workflows
8. cost roll-forward
9. queue linking
10. destination-native downstream transformations
11. reporting

## Minimal First Sprint

If you want the smallest safe coding start, do only:

1. schema foundation
2. biomass bridge
3. run source resolution helpers
4. first reconciliation checks

That gives you safe infrastructure without changing operator behavior yet.

## First Full Milestone

The first milestone where managers gain real new value is:

- biomass bridge complete
- extraction output lots auto-created
- read surfaces show derivative descendants

At that point the app will still be operationally run-centric, but managers will already gain true forward traceability from biomass to accountable extraction outputs.

## Deferred Until Later

These should not block the first genealogy rollout:

- fully lot-native downstream workflows
- packaged-goods lot modeling
- advanced wet-stage lot modeling
- repeated reminder escalation tied to genealogy issues

## Recommended Next Coding Sprint

Start with:

`Phase 1 + Phase 2 + Phase 3`

That is the right first coding sprint because it builds the durable foundation, keeps production risk low, and gives you the substrate required for everything else.
