# Derivative Lot Genealogy Plan

## Goal

Extend the app from strong upstream biomass traceability to true end-to-end material genealogy.

Today the system can reliably answer:

- which `PurchaseLot` records fed a given `Run`
- which `Run` records consumed a given `PurchaseLot`
- what downstream queue / state a run output reached

Today the system cannot reliably answer:

- which separately tracked HTE, THCA, GoldDrop, distillate, or other derivative lots came from a source biomass lot
- which upstream biomass lots contributed to a finished derivative lot when that derivative lot is treated as its own inventory object

This plan adds that missing layer without replacing the current `PurchaseLot`, `Run`, `RunInput`, or downstream queue model.

## Current State

Current lineage source of truth:

- `Purchase` -> source batch
- `PurchaseLot` -> source inventory lot
- `RunInput` -> source lot allocation into a run
- `Run` -> extraction event and output summary

Current audit / workflow history:

- `AuditLog`
- `LotScanEvent`
- `ExtractionCharge`
- `ExtractionBoothSession` / `ExtractionBoothEvent` / `ExtractionBoothEvidence`
- `DownstreamQueueEvent`
- `SupervisorNotification`

Current limitation:

- downstream material is mostly represented as fields and queue state on `Run`
- there is no first-class derivative inventory lot for HTE, THCA, GoldDrop, Liquid Loud, terp strip outputs, HP base oil, distillate, or packaged goods

## Design Principles

1. Additive, not a rewrite.
Keep the current source-lot and run model intact.

2. Material genealogy is distinct from workflow history.
Queue events and booth events remain useful, but they are not themselves inventory lineage.

3. Every traceable material unit should have a lot record.
If management wants lot-level ancestry or descendants, derivative material needs a first-class lot ID.

4. Transformations should own lineage edges.
Do not encode genealogy with ad hoc parent IDs on every lot type.

5. Runs remain the business and execution summary.
Derivative lots should reference the run, not replace it.

6. Reconciliation matters as much as lineage.
The genealogy model must make quantity mismatches, orphaned outputs, and unresolved corrections visible.

7. Corrections must preserve history.
Operational mistakes will happen. The system should correct forward with auditability rather than silently rewriting genealogy.

8. Cost should travel with material.
The model should support allocating biomass and operational cost into derivative lots so lineage and cost reporting stay aligned.

## Proposed Data Model

### `MaterialLot`

One row per traceable material lot, regardless of lifecycle stage.

Suggested fields:

- `id`
- `tracking_id`
- `lot_type`
- `status`
- `quantity`
- `unit`
- `strain_name_snapshot`
- `supplier_name_snapshot`
- `source_purchase_lot_id` nullable
- `parent_run_id` nullable
- `active_queue_key` nullable
- `inventory_status`
- `workflow_status`
- `cost_basis_total`
- `cost_basis_per_unit`
- `origin_confidence`
- `correction_state`
- `notes`
- `created_at`
- `updated_at`
- `closed_at`
- `closed_reason`

Suggested `lot_type` values:

- `biomass`
- `wet_hte`
- `dry_hte`
- `wet_thca`
- `dry_thca`
- `golddrop`
- `liquid_diamonds`
- `liquid_loud`
- `wholesale_thca`
- `terp_strip_output`
- `hp_base_oil`
- `distillate`
- `packaged_goods`

The lot type registry should be treated as extensible. The exact controlled vocabulary should follow real operating outputs rather than stay limited to a fixed generic list.

### `MaterialTransformation`

One row per genealogy-producing process step.

Suggested fields:

- `id`
- `transformation_type`
- `run_id` nullable
- `source_record_type` nullable
- `source_record_id` nullable
- `performed_at`
- `performed_by_user_id`
- `status`
- `notes`
- `created_at`

Suggested `transformation_type` values:

- `extraction`
- `drying`
- `post_processing_split`
- `golddrop_production`
- `liquid_loud_release`
- `terp_strip`
- `hp_base_oil_conversion`
- `distillate_conversion`
- `blend`
- `rework`
- `packaging`
- `manual_adjustment`

### `MaterialTransformationInput`

Input lots consumed by a transformation.

Suggested fields:

- `id`
- `transformation_id`
- `material_lot_id`
- `quantity_consumed`
- `unit`
- `notes`

### `MaterialTransformationOutput`

Output lots produced by a transformation.

Suggested fields:

- `id`
- `transformation_id`
- `material_lot_id`
- `quantity_produced`
- `unit`
- `notes`

### Optional `MaterialLotEvent`

