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
It can also include optional **field photos** (multiple images) captured at intake.

### Field intake submissions
Field users can submit data through secure links for:
- Biomass availability declarations
- Purchase requests (including multiple lot lines)

Both field forms support optional photo uploads:
- Allowed formats: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif`
- Max file size: 20 MB per photo
- Files are stored under `static/uploads/field/` and referenced by relative path in JSON fields

Field purchase intake requires/accepts:
- Purchase date, expected delivery date, harvest date
- Storage note and license information text
- Queue placement (`aggregate`, `indoor`, `outdoor`)
- Testing/COA status text
- Separate image categories for supplier/license docs, biomass photos, and testing/COA photos
- Lot line strain and lot line weight are optional in field intake (at least one lot row can still be submitted for context)

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
- Photos (optional, multiple images)

Acceptance criteria:
- User can create a record in stage `declared`.
- Validation errors show friendly messages; no stack traces are flashed.
- Audit log entry is written for create/update/delete.
- Invalid photo type or oversized photo shows a friendly validation message.

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
#### Field purchase submissions
Secure field links can submit purchase requests with:
- Supplier, date, estimated potency, $/lb, notes
- One or more lot lines (weight required, strain optional)
- Optional categorized photos (supplier/license, biomass, testing/COA)

Review requirements:
- Pending table only shows unreviewed submissions.
- Reviewed submissions are retained in a separate history table.
- Admin review table displays categorized submission photo thumbnails when present.
- Clicking a thumbnail opens the full image in a new tab.
- On approval, supplier/license photos are promoted into supplier attachments for persistent supplier document review.
- On approval, biomass/COA photos are retained as purchase-linked audit media.

Photo library requirements:
- The app provides a central photo/media library view.
- Library supports filtering by supplier, purchase, and category.
- Library supports free-text search against tags/title/path metadata.
- Assets are indexed from field submissions, supplier attachments, and lab test uploads.
- PDFs should remain accessible in the library with non-image preview handling.

Delete/cleanup requirements:
- Runs and purchases support soft delete for operational safety.
- Super admin can hard-delete runs/purchases for sandbox cleanup.
- Revoked/expired field tokens can be removed from Settings.
- User accounts remain disable-first; hard delete is blocked when audit history exists.

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
- Dashboard includes week-to-date quick metrics (lbs ran, dry THCA, dry HTE).
- Dashboard includes best-yielding supplier month-over-month view.

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
- Purchase and supplier media must remain traceable from source submission/document to final record context.

## Maintenance & Backfill Requirements
- Super Admin can run a one-time historical media backfill from Settings.
- Backfill processes approved field submissions and:
  - creates missing supplier attachments for supplier/license images,
  - creates searchable media index records for supplier/purchase audit photos.
- Backfill must be idempotent (safe to re-run without duplicating records).

---

## Integrations — Slack
- **Configuration:** Super Admin stores webhook URL, signing secret, bot token, and default channel in Settings. Outbound notifications post when integration is enabled.
- **Channel history sync (admin tooling):** Super Admin configures up to **six** Slack channels (by `#name` or channel ID) under **Slack Integration → Channel history sync**, then runs **Maintenance → Sync Slack channel history**. The sync uses Slack `conversations.history`, dedupes messages by **channel ID + message `ts`**, and stores rows for review (yield/production-style parsing hints); it does **not** auto-create Run records. **First sync** for each configured channel uses a configurable rolling window (**Days back**). **Subsequent syncs** use a **per-channel cursor** (last ingested message timestamp / watermark) so each channel incrementally fetches only newer messages. Editing a channel hint clears that slot’s resolved ID and cursor. New installs seed sync slot 0 from **Default Channel** when no sync rows exist yet.
- **Inbound HTTP endpoints (no user session):** requests must be verified with Slack’s signing secret (HMAC).
  - **Slash commands:** `POST /api/slack/command`
  - **Interactivity:** `POST /api/slack/interactivity`
  - **Events API:** `POST /api/slack/events` — must respond to `url_verification` with JSON `{ "challenge": "<value>" }`; must acknowledge `event_callback` within Slack’s timeout (hook for future channel/message automation).
- **Production:** Event Subscriptions Request URL must use **HTTPS** on the public hostname nginx serves.

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

