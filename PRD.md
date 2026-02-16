# Gold Drop Production Tracker — Product Requirements Document (PRD)

## Summary
Gold Drop is an operations tracker for biomass intake → inventory → extraction runs → yield/cost analytics. It supports:
- A **Biomass Pipeline** (farm declarations through testing and commitment),
- **Purchases** with **unique batch identifiers**,
- **Inventory lots** consumed by **Runs**,
- **Operational cost entries** allocated into **$/g**,
- **Analytics controls** to exclude runs missing biomass pricing,
- **Audit logging** for traceability and compliance.

This PRD describes the problem, users, workflows, data requirements, calculations, settings, and acceptance criteria.

---

## Problem Statement
Operations needs a single system to answer:
- What biomass is available, being tested, committed, delivered, or cancelled?
- Which purchase batch did it become, and what is its unique identifier?
- How much biomass is on hand/in transit, and how many days of supply remain?
- How are THCA/HTE yields trending by supplier and strain?
- What is the **true cost per gram** (including biomass input cost and operational costs) and how should cost be split across THCA vs HTE?
- How do we avoid skewed analytics when biomass pricing is missing?

---

## Goals
- **Pipeline visibility**: track biomass availability as it moves from declaration → testing → commitment → delivery.
- **Batch-level traceability**: every purchase has a **unique, human-readable Batch ID**.
- **One source of truth** for material usage: lots decrement as runs consume them.
- **Accurate $/g**: include biomass $/lb inputs and allocated operational costs.
- **Configurable allocation**: choose how total run dollars are distributed between THCA and HTE.
- **Data quality controls**: clearly flag runs missing biomass pricing and optionally exclude them from analytics.
- **Auditability**: record critical create/update/delete actions (including purchases created/updated indirectly via the biomass pipeline).

## Non-goals (for now)
- Full accounting/ERP integration
- Automated lab COAs ingestion (manual entry only)
- Multi-facility support
- Replacing the Biomass Pipeline model by merging it fully into Purchases (see “Future improvements”)

---

## Users & Permissions
- **Super Admin**
  - Full access
  - Can manage Users
  - Can access Settings + Maintenance actions (e.g., recalculate all run costs)
- **User**
  - Can create/edit operational data (runs, purchases, biomass pipeline, costs)
- **Viewer**
  - Read-only access

---

## Core Concepts & Entities
### Suppliers (farms)
Represents the source farm. Suppliers can have:
- Many **Purchases**
- Many **BiomassAvailability** records (pipeline)

### BiomassAvailability (pipeline record)
Tracks availability before it becomes a Purchase. Key stages:
- `declared`
- `testing`
- `committed`
- `delivered`
- `cancelled`

It may link **one-to-one** to a Purchase once committed/delivered/cancelled.

### Purchases (batch-level financial/receiving record)
Represents the committed/delivered batch. Contains:
- Supplier, purchase/delivery dates
- Status (includes operational statuses; supports early/manual status `declared`)
- Weights, potency (stated/tested), $/lb
- Total cost + true-up values
- **Batch ID** (unique, human-readable)

### PurchaseLots (inventory lots)
Represents strains within a purchase with:
- Weight and remaining weight
- Potency %
- Location / milled flag

### Runs (extraction)
Represents an extraction run with:
- Inputs (RunInput rows pointing to lots and weights)
- Wet/dry outputs for THCA and HTE
- Yield calculations
- Cost calculations (combined and product-specific)

### CostEntry (operational costs)
Represents operational spend over a date range:
- Type: solvent/personnel/overhead
- Total cost and optional unit cost/qty
- Start/end dates

---

## End-to-End Workflows
### 1) Biomass Pipeline workflow
#### Declaration
Fields:
- Availability Date (required)
- Declared Weight (lbs) (>= 0)
- Declared $/lb (>= 0, optional)
- Estimated potency % (0–100, optional)
- Strain name (optional)

Acceptance criteria:
- User can create a record in stage `declared`.
- Validation errors show friendly messages; no stack traces are flashed.
- Audit log entry is written for create/update/delete.

#### Testing
Fields:
- Testing timing: before_delivery | after_delivery
- Testing status: pending | completed | not_needed
- Testing date (optional, valid date)
- Tested potency % (0–100, optional)

Acceptance criteria:
- User can move a record to stage `testing` and record testing metadata.
- If stage is set to `testing`, no Purchase is created automatically.

#### Commitment
Fields:
- Committed On (date, optional)
- Delivery Date (date, optional)
- Committed Weight (lbs, >= 0, optional)
- Committed $/lb (>= 0, optional)

Purchase synchronization rules:
- When stage becomes **committed** or **delivered**, if no linked Purchase exists, create one.
- If a linked Purchase exists, keep key fields in sync (supplier/date/weight/potency/$/lb/status).
- If stage becomes `cancelled`, keep linked Purchase status in sync (if it exists).
- If stage is moved backward (e.g., `committed` → `testing`), the system keeps the linked Purchase status aligned (no drift).

Audit requirements:
- If the biomass pipeline creates/updates a Purchase, a **purchase audit log** entry must be recorded indicating it was biomass-driven.

---

### 2) Purchases workflow
#### Batch ID generation
- Batch IDs are **unique** and **human-readable**.
- Default format: `PREFIX-DDMONYY-WEIGHT` (example `FARML-15FEB26-200`)
  - `PREFIX`: first 5 alphanumeric characters of supplier name (uppercased)
  - Date: delivery date if present else purchase date
  - Weight: actual weight if present else stated weight, rounded to int
