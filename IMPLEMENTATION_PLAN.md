# Gold Drop - Next Sprint Implementation Plan

This plan replaces the older modularization-first execution list. The next product priority is the operational handoff from received biomass into extraction.

## Sprint Focus

Build `Extraction Charge / Start Run From Lot` as the canonical production-start workflow.

The business sequence is:

1. Buy
2. Receive
3. Extract
4. Test can occur before buy, after receipt, or after extraction depending on supplier trust and process stage

Testing remains important, but it should be modeled around extraction readiness rather than forcing a single linear "test first" workflow.

## Product Goal

Allow an extractor to take a purchased and received lot, allocate all or part of it into production, and record:

- exact source lot
- pounds charged
- reactor
- timestamp
- operator
- optional notes
- optional evidence from scan, Slack, or future scale capture

This charge event should become the source of truth regardless of how it is initiated:

- main app desktop workflow
- scan-first lot workflow
- Slack-triggered flow
- future standalone extractor app

## Why This Is Next

The repo already has stable buying and receiving workflows plus the lot-allocation foundations required to support extraction cleanly:

- `PurchaseLot` tracking ids, barcode/QR payloads, and scan history
- `/scan/lot/<tracking_id>` and `/scan/lot/<tracking_id>/start-run`
- `RunInput` explicit lot allocations
- run-form validation that lot allocations equal reactor input pounds
- Slack run preview and lot-candidate ranking
- scale-capture persistence primitives

What is missing is a dedicated operator workflow that treats "put this lot into reactor X now" as a first-class business event rather than a generic run-form prefill.

## Canonical Workflow

### Primary operator path

1. Extractor scans a lot label or opens a lot from the main app.
2. System shows lot identity and current operational state:
   - tracking id
   - supplier
   - strain
   - remaining lbs
   - potency when present
   - clean / dirty state
   - testing state
   - received location / floor state
3. Extractor enters:
   - pounds going into production
   - reactor
   - charge time
   - optional notes
4. System validates the allocation against remaining inventory and reactor-input rules.
5. System creates the extraction charge record and opens the downstream run workflow with the allocation already attached.

### Alternate entry paths

- Main app: manual lot selection and charge entry
- Slack: parse a floor message into the same charge workflow, with confirmation when confidence is low
- Future extractor app: mobile-first frontend against the same backend service

## User Stories

### Extractor

- As an extractor, I can scan a lot label and immediately start charging biomass into a reactor.
- As an extractor, I can allocate only part of a lot and leave the remainder on hand.
- As an extractor, I can see enough lot state before charging to avoid using the wrong material.
- As an extractor, I can record the actual charge time instead of relying on a later office edit.

### Production lead

- As a production lead, I can see which lots were charged into which reactors and when.
- As a production lead, I can trust that lot balances reflect actual extraction allocations.

### Operations / audit

- As an operator or auditor, I can trace a run backward to the exact source lot allocation.
- As an operator or auditor, I can see whether a charge was initiated by scan, main app, Slack, or future device-assisted entry.

## Scope For This Sprint

### In scope

- Dedicated extraction-charge workflow in the main app
- Scan-first handoff from scanned lot to reactor charge form
- Shared backend service for creating a charge from a lot allocation
- Testing/readiness state shown during charge review
- Audit trail for charge creation source and operator context
- Run creation or run-prefill flow that preserves the charge allocation as explicit `RunInput`

### Out of scope

- Full standalone extractor app
- Live Slack auto-commit without operator confirmation
- Connected-scale live hardware ingestion
- Finished graph-style Batch Journey expansion beyond the current journey baseline
- New testing lab pipelines beyond exposing the relevant state at charge time

## UX Surfaces

### 1. Main app extraction charge screen

Add a dedicated screen reachable from:

- Inventory lot views
- Purchase detail / purchase lots section
- Scan flow redirect
- Floor activity page

Required fields:

- source lot
- charge weight lbs
- reactor
- charge timestamp
- operator defaulted from session
- optional notes

Read-only lot context on screen:

- supplier
- strain
- remaining lbs before charge
- potency
- testing state
- clean / dirty
- received date and current location when available

### 2. Scan-first charge flow