Keep this separate from genealogy if you want lot-local history without overloading `AuditLog`.

Suggested uses:

- lot created
- lot relabeled
- lot moved
- lot split
- lot closed
- lot re-opened

### Recommended `MaterialReconciliationIssue`

One row per detected integrity or quantity problem.

Suggested fields:

- `id`
- `issue_type`
- `severity`
- `material_lot_id` nullable
- `transformation_id` nullable
- `run_id` nullable
- `status`
- `detected_at`
- `detected_by`
- `resolution_note`
- `resolved_at`
- `resolved_by_user_id`

Suggested `issue_type` values:

- `quantity_mismatch`
- `orphan_output`
- `missing_input_link`
- `closed_lot_still_active`
- `negative_balance`
- `cost_allocation_gap`
- `manual_override_requires_review`

## Relationship To Existing Tables

### `PurchaseLot`

`PurchaseLot` remains the source biomass inventory record.

Recommended bridge:

- create a corresponding `MaterialLot` of `lot_type = biomass`
- store a nullable one-to-one link:
  - `PurchaseLot.material_lot_id`

This preserves current screens while enabling new genealogy queries.

### `Run`

`Run` remains the extraction execution and reporting summary.

Recommended bridge:

- each extraction run creates one `MaterialTransformation` with `transformation_type = extraction`
- transformation inputs come from the biomass `MaterialLot` records corresponding to `RunInput`
- transformation outputs create derivative `MaterialLot` records for the HTE / THCA material

### Downstream Queues

Current downstream queues are attached to `Run`.

Recommended evolution:

- Phase 1: keep queues attached to `Run`, but add linked derivative lot references for display and reporting
- Phase 2: allow destination workflows to operate on derivative `MaterialLot` records directly

This avoids breaking existing queue behavior while the genealogy layer is introduced.

### Cost Model Alignment

The genealogy layer should not become a disconnected traceability island.

Recommended bridge:

- `Run.calculate_cost()` remains the run-level cost engine at first
- initial derivative lots inherit cost from their parent run output split
- downstream transformations can later roll cost forward from parent lots into child lots

Near-term rule:

- extraction output lots inherit cost from the parent run
- split transformations apportion cost by quantity unless a more specific policy is defined
- blend transformations sum input cost bases into the output lot(s)

This keeps future cost reporting aligned with lineage instead of creating separate incompatible truths.

### Provenance / Confidence

Not every genealogy edge will originate the same way.

The model should record whether a link came from:

- direct operator entry
- run output auto-generation
- migration backfill
- inferred allocation
- manual correction

Recommended fields / enums:

- on `MaterialLot`: `origin_confidence`
- on transformations or links: `source_mode` and optional `source_reference`

Suggested confidence values:

- `confirmed`
- `system_generated`
- `backfilled`
- `inferred`
- `corrected`

This makes the system more transparent for managers and helps identify where trust is strongest or weakest.

## Mockup-Aligned UX Requirements

The `lot-journey-v2` mockup adds several requirements that should be treated as part of the plan rather than as a separate concept.

### Dual Journey Modes

The journey should support:

- `By Lot`
- `By Run`

This is not just navigation chrome. It reflects two legitimate management questions:

- starting from a source or derivative lot, where did it go?
- starting from a run, what fed it and what came out of it?

### Trunk + Branch Model

The mockup correctly separates:

- upstream trunk history:
  - purchase
  - receiving
- branch history:
  - extraction
  - post-processing
  - downstream production

The journey API should preserve that distinction. Upstream trunk stages are lot-anchored. Branch stages are run- and transformation-anchored.

### Remainders and Partial Consumption

The mockup explicitly shows remainder material after one or more runs.

That means genealogy must support:

- partial lot consumption
- residual source lot balance
- continued open inventory after some descendant transformations already exist

This reinforces the need to keep `PurchaseLot.remaining_weight_lbs` and bridge it into the genealogy layer rather than replacing it.

### Aggregate / Multi-Source Runs

The mockup explicitly models aggregate runs built from multiple source lots.

This should be considered a first-class genealogy case, not an exception.

That means the data model must support:

- many source lots into one transformation
- one transformation producing one or more output lots

This is already compatible with `MaterialTransformationInput`, and should be called out as a core design reason for that table.

### App-Surface Drill Links

The mockup includes step-to-app references such as:

- `Purchases`
- `Inventory`
- `Floor Ops`
- `Downstream Queues`
- `standalone-extraction-lab-app`

The final journey surface should not just show lineage. It should also provide operational drill links into the app surfaces where the tracked event occurred or can be acted on.