- If a generated value conflicts, suffix with `-2`, `-3`, … (bounded attempts).
- IDs are truncated to 80 chars to respect schema constraints.

Acceptance criteria:
- Leaving Batch ID blank auto-generates a valid unique value.
- Entering a conflicting Batch ID returns a clear validation error.

#### Purchase ↔ Biomass Pipeline synchronization
- If a Purchase is linked to a BiomassAvailability record, changes to Purchase `status` update biomass `stage` with nuanced mapping:
  - committed/ordered/in_transit → stage `committed`
  - in_testing/available → stage `testing`
  - delivered/processing/complete → stage `delivered`
  - cancelled → stage `cancelled`
  - declared/testing (manual/early) → stage matches when present

Acceptance criteria:
- Editing a Purchase status updates linked biomass stage reliably.

---

### 3) Inventory workflow
- Inventory shows:
  - On-hand lots (from arrived statuses)
  - In-transit purchases
  - Days of supply based on configured daily throughput target

Acceptance criteria:
- When a run uses lot weights, `remaining_weight_lbs` decrements.
- Deleting a run restores decremented lot weights.

---

### 4) Runs workflow (yield + cost)
#### Yield calculations
Definitions:
- grams_ran = \(bio\_in\_reactor\_lbs \times 454\)
- overall_yield_pct = \(\frac{dry\_hte\_g + dry\_thca\_g}{grams\_ran} \times 100\)
- thca_yield_pct = \(\frac{dry\_thca\_g}{grams\_ran} \times 100\)
- hte_yield_pct = \(\frac{dry\_hte\_g}{grams\_ran} \times 100\)

Acceptance criteria:
- Yields compute on save and update when outputs change.

#### Cost calculations (biomass + OpEx)
Total run dollars include:
- **Biomass cost**: sum(inputs_lbs × purchase.price_per_lb) for each input lot where pricing exists
- **Operational cost allocation**:
  - For each CostEntry whose date range contains the run date:
    - Compute total dry grams produced across all runs in that cost period
    - Allocate entry.total_cost evenly across grams to form a $/g contribution
  - Sum all applicable $/g contributions into an `op_rate`
- total_cost_for_run = biomass_cost + op_rate × total_dry_grams_for_run
- cost_per_gram_combined = total_cost_for_run ÷ total_dry_grams_for_run

#### THCA vs HTE allocation methods (settings)
The system supports configurable product allocation (for `cost_per_gram_thca` and `cost_per_gram_hte`):
- **Uniform $/g (default)**: THCA and HTE match combined $/g
- **Split 50/50**: split total run dollars evenly between THCA and HTE (when both exist)
- **Custom split**: allocate total run dollars by THCA % (remainder to HTE)

Acceptance criteria:
- Combined $/g always equals total dollars ÷ total dry grams.
- Split methods produce higher $/g for lower-yield product when both outputs exist.

---

### 5) Costs workflow
- Users can create/edit/delete CostEntry records (solvent/personnel/overhead) with:
  - Start date / end date
  - Total cost (required)
  - Optional unit cost, quantity, unit, notes

Acceptance criteria:
- Cost list shows totals by type and overall OpEx.
- New/updated costs affect run $/g calculations.
- Admin can trigger “Recalculate all run costs” after changing settings or entering costs.

---

## Analytics & Data Quality
### Missing biomass price indicator
Runs can have missing purchase pricing on one or more input lots.
Requirements:
- Runs list shows a clear badge:
  - “No $/lb” when none of the inputs have prices
  - “Partial $/lb” when some inputs have prices and some do not

### Excluding unpriced runs from analytics
Setting: `exclude_unpriced_batches`
When enabled, Dashboard/Supplier/Strain analytics:
- Exclude runs that have no inputs **or** have any input lot whose purchase has null `price_per_lb`.

Acceptance criteria:
- Dashboard shows a banner when the filter is enabled.
- Supplier and Strain pages do not break under group-by queries when filter is enabled.

---

## Audit Logging Requirements
AuditLog must capture:
- **Who** (user_id)
- **What** (action, entity_type, entity_id)
- **When** (timestamp)
- **Details** (JSON string, minimized and non-sensitive)

Critical requirements:
- Biomass create/update/delete actions must be logged.
- Purchase create/update/delete actions must be logged.
- Purchases created/updated indirectly via Biomass Pipeline must also generate purchase audit log entries indicating source = biomass_pipeline and biomass_id.

---

## Non-Functional Requirements
- **Security**
  - Do not display raw exception messages to end users.
  - Role-based access must gate edit/admin-only routes.
- **Reliability**
  - Validation prevents obvious invalid data (negative weights, invalid dates, invalid stages).
  - Batch ID generation must not hang (bounded attempts).
- **Maintainability**
  - SQLite schema evolution supported via lightweight startup adjustments.
- **Performance**
  - Analytics queries should be efficient; filters must not trigger ORM correlation errors.

---

## Future Improvements (Roadmap)
- Consider consolidating Biomass Pipeline into Purchases by expanding purchase statuses to include pre-commitment stages (declared/testing), reducing duplication and sync logic.
- Add richer analytics screens (time series, variance by reactor/operator).
- Add COA upload + parsing, and stronger validation rules around potency/pricing.
- Add automated alerts for “missing $/lb” purchases linked to recent runs.