Refine `/scan/lot/<tracking_id>` so the operator can go directly from a scanned lot into a purpose-built charge form instead of a generic run edit flow.

Desired choices:

- charge full remaining lot
- charge partial lbs
- open blank run with this lot preselected
- capture scale evidence first when that workflow is later enabled

### 3. Floor activity handoff

Extend the floor page so recent scans can be acted on as "charge this lot now" tasks, not just reviewed as scanner history.

### 4. Slack alternate flow

Slack should create or prefill the same extraction charge workflow rather than bypass it with a separate business path.

## Backend Changes

### Service boundary

Create a shared extraction-charge service that:

- validates source lot usability
- validates requested pounds against remaining inventory
- records charge metadata
- attaches source mode such as `main_app`, `scan`, `slack`, or future `extractor_app`
- prepares or creates the downstream run context with explicit lot allocation

Possible location:

- `services/extraction_charge.py`

### Data model direction

Prefer introducing a canonical charge object or equivalent persisted event instead of hiding the entire action inside run-prefill session state.

Minimum required fields:

- id
- purchase_lot_id
- run_id when linked
- charged_weight_lbs
- reactor
- charged_at
- charged_by_user_id
- source_mode
- notes
- optional slack/scanner/weight-capture references

If a new table is deferred for a first slice, the implementation must still preserve the event semantics and audit trail clearly enough to migrate later without ambiguity.

### Validation rules

- lot must exist and not be soft-deleted
- lot must have remaining inventory
- requested charge weight must be greater than zero
- requested charge weight must not exceed remaining inventory
- unapproved or otherwise blocked inventory must still honor existing purchase approval rules
- reactor assignment must use current run/reactor rules already enforced elsewhere

## Testing-State Handling

Extraction should not assume one fixed test order. The product should surface testing as separate operational facts:

- pre-purchase testing state
- received-biomass testing state
- post-extraction testing state

For this sprint:

- show the currently known lot testing state clearly during charge
- allow business rules later to classify lots as:
  - allowed
  - allowed with warning
  - blocked pending review

Do not hardcode "tested" as a single boolean that tries to represent all stages.

## Proposed Route / Entry Changes

Potential additions:

- `GET /lots/<lot_id>/charge`
- `POST /lots/<lot_id>/charge`
- `GET /scan/lot/<tracking_id>/charge`

Potential refactors:

- keep `/scan/lot/<tracking_id>/start-run` as compatibility path or make it redirect into the new charge flow
- keep existing run-form creation path available for office/admin use

## Test Plan

### Targeted tests during implementation

- lot charge validation rules
- scan-to-charge route behavior
- charge-to-run allocation persistence
- blocked vs warning-ready testing states
- audit source tagging

### Full-suite closeout before final commit

- full Python suite
- affected standalone app suites if Slack/mobile/frontend flows change

### New regression scenarios

- charge full remaining lot into a reactor
- charge partial lbs from a lot and preserve the remainder
- reject charge when requested lbs exceeds remaining lbs
- reject charge from inventory that is not approved/usable
- preserve exact source lot allocation into the run
- scan flow opens the correct lot and preloads the charge form
- Slack-assisted flow preserves the same canonical allocation semantics

## Documentation To Update When This Ships

Core docs:

- `PRD.md`
- `README.md`
- `FAQ.md`
- `ENGINEERING.md`
- `CHANGELOG.md`

Conditional docs:

- `USER_MANUAL.md`
- API docs if new routes are exposed
- deployment/runbook docs if scan or standalone surfaces change

## Definition Of Done

- operators can start extraction from a specific received lot without using a generic workaround
- partial and full lot charges both work
- the reactor charge records exact source lot, pounds, reactor, time, and operator
- the resulting run context preserves explicit lot allocation
- scan-first workflow lands in the same charge flow
- testing state is visible at charge time without forcing one rigid upstream sequence
- targeted tests pass during development
- full Python suite passes before final commit
- affected docs are updated

## Follow-On Work After This Sprint

1. Standalone extractor app using the same extraction-charge backend
2. Slack confidence buckets and guided manual resolution into extraction charge
3. Connected-scale assisted charge confirmation
4. Richer Batch Journey graph with charge-event nodes and allocation edges
5. Deeper testing and post-extraction department workflows