### Transitional UI Behavior

The mockup is slightly more conservative than the full end-state plan. It still presents downstream progress primarily as run phases.

That is acceptable in the short term.

The rollout should be:

1. add derivative genealogy in the data model
2. expose derivative lots in journey read surfaces
3. preserve run-centric downstream views during transition
4. only later make destination workflows operate directly on derivative lots

So the mockup should be treated as the transitional UX, while the full genealogy model remains the target backend architecture.

## Minimal Useful Workflow

### Extraction

Inputs:

- one or more biomass `MaterialLot` rows

Transformation:

- `MaterialTransformation(type=extraction, run_id=<run.id>)`

Outputs:

- one HTE derivative lot
- one THCA derivative lot

Examples:

- `dry_hte` if dry HTE is the real accountable output
- `wet_hte` plus later `drying` transformation if wet-to-dry matters operationally

### GoldDrop

Input:

- one HTE derivative lot

Transformation:

- `MaterialTransformation(type=golddrop_production)`

Output:

- one or more `golddrop` derivative lots

### Distillate / HP Base Oil / Terp Strip

Same pattern:

- consume one or more input lots
- create a transformation row
- produce new derivative lots

## Query Capability After This Change

After implementation, management should be able to ask:

1. Starting from a derivative lot:
- what upstream biomass lots contributed to this lot?
- which purchase batches did those biomass lots come from?
- which runs and downstream transformations touched this material?

2. Starting from a purchase lot:
- which derivative lots were ultimately created from this source lot?
- how much of the source lot went to each derivative outcome?
- what is still open, completed, reworked, or scrapped?

3. Starting from a run:
- what source lots fed it?
- which derivative lots were created from it?
- where are those derivative lots now?

4. Starting from a reconciliation problem:
- which lots or transformations are out of balance?
- what quantity is unresolved?
- who last corrected or overrode the affected record?

5. Starting from a cost question:
- what cost basis is sitting in each derivative lot?
- which source lots contributed to that cost?
- what released product quantity carried that cost forward?

## UI / API Changes

### New Journey Expansion

Extend the existing journey concept to support descendants as well as upstream allocations.

New read surfaces:

- derivative lot detail page
- derivative lot journey API
- lot descendants view
- lot ancestry view

Suggested endpoints:

- `/api/v1/material-lots/<lot_id>`
- `/api/v1/material-lots/<lot_id>/journey`
- `/api/v1/material-lots/<lot_id>/ancestry`
- `/api/v1/material-lots/<lot_id>/descendants`

### Existing Journey Enhancements

Enhance current purchase / lot / run journey payloads to include:

- derivative output lots linked from runs
- downstream transformations linked from those output lots
- descendant counts and open/closed status
- remainder / unconsumed balance visibility on source lots
- aggregate / multi-source transformation visibility
- drill links to the relevant operational surface for each major step

### Queue Surfaces

Eventually each downstream queue card should show:

- linked derivative lot tracking ID
- lot type
- current quantity
- upstream source count
- quick-link to lot ancestry / descendants
- reconciliation warning badge when lineage or quantity integrity is unresolved
- cost summary when useful for management review

## Audit Expectations

Genealogy should not depend on `AuditLog`, but the two should complement each other.

Recommended audit behavior:

- creating a `MaterialLot` writes an `AuditLog`
- creating a `MaterialTransformation` writes an `AuditLog`
- changing lot status, relabeling, closing, splitting, or rework writes an `AuditLog`

But the authoritative lineage query should come from:

- `MaterialTransformationInput`
- `MaterialTransformationOutput`

not from free-text audit records.

## Integrity, Error Detection, And Correction

This app is not only for lineage lookup. It also exists to surface mistakes early and make corrections accountable.

### Reconciliation Checks

The system should detect and flag:

- source lots whose consumed quantity exceeds available quantity
- runs with output lots but no source transformation inputs
- downstream derivative lots whose parent transformation is missing
- child lots whose parent lots remain incorrectly open or fully available
- cost-bearing lots with missing cost basis

### Correction Strategy

Recommended rule:

- do not delete or silently rewrite lineage edges when correcting production data
- instead create a correction transformation or explicit audit-backed adjustment

Examples:

- mistaken derivative lot creation -> close the lot with a corrective note and create the correct lot
- wrong parent link -> create a correction record that severs the old edge and establishes the new one with audit context
- quantity mistake -> record an adjustment transformation rather than editing away history

### Review Surfaces

Managers should eventually have:

- an unresolved genealogy issues queue
- lot detail pages that show corrections and confidence level
- dashboards for orphan lots, negative balances, and unresolved overrides

## Reporting Outcomes

The genealogy model should explicitly support the app's management goals:

- visibility into where material came from and where it went
- transparency into partial consumption, blends, splits, and rework
- cost roll-forward from biomass to derivative lots and released goods
- audit-ready history for creation, correction, and release
- error detection for quantity, lineage, and cost mismatches

The first reporting set should target:

- lot ancestry
- lot descendants
- open derivative inventory by type
- released derivative inventory by type
- source-to-derivative yield by lot
- rework volume by source lot and by destination
- unresolved genealogy issues
- quantity reconciliation exceptions
- cost basis by open and released derivative lot

## Migration Strategy

### Phase 1: Schema Foundation

Add:

- `MaterialLot`
- `MaterialTransformation`
- `MaterialTransformationInput`
- `MaterialTransformationOutput`

No UI dependency yet.

Migration requirements:

- schema creation must be additive
- backfills must be idempotent
- existing run and queue workflows must remain usable even if genealogy backfill is incomplete
- unresolved migration exceptions should be visible rather than silently ignored

### Phase 2: Biomass Bridge

Backfill one `MaterialLot(type=biomass)` per active `PurchaseLot`.

Rules:

- preserve source tracking IDs
- snapshot supplier / strain
- link back to `PurchaseLot`
- mark these rows as `origin_confidence = backfilled`

### Phase 3: Run Output Lots

When a run has recorded output quantities, create derivative output lots.

Initial recommendation:

- create `dry_hte` lot when `dry_hte_g` is recorded
- create `dry_thca` lot when `dry_thca_g` is recorded

Optionally add wet-stage lots later if operations need them.

Recommended accountable default:

- create output lots from dry output fields first
- add wet-stage lots only if a real operational accountability need exists

### Phase 4: Journey Read Surfaces

Add derivative lot journey APIs and UI drill-down.

### Phase 5: Downstream Queue Linking

Attach queue items to derivative lots while preserving run-based workflow.

### Phase 6: Destination-Native Operations

Allow downstream production workflows to consume one derivative lot and produce another.

This is when genealogy becomes fully end-to-end.

## Open Product Decisions

1. What is the accountable extraction output?

Choose one:

- dry-only output lots
- wet and dry output lots

2. Do downstream destinations always create new lots, or can some destinations just change status on an existing lot?

Recommended default:

- conversion creates a new lot
- pure hold/review updates status on the existing lot

3. Do blends need explicit many-to-many genealogy?

Recommended answer:

- yes, via `MaterialTransformationInput`

4. Do packaged goods need their own lot records?

Recommended answer:

- yes, if management wants true finished-goods traceability

5. Should the UI expose derivative genealogy immediately as a pure lot graph, or as run-centric cards with linked derivative lots?

Recommended answer:

- start with run-centric cards plus linked derivative lot cards
- move to fuller lot-native navigation once operators and managers are comfortable with the new model

6. Should the system allow manual derivative lot creation outside a run-backed transformation?

Recommended answer:

- only in tightly controlled admin / correction workflows
- normal operations should create derivative lots through transformations

## Recommended First Coding Sprint

Implement only the safe foundation:

1. add the four genealogy tables
2. backfill biomass `MaterialLot` rows from active `PurchaseLot` rows
3. add internal helpers to resolve:
- biomass lot for `PurchaseLot`
- source biomass lots for a `Run`
4. add minimal reconciliation checks for orphan / negative-balance conditions
5. do not yet change operator workflow screens

## Appendix A: Lot Creation Rules

These rules should be explicit so the system creates lots consistently.

### Biomass Lots

Creation trigger:

- `PurchaseLot` exists or is backfilled

Rule:

- one `MaterialLot(type=biomass)` per active `PurchaseLot`

### Extraction Output Lots

Default accountable rule:

- when `dry_hte_g` is first recorded and no `dry_hte` derivative lot exists, create one `MaterialLot(type=dry_hte)`
- when `dry_thca_g` is first recorded and no `dry_thca` derivative lot exists, create one `MaterialLot(type=dry_thca)`

Creation source:

- `MaterialTransformation(type=extraction, run_id=<run.id>)`

### Split Output Lots

Creation trigger:

- a downstream decision intentionally divides one parent lot into multiple accountable child lots

Examples:

- THCa split into `liquid_diamonds` and `wholesale_thca`
- one HTE lot split into two production batches

Rule:

- create one child `MaterialLot` per accountable destination lot
- parent lot remains open only if a residual quantity still exists
- otherwise parent lot closes as `consumed` or `split_complete`

### Blend Output Lots

Creation trigger:

- two or more parent lots are intentionally combined into one accountable child lot

Rule:

- create one `MaterialTransformation(type=blend)`
- consume quantities from all parent lots
- create one or more blended child lots

### Rework Lots

Creation trigger:

- previously created derivative material is intentionally reprocessed into a new accountable material state

Rule:

- create a new child lot when rework changes accountable identity or destination
- use a rework transformation rather than relabeling the parent lot silently

## Appendix B: Status Transition Rules

The model should distinguish inventory truth from workflow truth.

### `inventory_status`

Suggested allowed values:

- `open`
- `partially_consumed`
- `fully_consumed`
- `released`
- `held`
- `scrapped`
- `archived`

Rules:

- `open` means quantity is still available
- `partially_consumed` means some quantity remains
- `fully_consumed` means no quantity remains for future transformations
- `released` means inventory has left accountable internal stock
- `held` means quantity exists but is intentionally blocked
- `scrapped` means quantity is no longer usable

### `workflow_status`

Suggested allowed values:

- `new`
- `queued`
- `in_process`
- `review_pending`
- `release_ready`
- `completed`
- `correction_pending`

Rules:

- workflow status may change without changing quantity
- inventory status should only change on real inventory events

### Transition Guardrails

- a `fully_consumed` lot cannot become `open` again without a corrective adjustment
- a `released` lot cannot be consumed by another transformation unless a return / correction flow exists
- a child lot should not reach `released` if its parent transformation is incomplete or unresolved

## Appendix C: Split / Blend / Rework Rules

### Split Rules

- split by creating explicit child lots
- decrement or close the parent based on residual quantity
- preserve the parent-child transformation link
- apportion cost by quantity unless an approved policy overrides it

### Blend Rules

- every contributing parent lot must be listed as a transformation input
- the child lot should carry summed cost basis from all parents
- ancestry queries must show all upstream contributing biomass lots

### Rework Rules

- rework creates a new transformation record
- if the output is materially different in accountability, create a new child lot
- the parent lot should close or partially consume according to quantity used
- the rework reason should be mandatory
- manager review should be available for manual rework corrections

## Appendix D: Accountable Lot Creation Matrix

This matrix should govern when the system creates a new accountable derivative lot.

| Process area | Trigger event | Create lot type | Parent reference | Notes |
|---|---|---|---|---|
| Biomass intake | `PurchaseLot` created or backfilled | `biomass` | `PurchaseLot` | One-to-one bridge from source inventory lot |
| Extraction | `dry_hte_g` first recorded | `dry_hte` | `Run` / `extraction` transformation | Recommended default accountable HTE lot |
| Extraction | `dry_thca_g` first recorded | `dry_thca` | `Run` / `extraction` transformation | Recommended default accountable THCa lot |
| THCa split | THCa routed into multiple outcomes | `liquid_diamonds`, `wholesale_thca`, or other destination-specific lot | parent `dry_thca` lot | Use explicit split transformation |
| GoldDrop conversion | GoldDrop production batch created | `golddrop` | parent `dry_hte` or other approved parent lot | Output may be one or more production lots |
| Liquid Loud reservation / conversion | Material is promoted into an accountable Liquid Loud lot | `liquid_loud` | parent lot | If the hold remains only a hold, do not create a new lot yet |
| Terp strip | Strip/CDT output becomes accountable material | `terp_strip_output` | parent `dry_hte` lot | Create new lot when output is materially distinct |
| HP base oil conversion | HP base oil production lot created | `hp_base_oil` | parent lot | Create on actual conversion, not just hold |
| Distillate conversion | Distillate production lot created | `distillate` | parent lot | Create on actual conversion, not just hold |
| Packaging | Finished packaged accountable lot created | `packaged_goods` | parent derivative lot | Only if packaged-goods traceability is required |

Rules:

- holds and queues alone do not create a new lot unless accountable material identity changes
- a new lot is created when management would expect a new traceable material identity
- if a process only changes workflow state, keep the same lot and update status instead

That first sprint creates the substrate for true derivative traceability without destabilizing current production behavior.

## Expected Outcome

After the full genealogy layer lands, the app will be able to answer both of the manager questions cleanly:

- starting from a derivative lot of HTE, determine every source biomass lot and purchase batch that contributed to it
- starting from a purchase lot, determine every derivative lot and downstream product that was made from it

That is the missing capability between the current run-centric journey model and true lot-centric production genealogy.
