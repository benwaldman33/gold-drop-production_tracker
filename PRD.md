# Gold Drop Production Tracker — Product Requirements Document (PRD)

## Summary
Gold Drop is an operations tracker for biomass intake → inventory → extraction runs → yield/cost analytics. It supports:
- A **Biomass Pipeline** (farm declarations through testing and commitment),
- **Purchases** with **unique batch identifiers**,
- **Inventory lots** consumed by **Runs**,
- **Operational cost entries** allocated into **$/g**,
- **Analytics controls** to exclude runs missing biomass pricing,
- **Audit logging** for traceability and compliance.

**Cross-cutting product direction (department views & governance):** the same underlying data should be exposed through **department-focused UIs** (finance, purchasing, intake, extraction, downstream processing, testing, sales) without duplicating business rules; **Slack** remains the **authoritative operational input channel** for floor capture until a future phase adds first-class barcode / QR and connected-scale workflows. **Purchase approval** uses **per-user capabilities**; a single approval promotes a potential purchase to a **system-wide commitment**, including the **weekly budget dashboard**. **Potential** pipeline lines that never close otherwise **age out** to **Old Lots** and then **soft-delete** on a configurable schedule anchored to **`created_at`**.

**Operator workflow — list views:** On primary **list screens** (Runs, Purchases, Biomass Pipeline, Costs, Inventory, Strains, Slack imports), **filters, date constraints, sort order, and related query state** are **persisted in the user’s server session** so operators can **navigate freely between app sections** and return **without re-entering** those choices—reducing repetitive work and supporting multi-step review (e.g. cross-checking Slack imports against Purchases). Persistence is **session-scoped** (not a permanent per-user database preference): sign-out, cookie loss, or timeout ends it. Each list exposes **Remove filters** (or equivalent) to restore the default unfiltered view. **Pagination** resets to **page 1** when filters are applied or certain primary facets change (e.g. Purchases status) so narrowed result sets are not shown as empty due to a stale page index.

**Operator workflow — batch edits:** On list screens where users can already open a single-row **Edit** (Runs, Purchases, Biomass Pipeline, Costs, Suppliers, Strain Performance) and on **Inventory** (on-hand **lots** and in-transit **purchases**), the UI provides **row checkboxes**, **Select all** / **Select none** (current **page** only), and **Batch edit…** enabled when **at least two** rows are selected. The user is taken to a **batch apply** screen with **optional** fields; only populated fields are written to **all** selected records. **Permissions** match single-record edit (`can_edit` vs `can_edit_purchases` as appropriate). **Strain Performance** uses **Batch rename…** to apply a new strain label to all matching **PurchaseLot** rows for the selected strain+supplier pairs. Purchase batch status/delivery/queue/notes changes must honor the same **inventory lot** and **weekly biomass budget** rules as single purchase save.

**Operator workflow — purchase spreadsheet import:** Users with purchase edit access can upload **CSV or Excel** (`.csv`, `.xlsx`, `.xlsm`) via **Purchases → Import spreadsheet**; the system **maps columns by header name** (including common accounting layouts: Vendor, Purchase Date, Invoice Weight, Actual Weight, Manifest, Amount, etc.), shows a **preview** with per-row validation, then commits selected rows into **Purchase** records (and optional **PurchaseLot** when a strain column is present). Staging uses a **server temp file** plus session token (not large cookie payloads). Duplicate **Batch ID** values are rejected; optional **auto-create suppliers** is supported.

This PRD describes the problem, users, workflows, data requirements, calculations, settings, and acceptance criteria.

**April 2026 product direction update:** the next product phase prioritizes **operator clarity and automation readiness** over further internal cleanup. The app must make it obvious **where each batch / lot is in the process**, **what physical state it is in** (weight, remaining weight, potency, clean/dirty, cost, testing state), and **which exact source lot** feeds each downstream run allocation. The flagship UX surfaces for this phase are:
- a richer **Batch Journey** rooted in `Purchase -> PurchaseLot -> RunInput allocation -> Run -> outputs`
- a **Slack imports inbox** organized by confidence / manual resolution need
- **lot identity** at creation time via **tracking ID + barcode + QR**
- readiness for future **connected scale** capture as a structured input channel

Current implementation note: the active modular extraction surface now includes dashboard, field intake, runs, purchases, biomass, costs, inventory, batch edit, suppliers/photos, purchase import, strains, settings, Slack integration, and startup bootstrap modules. This remains an engineering delivery change only; product behavior and operator-facing workflow are intended to stay the same.

**Release note â€” April 2026:** the current upgrade train includes a substantial internal modularization of `app.py` into package-backed route and bootstrap modules. This is an **engineering delivery change only**; product behavior, URLs, approvals, list workflows, Slack ingest behavior, and operator-facing page structure are intended to remain unchanged.

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
- **Allocation integrity**: every reactor input must resolve to a **specific source lot**; the product must never silently guess between multiple viable lots from the same supplier.
- **Physical-state visibility**: operators must be able to see **weight, remaining weight, potency, testing state, clean/dirty, and cost** anywhere material is reviewed or matched.
- **Automation readiness**: lots must be ready for future **barcode / QR scanning** and **connected scale** workflows without changing the core data model later.
- **Internal data access**: each site deployment must expose a stable, read-only internal API so trusted internal consumers, future site rollups, and future read-only MCP / AI tools can access detailed operational data without querying the database directly.
- **Accurate $/g**: include biomass $/lb inputs and allocated operational costs.
- **Configurable allocation**: choose how total run dollars are distributed between THCA and HTE.
- **Data quality controls**: clearly flag runs missing biomass pricing and optionally exclude them from analytics.
- **Auditability**: record critical create/update/delete actions (including purchases created/updated indirectly via the biomass pipeline).

## Non-goals (for now)
- Full accounting/ERP integration
- Automated lab COAs ingestion (manual entry only)
- Multi-facility support
- External customer-facing API access
- **Department UIs (initial scope):** replacing Slack as the authoritative capture layer for weights/production logs (see **Operational input authority** below); full barcode / Wi‑Fi or Bluetooth scale integration (roadmap)

---

## Batch Journey Progress Tracker

### Problem to solve
Operators and managers can see each stage in separate screens today (Pipeline, Purchases, Inventory, Runs, Departments), but there is no **single visual timeline** for one batch from first declaration through downstream outcomes.

### Product intent
When a user opens a batch (purchase), they should be able to view a **graphic progress tracker** that answers:
- Where is this batch now?
- Which stages are complete vs pending vs skipped?
- What dates/owners/evidence are attached to each stage?
- What quantity is still active at each step?
- Which exact lots and allocations fed each downstream run?
- What is the physical/economic state of the material at each node?

### Scope (vNext target)
The tracker is a **single-batch journey view** anchored to `Purchase.id` / Batch ID and rendered as a horizontal or vertical stepper plus linked node/edge graph:
1. **Declared** (availability captured)
2. **Testing** (pre/post-delivery test status)
3. **Committed / Approved**
4. **Delivered / Received**
5. **On-hand inventory** (specific lots and remaining lbs)
6. **Allocation to extraction** (one or more explicit `RunInput` records from named lots)
7. **Extraction** (runs that consumed this batch’s lots)
8. **Post-processing** (HTE/THCA downstream states where applicable)
9. **Sales/Disposition** (placeholder step until sales module is expanded)

Each step shows:
- Status badge (`done`, `in_progress`, `blocked`, `not_started`, `not_applicable`)
- Timestamp(s)
- Responsible user (when available)
- Key metrics (lbs, g, potency, cost)
- Drill link to source record (purchase, lot, run, etc.)

Each **node** in the detailed journey should also expose a common material summary shape:
- Current stage / status
- Weight, allocated weight, remaining weight
- Potency / testing state
- Clean / dirty state
- Cost basis when available
- Exceptions / unresolved ambiguity

### Rules / behavior
- Journey is **derived** from existing source-of-truth records; no duplicate stage table required for v1.
- A step can be **partially complete** (e.g., only some lots consumed in runs).
- The journey must make the chain **explicit**: `Supplier -> Purchase -> PurchaseLot -> RunInput allocation -> Run -> output / downstream state`.
- A **run input** is an **allocation event**, not just a quantity field on a run. The product must always be able to show which lot(s) fed the run and how much each contributed.
- If a run is fed by multiple lots, the journey must show **split allocations**.
- Soft-deleted records are excluded from default display but can be shown in an “include archived” mode for audit/admin.
- Approval gates remain authoritative: unapproved batches can show delivered/ordered milestones, but on-hand consumption and run usage remain blocked by existing rules.

### Acceptance criteria (v1)
- From Purchases list and Purchase detail/edit, user can open **View Journey** for that batch.
- Journey reflects current state within the same request cycle as underlying records (no stale cache requirement in v1).
- Every visible step has at least one traceable source link.
- If a phase has no data yet, UI explicitly shows “Not started” rather than empty space.
- Export (JSON/CSV) of journey events is available for audit/debug.

### Acceptance criteria (next phase)
- Journey shows **lot-level** remaining inventory and total allocated quantity, not only purchase-level totals.
- Journey shows **explicit edges** from `PurchaseLot` to `Run` via `RunInput` allocation records.
- From any run node, an operator can trace **backward** to the exact source lot(s); from any lot node, an operator can trace **forward** to all consuming runs.
- Journey nodes visibly surface **weight**, **potency**, **clean/dirty**, **testing state**, and **cost** when available.
- Any unresolved ambiguity (for example, a Slack message that names a supplier but not a lot) is visible as an **exception state**, not hidden.

### Implementation status (current)
- Delivered endpoints:
  - `GET /purchases/<purchase_id>/journey` (timeline page)
  - `GET /api/purchases/<purchase_id>/journey` (JSON payload)
  - `GET /purchases/<purchase_id>/journey/export?format=json|csv` (download export)
- `include_archived=1` is super-admin only for archived purchase visibility/export.
- Export format validation is explicit: unsupported `format` returns `400` with a machine-readable payload listing supported formats (`csv`, `json`), rather than silently falling back.
- Current journey payload and page already expose lot-level detail:
  - `lots` with tracking id, original / allocated / remaining weight, potency, testing state, and clean/dirty state
  - `allocations` representing explicit `RunInput` edges from lot to run
  - `runs` as separate downstream nodes
- The current HTML journey page already shows dedicated **Inventory Lots** and **Run Allocations** sections, so operators can inspect lot-to-run traceability before the future graph UI ships.

---

## Users & Permissions

### Base roles (existing)
- **Super Admin** — Full access; can manage users; Settings + Maintenance (e.g. recalculate all run costs).
- **User** — Can create/edit operational data (runs, purchases, biomass pipeline, costs), subject to capabilities below.
- **Viewer** — Read-only access; cannot approve purchases or persist operational edits.

### Capabilities (preferred model)
Authorization should use **named capabilities per user** (flags or equivalent), not a separate database “role enum” for every combination of job duties. Examples: **`can_approve_purchase`**, existing **Slack Importer** (`is_slack_importer` / `can_slack_import`), and future narrow grants as needed. **Super-Buyer**, **COO**, and **Super Admin** are **business labels**; provisioning may default certain flags for those accounts, but enforcement is always via capabilities.

### Purchase approval
- **Eligible approvers:** any account with **`can_approve_purchase`** (`User.is_super_admin` **or** **`is_purchase_approver`**). The business requires that **Super-Buyer**, **COO**, and **Super Admin** users be able to approve; it is **any one** of these (or any user with the flag)—**not** a multi-signature workflow.
- **Effect on approve:** sets **`purchase_approved_at`** / **`purchase_approved_by_user_id`**. Until then, the product **must not** treat the batch as usable for **on-hand inventory**, **run consumption**, or **dashboard on-hand / days-of-supply** (lot pickers and inventory queries require approval). **Edit Purchase** cannot move into on-hand statuses (**delivered**, **in_testing**, **available**, **processing**) until approved. **Biomass Pipeline:** moving stage to **Committed** (purchase **`status = committed`**) requires the same approver capability and **stamps** approval as part of that transition.
- **Operator UX:** eligible approvers should be able to approve directly from list views, not only from the edit form. The shipped workflow now exposes inline **Approve** actions on unapproved rows in **Purchases** and **Biomass Pipeline**, returning the user to the same filtered list after approval.
- **Commitments / finance:** weekly **commitments** dollar rollups use **`committed`/`delivered`** purchases, weighted toward rows with **`purchase_approved_at`** in the calendar week (with a legacy fallback when approval is null—see **`ENGINEERING.md`**).
- **Audit:** log **who** approved and **when**; approval is **idempotent** (subsequent approve actions are no-ops or blocked with a clear message).

### Operational input authority
- **Today:** **Slack** is the **authoritative** channel for operational posts (e.g. intake weights, photos, production variables) that operators treat as ground truth; the app **ingests, links, or mirrors** that information per existing Slack integration behavior.
- **Future:** **barcode / QR** and **connected scales** become additional structured input channels. Slack remains authoritative until those channels are explicitly turned on for a workflow, but the model must be ready now for:
  - scan-based lot identification
  - scan-based allocation / movement confirmation
  - device-captured weights with audit trail
  - mixed manual + device-assisted workflows

### Internal API & site-local deployment
- Each facility deployment is its own **site-local system of record**.
- Sites are intentionally **separate deployments first**, with the option to be **rolled up / aggregated later** through a separate reporting or integration layer.
- The product should expose a **read-only internal API** for trusted internal consumers, future aggregation services, and future read-only MCP / AI tooling.
- This internal API is **not** a customer-facing public API.
- `/api/v1/*` uses **bearer-token auth** via internal API clients rather than web-login redirects.
- Phase 1 of the internal API is **read-only**; future write access may be added later only after the read contract and audit requirements are stable.
- AI / MCP access should also remain **read-only initially**.
- **Suppliers** are **site-local first**; any cross-site supplier consolidation belongs in a later aggregation layer rather than the current operational app.
- **Costs** are **site-scoped** and remain local to each site deployment.
- Every internal API response should identify the site clearly enough for later aggregation.

### Internal API phase 1 (current)
The current first slice of the internal API includes:
- `GET /api/v1/site`
- `GET /api/v1/capabilities`
- `GET /api/v1/sync/manifest`
- `GET /api/v1/aggregation/sites`
- `GET /api/v1/aggregation/sites/<site_id>`
- `GET /api/v1/aggregation/summary`
- `GET /api/v1/aggregation/suppliers`
- `GET /api/v1/aggregation/strains`
- `GET /api/v1/search`
- `GET /api/v1/tools/inventory-snapshot`
- `GET /api/v1/tools/open-lots`
- `GET /api/v1/tools/journey-resolve`
- `GET /api/v1/tools/reconciliation-overview`
- `GET /api/v1/summary/dashboard`
- `GET /api/v1/departments`
- `GET /api/v1/departments/<slug>`
- `GET /api/v1/purchases`
- `GET /api/v1/purchases/<purchase_id>`
- `GET /api/v1/purchases/<purchase_id>/journey`
- `GET /api/v1/lots`
- `GET /api/v1/lots/<lot_id>`
- `GET /api/v1/lots/<lot_id>/journey`
- `GET /api/v1/runs`
- `GET /api/v1/runs/<run_id>`
- `GET /api/v1/runs/<run_id>/journey`
- `GET /api/v1/suppliers`
- `GET /api/v1/suppliers/<supplier_id>`
- `GET /api/v1/strains`
- `GET /api/v1/slack-imports`
- `GET /api/v1/slack-imports/<msg_id>`
- `GET /api/v1/exceptions`
- `GET /api/v1/summary/inventory`
- `GET /api/v1/summary/slack-imports`
- `GET /api/v1/summary/exceptions`
- `GET /api/v1/inventory/on-hand`

These endpoints:
- are token-authenticated
- are read-only
- return JSON envelopes with site metadata
- are intended for internal consumers only
- expose a machine-readable discovery surface so internal tools and future MCP clients can discover scopes and supported endpoints
- expose a site sync manifest so future aggregation services can identify the site, dataset counts, and basic freshness markers before pulling deeper data
- expose a cached rollup layer for registered remote sites so one site can summarize other site deployments without live fan-out on every read
- expose cached cross-site supplier and strain comparison reads so internal analytics and future AI tooling can compare site performance without direct access to every remote instance
- expose a cross-entity search / lookup surface so internal tools and future MCP clients can find suppliers, purchases, lots, and runs without hard-coding separate list queries first
- expose semantic, tool-oriented read endpoints so future MCP / AI clients can ask for inventory snapshots, open-lot resolution, canonical journeys, and reconciliation posture without stitching together multiple low-level API calls themselves
- now include summary-oriented read models for inventory posture, Slack-import triage posture, and reconciliation posture
- now include supplier- and strain-performance analytics reads for internal reporting and future MCP / AI use
- now include a dashboard-style site operating summary for internal reporting and future MCP / AI use
- now include department-focused summary reads for operations, purchasing, and quality views

### Internal API future direction
Future phases should expand the internal API with:
- higher-value derived reconciliation and analytics reads beyond the current Slack-import and exception surfaces

Longer term, the architecture should support:
- a separate rollup / aggregation service that pulls from multiple site APIs
- site-local registration and batch pulling of trusted remote site caches as the bridge between isolated deployments and a fuller future rollup service
- read-only MCP / AI access through the same internal API or domain-tool layer
- eventual controlled write access with explicit scopes and audit logging

---

## Core Concepts & Entities
### Suppliers (farms)
Represents the source farm. Suppliers can have many **Purchases** (including pipeline-stage purchases).

### Biomass Pipeline (unified `Purchase` rows)
**Biomass Pipeline** is not a separate business record type in the UI: it is a **filtered view of `Purchase`** rows whose **`status`** is in the pipeline set (**`declared`**, **`in_testing`**, **`committed`**, **`delivered`**, **`cancelled`**) plus normal purchase lifecycle statuses where relevant. Early pipeline data lives on the same columns as procurement/receiving:

- **`availability_date`**, **`declared_weight_lbs`**, **`declared_price_per_lb`**
- **Testing:** **`testing_timing`**, **`testing_status`**, **`testing_date`**, tested potency on the purchase / lots as entered
- **Field photos:** **`field_photo_paths_json`**
- **Strain** for simple pipeline rows is carried on **`PurchaseLot`** (typically one lot per pipeline purchase)

**Stage labels vs storage:** the UI “Testing” stage maps to purchase status **`in_testing`**.

**Legacy `BiomassAvailability`:** the **`biomass_availabilities`** table may remain on disk for backward compatibility; startup migration **`_migrate_biomass_to_purchase()`** copies forward into **`purchases`**. New operator work uses **Purchases** / **Biomass Pipeline** screens only.

### Field intake submissions
Field users can submit data through secure links for:
- Biomass availability declarations
- Purchase requests (including multiple lot lines)

Both field forms support optional photo uploads:
- Allowed formats: `.jpg`, `.jpeg`, `.png`, `.webp`, `.heic`, `.heif`
- Max file size: 50 MB per photo (field intake); 50 MB per file for supplier lab/attachment uploads, photo library uploads, and purchase supporting documents
- Max **count** per photo bucket (default 30 per category on purchase intake; same for the single biomass-availability bucket): overridable via `FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET`. UI uses **one native file input per photo** (required for iOS / many WebViews); **Add photo** adds a row; **Take or choose photo** opens the picker; **Remove** drops the row before submit.
- Files are stored under `static/uploads/field/` and referenced by relative path in JSON fields

Field purchase intake requires/accepts:
- Purchase date, expected delivery date, harvest date
- Storage note and license information text
- Queue placement (`aggregate`, `indoor`, `outdoor`)
- Testing/COA status text
- Separate image categories for supplier/license docs, biomass photos, and testing/COA photos
- Lot line strain and lot line weight are optional in field intake (at least one lot row can still be submitted for context)

### Purchases (batch-level financial/receiving record)
Represents procurement from first touch through delivery (and optional pipeline-only phases). Contains:
- Supplier, purchase/delivery dates
- **Status** — full lifecycle including pipeline values **`declared`**, **`in_testing`**, **`committed`**, plus **`ordered`**, **`in_transit`**, **`delivered`**, **`available`**, **`processing`**, **`complete`**, **`cancelled`**, etc.
- **Approval** — **`purchase_approved_at`**, **`purchase_approved_by_user_id`** (gate for on-hand treatment and runs)
- Weights, potency (stated/tested), $/lb
- Total cost + true-up values
- **Batch ID** (unique, human-readable)

### PurchaseLots (inventory lots)
Represents strains within a purchase with:
- Weight and remaining weight
- Potency %
- Location / milled flag

This is the **physical inventory bucket** that can actually be consumed by extraction. A purchase may create one or more lots, and lots may be split or created manually after approval as operations require.

Each lot must eventually support:
- A permanent **tracking identity** (`tracking_id`)
- **Barcode** payload
- **QR** payload
- Printable label metadata
- Physical descriptors shown consistently in the UI:
  - original weight
  - allocated weight
  - remaining weight
  - potency
  - testing state
  - clean / dirty
  - cost basis where available

### Run inputs as allocation records
`RunInput` is the canonical **inventory allocation** record between a `PurchaseLot` and a `Run`.

Product rules:
- A reactor run must consume from one or more **specific lots**, never from a supplier name alone.
- If multiple lots from the same supplier are viable, the system must either:
  - auto-select only when confidence is high and there is one clearly correct candidate, or
  - ask for confirmation, or
  - require manual lot selection / split allocation.
- The system must never silently guess between two open lots from the same supplier.
- Remaining lot quantity must always be derivable from explicit allocations.

### Canonical material descriptors
Every raw or finished material-facing UI should present both **process state** and **physical/economic state**.

At minimum, the product should be able to represent:
- Identity:
  - batch id
  - lot id
  - supplier
  - strain
  - linked Slack / scan / scale evidence
- Process state:
  - current stage
  - previous stages
  - next required action
  - exception / blocked state
- Physical state:
  - gross weight
  - allocated weight
  - remaining weight
  - potency
  - testing status / date
  - clean / dirty
- Economic state:
  - price per lb
  - total cost
  - remaining cost basis

### Runs (extraction)
Represents an extraction run with:
- Inputs (RunInput rows pointing to lots and weights)
- Wet/dry outputs for THCA and HTE
- Yield calculations
- Cost calculations (combined and product-specific)
- **HTE post-separation workflow (optional per run):** after dry HTE is separated from THCA, operators may record a **pipeline stage** (e.g. awaiting outside lab test; lab result **clean** for menu/sale vs **dirty** queued for terp stripping on Prescott / “Terp Tubes”; **stripped** with terpene and retail distillate mass accounted). **Lab/COA evidence** may be attached as files on the run (images or PDFs). This is distinct from **supplier-level** historical lab tests in the Suppliers module.

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
- User can move a record to stage **Testing** (purchase **`in_testing`**) and record testing metadata **on the same `Purchase` row**—no second record is created.

#### Commitment / delivery
Fields (still the same purchase row):
- Committed On → **`purchase_date`**
- Delivery Date → **`delivery_date`**
- Committed Weight → **`stated_weight_lbs`** (falls back to declared weight when blank)
- Committed $/lb → **`price_per_lb`** (falls back to declared $/lb)

Rules:
- **Delivered** is rejected unless the batch was **Committed** first (or already delivered).
- **Committed** and stepping **out of** **Committed** / **Delivered** require **`can_approve_purchase`**; entering **Committed** stamps **`purchase_approved_at`** and emits **`purchase_approval`** audit details (`source: biomass_pipeline`).
- **Batch ID** is generated when missing (same rules as other purchases).

Audit requirements:
- Create/update/delete from **Biomass Pipeline** forms log **`purchase`** with **`source: biomass_pipeline`** in details JSON.

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

#### Purchase ↔ Biomass Pipeline (single row)
There is **no** separate biomass row to keep in sync: **Biomass Pipeline** edits **are** purchase edits. Batch list **Biomass Pipeline** applies **`Purchase.status`** and testing fields directly (`apply_batch_biomass`).

#### Spreadsheet import (purchases)
- **Access:** Same users who can create/edit purchases (`can_edit_purchases`).
- **Inputs:** `.csv`, `.xlsx`, `.xlsm`; first recognizable header row within the first ~50 lines; required mapped columns include **supplier** (Vendor/Farm/etc.) and **purchase date** (or acceptable fallbacks per product rules) and **stated/invoice weight** (or actual weight as fallback when invoice weight is blank).
- **Flow:** Upload → parse → **preview** (errors per row) → user selects rows to import → commit creates purchases with standard side effects (batch ID, lots, inventory maintenance, budget checks, audit). Rows are created **without** **`purchase_approved_at`**; any spreadsheet **status** that would imply on-hand inventory is **coerced to a non-on-hand status** (e.g. **ordered**) so operators must **Approve** and set status explicitly.
- **Acceptance criteria:**
  - Unreadable files or missing required columns produce a clear error before commit.
  - Rows with validation errors are not importable until fixed in the source file or excluded from selection.
  - Commit respects **unique Batch ID** and **weekly biomass purchase limits** like manual save.

#### Batch edit from list (purchases)
- **Access:** `can_edit_purchases`.
- **Behavior:** User selects ≥2 purchases on the **current list page**; batch form may set **status**, **delivery date** (optional clear), **queue placement** (or clear), **append notes**; only filled controls apply.
- **Acceptance criteria:**
  - Each updated purchase runs **inventory lot maintenance** and **weekly budget enforcement**; failure rolls back the **entire** batch operation with a clear message.

---

### 3) Inventory workflow
- Inventory shows:
  - On-hand lots (from purchase statuses **`delivered`**, **`in_testing`**, **`available`**, **`processing`** **and** **`purchase_approved_at` set**), using each lot’s **remaining** weight
  - In-transit purchases (statuses **committed**, **ordered**, **in_transit**), using **stated** weight (approval not required to appear here)
  - Summary tiles:
    - **On Hand**: sum of remaining lbs on on-hand lots
    - **In Transit**: sum of stated lbs on in-transit purchases
    - **Total**: on hand + in transit (combined lbs position)
    - **Days of Supply**: **on-hand lbs only** ÷ **Daily Throughput Target** (`SystemSetting` `daily_throughput_target`, default 500 lbs/day). In-transit weight does **not** extend days of supply until it arrives and appears on hand.
  - Optional **supplier** filter applies to both on-hand lots and in-transit purchases (all four summaries use the same supplier scope).
  - Optional **strain-contains** filter applies **only** to on-hand lots (lot `strain_name`). In-transit purchases are not strain-filtered, so **In Transit** and the **Total** tile still include all matching supplier in-transit weight when a strain filter is set; **On Hand** and **Days of Supply** reflect the strain slice only.

Acceptance criteria:
- When a run uses lot weights, `remaining_weight_lbs` decrements.
- Deleting a run restores decremented lot weights.

#### Batch edit (inventory lots and in-transit purchases)
- **On-hand table:** Checkboxes identify **PurchaseLot** IDs; batch form may update strain name, location, milled flag, potency, append notes (`can_edit_purchases`).
- **In-transit table:** Checkboxes identify **Purchase** IDs; batch behavior matches **Purchases** batch edit (same permission and rules).
- **Acceptance criteria:** Selection is limited to **visible page** of the table; toolbar actions are disabled until ≥2 rows are checked.

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

#### Batch edit (runs)
- **Access:** `can_edit` (same as single run edit).
- **Optional batch fields:** Run type, HTE pipeline stage (including clear), rollover and decarb sample flags, biomass load source (with explicit “apply” checkbox), append notes.
- **Acceptance criteria:** Changing a run recalculates **yields** and **cost per gram** where applicable; empty / “no change” controls do not overwrite existing values.

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

#### Batch edit (costs)
- **Access:** `can_edit`.
- **Optional fields:** Cost type (solvent/personnel/overhead), append notes.
- **Acceptance criteria:** Only non-empty / selected changes are applied to all selected entries.

---

### 6) Biomass pipeline — batch edit
- **Access:** `can_edit`.
- **Optional fields:** Stage, testing status, testing timing, append notes.
- **Acceptance criteria:** Same validation expectations as single-record edit for the fields touched.

### 7) Suppliers — batch edit
- **Access:** `can_edit`.
- **Optional fields:** Set all selected suppliers **active** or **inactive**, and/or append to **notes**.
- **Acceptance criteria:** At least one action (status change or notes append) is required to submit.

### 8) Strain performance — batch rename
- **Access:** `can_edit`.
- **Behavior:** User selects ≥2 aggregate rows; supplies a **new strain name**; system updates **all non-deleted purchase lots** matching each **strain + supplier** pair.
- **Acceptance criteria:** Audit log records the bulk rename; operators understand this is a **data migration** on lot strain labels, not a separate master “strain” entity.

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

**Batch operations:** Successful **batch list edits** log **`update`** with synthetic entity types such as `run_batch`, `purchase_batch`, `biomass_batch`, `supplier_batch`, `cost_batch`, `inventory_lot_batch`, or `strain_rename`, using a generated `entity_id` and **details** summarizing the count affected. Individual row IDs may be omitted to avoid log spam; critical per-record compliance needs should rely on single-record edits or future enhanced batch logging if required.

Critical requirements:
- Purchase create/update/delete actions must be logged (including saves originating from **Biomass Pipeline** forms with **`source: biomass_pipeline`** in JSON details).
- Purchase **approve** action (`approve` / `purchase_approval`) must be logged with approver identity where applicable.
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
- **Channel history sync (admin tooling):** Super Admin configures up to **six** Slack channels (by `#name` or channel ID) under **Slack Integration → Channel history sync**, then runs **Maintenance → Sync Slack channel history**. The sync uses Slack `conversations.history`, dedupes messages by **channel ID + message `ts`**, and stores rows for review (yield/production-style parsing hints); sync **by itself** does **not** auto-create Run records. Operators with **Slack Importer** (or Super Admin) use **Slack imports** + **Create run from Slack** to open the Run form prefilled from mappings; Runs are created only when the Run form is **saved** (Phase 2). **First sync** for each configured channel uses a configurable rolling window (**Days back**). **Subsequent syncs** use a **per-channel cursor** (last ingested message timestamp / watermark) so each channel incrementally fetches only newer messages. Editing a channel hint clears that slot’s resolved ID and cursor. New installs seed sync slot 0 from **Default Channel** when no sync rows exist yet.
- **Inbound HTTP endpoints (no user session):** requests must be verified with Slack’s signing secret (HMAC).
  - **Slash commands:** `POST /api/slack/command`
  - **Interactivity:** `POST /api/slack/interactivity`
  - **Events API:** `POST /api/slack/events` — must respond to `url_verification` with JSON `{ "challenge": "<value>" }`; must acknowledge `event_callback` within Slack’s timeout (hook for future channel/message automation).
- **Production:** Event Subscriptions Request URL must use **HTTPS** on the public hostname nginx serves.

### Proposed: Field mapping control panel (phased roadmap)

Super Admins need to **configure** how parsed Slack fields (`derived_json` / `message_kind`) relate to operational entities without code changes. The following phases are **proposed**; scope and sequencing may be adjusted after Phase 1 validation.

#### Problem statement

- Synced Slack messages are stored in `slack_ingested_messages` with **classifier + regex-derived hints** (`yield_report`, `production_log`, `unknown`). **Automatic** sync/ingest does **not** create or update operational rows. **Phase 2** adds an explicit **manual apply** path: prefilled **Run** form + save, with Run **backlinks** to `channel_id` + `message_ts`. Other entities (Purchases, Biomass, etc.) remain out of scope for apply until later phases.
- Operations need a **dashboard / control panel** to define **mappings** (source Slack keys → target entity + field + optional transform) and to revisit those mappings as templates and business rules evolve.

#### Guiding principles

- **Configurable**: mappings editable in-app (Super Admin); persisted (e.g. JSON in `SystemSetting` and/or normalized tables as complexity grows).
- **Safe by default**: Phase 1 is **preview-only**; no silent bulk writes to core operational tables.
- **Idempotent**: later phases must avoid duplicate application of the same Slack message (`channel_id` + `message_ts`) unless explicitly re-run with audit.
- **Auditable**: any apply action logs **who**, **when**, **which import row**, and **what** changed (AuditLog or dedicated apply log).

---

#### Phase 1 — Mapping catalog + preview (no writes to Runs et al.)

**Goal:** Prove value and correctness before automating data entry.

**Requirements**

1. **Mapping configuration UI** (Super Admin), minimal first slice:
   - Support rules scoped by **`message_kind`** (`yield_report`, `production_log`, and optionally `unknown` / catch-all).
   - Each rule: **source key** (from `derived_json`, e.g. `strain`, `wet_thca_g`, `bio_lbs`, `reactor`) → **target descriptor**: entity name (initial focus **Run** only) + **logical field** (align with Run model / form fields operators care about).
   - Optional **transform** (v1): passthrough, numeric scale, prefix/suffix string, map `message_ts` to a suggested **run date** (display only in preview).
   - Ordered list; later rules may override earlier (document resolution order).

2. **Preview on Slack imports (or linked screen):**
   - For a selected `SlackIngestedMessage`, compute and display **“would-be”** field values from active mappings + `derived_json` + `message_ts`.
   - Show **unmapped** source keys and **unfilled** required Run fields so gaps are obvious.
   - **No** `INSERT`/`UPDATE` to `runs`, `purchases`, `biomass_availabilities`, etc.

**Out of scope for Phase 1**

- Entity resolution (matching Slack `source` / `strain` text to Supplier ID or PurchaseLot ID).
- Automatic apply, scheduling, Photo Library file ingest from Slack uploads.
- Full coverage of Purchases, Costs, Biomass, Inventory, Strains, Suppliers (beyond what is needed to **describe** a Run preview).

**Success criteria**

- Super Admin can add/edit/disable mapping rules without a deploy.
- Preview output is **repeatable** and matches documented rule order.
- No production data mutation from Phase 1 alone.

**Implementation (shipped):** Super Admin → **Settings → Slack → field mappings** (`/settings/slack-run-mappings`): JSON rule list stored as `SystemSetting` `slack_run_field_mappings` (seeded on first `init_db`). Each rule may set optional **`destination`** (`run`, `biomass`, `purchase`, `inventory`, `photo_library`, `supplier`, `strain`, `cost`); omitting it means **`run`**. **Run** targets use the known Run preview field allowlist; other destinations store a **snake_case target label** until that module gains a preview/apply workflow. **Slack imports** adds **Run preview** per row (`/settings/slack-imports/<id>/preview`) showing mapped Run fields only, unmapped derived keys (after any destination consumes a source), and gaps vs recommended `run_date` / `reactor_number` / `bio_in_reactor_lbs`.

---

#### Phase 2 — Manual apply + linkage + idempotency

**Goal:** Let trusted users **promote** a reviewed import row into operational records with explicit consent.

**Product decisions (locked for v1 implementation)**

1. **Apply path — prefilled Run form (simple workflow)**  
   - From Slack import / preview, the user opens **New run** with fields **prefilled** from the Run preview payload. Nothing is persisted until they **Save** the Run form (adjust later if this feels too onerous).

2. **Second apply — warn, then allow**  
   - If a Slack message was already used to start or complete an apply path, show a **clear warning** and require **explicit confirmation** before prefilling again. Operators accept that mistaken duplicates may be **deleted manually** in edge cases.

3. **Permission — Slack Importer**  
   - New capability: users who may use Slack apply / importer audit flows. **`super_admin` implicitly includes this capability.**  
   - Additional users may be granted **Slack Importer** via a dedicated flag (or equivalent) in Settings / user admin without making them full Super Admin.

4. **Slack imports — audit and triage**  
   - Operators need **two orthogonal views** on each imported message: whether anything was **saved from Slack into operations**, and whether **mapping rules** fully used the parsed payload before anyone promotes a Run.

**Slack import triage — two dimensions (both shown on list / filters where practical)**

| Dimension | Labels | Definition |
|-----------|--------|------------|
| **Promotion status** | **Not promoted** (aka *unapplied*) / **Linked to Run** | **Not promoted:** no **saved Run** exists whose **Slack backlink** matches this row’s `channel_id` + `message_ts` (Phase 2 adds the backlink on save). **Linked to Run:** at least one such Run exists. This answers: “Has anything been committed from this message?” |
| **Mapping coverage (Run preview)** | **Full** / **Partial** / **None** | **Heuristic** from the same Run-only preview as Phase 1 (`_preview_slack_to_run_fields`). **None:** no Run-shaped `filled` fields after rules (or no usable `derived_json`). **Partial:** at least one field in `filled` **and** (`unmapped_keys` non-empty **or** `missing_recommended` non-empty). **Full:** at least one field in `filled`, **and** `unmapped_keys` empty, **and** `missing_recommended` empty. Answers: “Are rules leaving gaps before apply?” — *not* whether a Run was saved. |

**Examples**

- **Not promoted + Partial:** Common; improve rules or prefill and save a Run.  
- **Linked to Run + Partial:** Run was saved from Slack but rules still didn’t use every derived field (or recommended trio wasn’t in the preview); may be fine if the user fixed fields on the form.  
- **Not promoted + Full:** Ready to promote; preview used all tracked derived keys and recommended Run fields.  
- **Not promoted + None:** Parsing or mapping gap; tune rules, template, or `message_kind`.

**UI (Phase 2)**

- **Filters:** **date range**, **channel(s)**, and optionally filter by **promotion status** and/or **mapping coverage**.  
- **Columns or badges** for both dimensions so teams can find “falling through the cracks” messages and batch review.

**Requirements**

1. **Apply actions** (from Slack import row or preview):
   - **Open Run form prefilled** from preview payload (query params, short-lived session, or POST redirect—implementation detail).
   - Phase 2 **Run apply only** uses rules with `destination` **`run`** (or omitted); other destinations remain preview/storage until their modules ship.
   - On **successful Run save**, store **backlink** on the Run: e.g. `slack_channel_id`, `slack_message_ts`, `slack_import_applied_at` (and optionally `slack_ingested_message_id`) so list views can mark **applied vs not**.

2. **Idempotency:**
   - On second (or subsequent) **apply** for the same `channel_id` + `message_ts`, **warn** and require **confirmation** before opening prefilled form again. Log confirmatory applies in **Audit** where applicable.

3. **Audit:**
   - `AuditLog` (or equivalent) when a Run is **saved** from a Slack-sourced prefilled flow (and when a duplicate apply is confirmed): user, import row id / Slack ids, run id, summary JSON.

4. **Slack imports list (Phase 2):**
   - Filters: **date range**, **channel(s)**, **promotion status** (Not promoted / Linked to Run), **mapping coverage** (Full / Partial / None) where technically feasible.  
   - **Promotion** from backlink lookup on `Run` after save. **Coverage** from computing preview once per row (cache in session or materialized column only if performance requires—implementation detail).  
   - Help text in UI: coverage is **rule/preview quality**, not legal proof; operators may still save a Run with different values than preview.

**Out of scope for Phase 2 (unless trivial)**

- Bulk apply hundreds of rows in one click without review.
- Full Biomass/Purchase/Inventory creation from one Slack message (unless a narrow, specified workflow is added).

**Success criteria**

- Operators can take a **single** import row to a **saved** Run via the normal form, with traceability.  
- Slack imports supports finding **Not promoted** rows and rows with **Partial** vs **Full** mapping coverage, with **date** and **channel** filters.  
- Duplicate apply is **warned**, not silently allowed.

**Implementation (shipped):** **`User.is_slack_importer`** (Settings toggle + create-user checkbox; Super Admin always has importer capability via **`User.can_slack_import`**). Sidebar **Slack imports** for eligible users. **`GET /settings/slack-imports`** with filters (Slack message date, channel(s), promotion **not linked / linked**, coverage **full / partial / none**). **`GET .../preview`** and **`GET .../apply-run`** (`confirm=1` after duplicate interstitial). Session key stores prefilled Run fields; **`GET /runs/new`** hydrates the form; hidden inputs post Slack ids + duplicate flag; **`_save_run`** sets **`Run.slack_channel_id`**, **`slack_message_ts`**, **`slack_import_applied_at`** on new saves; audit **`create`/`run`** with JSON details (and **`slack_duplicate_apply_confirm`** when confirmed). SQLite schema patched in **`_ensure_sqlite_schema`**. Mapping editor remains Super Admin only (`/settings/slack-run-mappings`).

**Implementation update (April 2026):**
- Slack preview now surfaces ranked candidate lots for run-style messages, including tracking IDs and remaining pounds.
- Operators can assign one lot or split the run weight across multiple lots directly on the preview page before opening the Run form.
- The selected split is preserved into the Run prefill session and rendered as source-lot rows on **New Run**.
- The Run form now shows a live allocation summary and projected remaining lot balances; save still fails server-side if selected lot allocations do not equal `bio_in_reactor_lbs`.

---

#### Phase 3 — Resolution, breadth, optional automation

**Goal:** Reduce manual matching work and extend mapping beyond Runs where justified.

**Requirements** (prioritize by business need)

1. **Entity resolution strategies** (configurable per mapping or global defaults):
   - Match Slack `source` / supplier-like strings to **Supplier** (exact, fuzzy, manual pick list in UI).
   - Match `strain` to **Strain** / **PurchaseLot** context where applicable.
   - Resolve Slack biomass usage against **specific candidate lots**, not only suppliers.
   - Clarify behavior when **no match**: block apply, create placeholder note, or require manual selection.

2. **Additional entity targets** (as separate mapping rules):
   - **Purchases** / **Biomass Pipeline** / **Inventory**-related notes or fields (many may be “append note” or “suggested follow-up” rather than strict column mapping).
   - **Costs**: conservative design—likely **suggestions** or notes unless product defines a clear Cost Entry shape from Slack.
   - **Photo Library**: only if Slack posts include **usable file URLs or file IDs** and legal/retention policies allow ingest; scope separately.

3. **Optional automation** (off by default):
   - Post-sync hook: “auto-preview queue” or “auto-create draft Run” for messages matching strict rules, with notification and rollback path.

4. **Confidence-based lot allocation workflow**
   - Inbox buckets should distinguish:
     - **Auto-ready**
     - **Needs confirmation**
     - **Needs manual match**
     - **Blocked / exception**
   - When Slack supplies enough context (supplier, strain, quantity, date, reactor), the system should rank candidate lots using:
     - supplier
     - strain
     - available quantity
     - received date / FIFO preference
     - clean / dirty state
     - testing state
   - If one candidate is clearly correct, the system may propose or auto-apply that lot allocation.
   - If multiple lots remain plausible, the UI must present a short guided list with lot id, received date, remaining lbs, strain, and state.
   - Split allocation across multiple lots must be supported when no single lot can satisfy the requested quantity.

**Success criteria**

- Measurable reduction in manual keystrokes vs Phase 2 for the same channel templates.
- Documented limits: which Slack templates are supported end-to-end vs preview-only.

---

#### Cross-cutting (all phases)

- **Security:** Super Admin for mapping config. **Slack imports UI + apply session:** `slack_importer_required` / **`can_slack_import`** (Super Admin or **`is_slack_importer`**). **Persisting a Run:** **`can_edit`** (**User** or **Super Admin**); Viewers with importer may open a read-only prefilled form until an editor saves.
- **Documentation:** USER_MANUAL + FAQ + ENGINEERING describe source keys (`_derive_slack_production_message`), rule schema, preview vs apply semantics, triage dimensions, and migrations for non-SQLite DBs.
- **Migration:** V1 mapping storage backward-compatible (default rules empty → preview shows raw `derived_json` only).

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

## Operational departments & shared data model

Departments are **views and workflows on the same canonical data** (suppliers, biomass pipeline, purchases, lots, runs, costs, inventory, lab/testing artifacts, finished goods). They are **not** separate silos with duplicated rules.

### Planning and capacity controls
Throughput, reactors, shifts, and related **planning knobs** already live in **Settings** and existing screens. Department-facing work should **reuse** those values and present **focused, output-oriented** summaries (KPIs, WIP, variance, obligations)—not rebuild parallel configuration UIs unless a gap is documented and accepted.

### Department surfaces (roadmap)
Each row is a **primary lens**; several departments share the same underlying entities.

| Department | Primary intent (illustrative) |
|------------|-------------------------------|
| **Finance** | Obligations, spend vs budget, cost visibility tied to commitments and purchases |
| **Biomass purchasing** | Sourcing, pipeline, potential → approval handoff, strain/quantity/quality signals |
| **Biomass intake** | Receipt, weigh-in variance vs promised, photos, strain receipt into inventory |
| **Biomass extraction** | Reactor loads, batch sizing, production variables tied to runs |
| **THCA processing** | Wet/dry THCA path, yields, disposition toward powder vs further refinement |
| **HTE processing** | Wet/dry HTE path, yields; department page links to runs and analytics (disposition detail is tracked on each **Run** via **HTE pipeline stage** when used) |
| **Liquid Diamonds processing** | THCA refinement path where product strategy routes material here |
| **Terpenes distillation** | After dirty lab results, queue vs stripped runs; **terpenes recovered (g)** and **retail distillate (g)** recorded on **Runs** at strip complete; department rollups |
| **Testing** | **Shipped v1:** department page rollups for **HTE lab pipeline** (runs with dry HTE) plus supplier-level lab history; **Runs** hold stage + COA attachments for post-extraction HTE testing |
| **Bulk sales** | **v1:** decrement **finished inventory** so on-hand balances stay correct; extended CRM/order management is out of scope until specified |

Acceptance criteria (department initiative):
- Navigation and layouts may differ by department; **numbers** for the same entity match across views.
- New department pages **respect** base role + capability gates (see **Users & Permissions**).
- **Testing** and **Terpenes distillation** pages surface **HTE lab pipeline** counts and links to **Runs** filtered by pipeline stage where implemented; **Run** is the system of record for stage, attachments, and terp/distillate grams.

### Canonical material flow (narrative)
1. Buyer sources **potential** biomass (field intake); weekly **volume** and **quality** goals align with plant throughput targets (e.g. lbs/day targets—configurable).
2. An approver promotes a line to **commitment** → **financial obligation**, logistics, and intake planning; testing may occur before or after commitment; **commercial terms** (e.g. pesticide repricing) must be representable in data.
3. Intake weighs and documents receipt; variance vs promised matters; media may flow through **Slack**; strains enter **inventory lots** with explicit remaining quantity.
4. Extraction consumes lots in **runs** (e.g. batch sizes, multiple reactors); each run input is an explicit **allocation from a named lot**; production variables captured per operational policy (**Slack**-authoritative today).
5. Outputs split into **wet THCA** and **wet HTE**, then dry weights; downstream: THCA → powder or Liquid Diamonds; HTE → outside lab test (staged/awaiting), then **clean** (menu/sale) or **dirty** (queued for Prescott terp strip) → **stripped** with terpenes and retail distillate grams recorded on the **Run**.
6. **Bulk sales** reduces finished inventory.

### Scanability and device-readiness
The product should be designed so physical handling can become machine-assisted without reworking the underlying material model.

#### Lot identity
- Every `PurchaseLot` should receive a permanent **tracking id** when created or authorized.
- Each lot should be able to generate:
  - a human-readable label
  - a **barcode** payload
  - a **QR** payload
- If a purchase produces multiple lots, each lot gets its own identifier and code.
- If a lot is split into new physical lots, each child lot gets its own identifier while preserving lineage.

#### Scale readiness
- The product should support both **manual** and **device-captured** weights.
- Future connected-scale support should store:
  - measured value
  - unit
  - timestamp
  - source mode (`manual`, `device`)
  - device identity
  - raw device payload
  - accepted / rejected state
- A scale reading should not silently mutate inventory by itself; it becomes evidence that is accepted into an intake, allocation, or output workflow.

---

## Potential pipeline records — Old Lots and soft deletion

Some **potential** purchase / pipeline lines will never be approved. The product must avoid an ever-growing “current” list while keeping history available for a bounded time.

### Aging model (single clock)
- **Anchor:** strictly **`created_at`** on the record (no sliding window based on `updated_at` or last activity unless the product explicitly changes—**default is `created_at` only**).
- **Parameter `N₁` (default: 10 days):** after **`created_at` + N₁**, the record leaves the default “current” potential list and appears only under **Old Lots** (or equivalent filter). It remains **active data**, not deleted.
- **Parameter `N₂` (default: 30 days):** after **`created_at` + N₂**, the record is **soft-deleted** (hidden from normal operational lists; recoverable only via admin/audit paths as implemented).
- **Total age:** **`N₂` is total age from `created_at`** toward soft delete (consistent with **Option A**: e.g. days 1–10 current, 11–29 Old Lots, day 30 soft delete for defaults).

### Settings validation
- **`N₁`** and **`N₂`** are **admin-configurable** system settings.
- **Validation:** **`N₂` ≥ `N₁`**. Invalid combinations must be rejected or clamped with a clear message at save time.

### Soft delete semantics
- Soft-deleted rows **remain in the database** with deletion metadata (`deleted_at` / `is_deleted` or equivalent) for audit and optional recovery; **hard purge** is a separate future policy if required.

### Relationship to approval
- **Approve** transitions a potential line to **commitment** and removes it from the “unapproved potential” problem by definition.
- **Aging** applies to lines that remain **unapproved** (and not otherwise terminal—e.g. cancelled—per existing pipeline rules).

---

## Future Improvements (Roadmap)
- **Lot allocation integrity + UX:** make `PurchaseLot` and `RunInput` the explicit `Purchase -> Lot -> Allocation -> Run -> Output` chain; add guided resolution when multiple same-supplier lots exist.
- **Batch Journey upgrade:** evolve the current purchase timeline into a true graph/timeline view with lot nodes, allocation edges, physical descriptors, and exception states.
- **Slack inbox redesign:** move from raw import review to confidence buckets, candidate-lot resolution, and simple manual allocation/split workflows.
- **Lot identity + labels:** generate `tracking_id`, barcode, and QR for each lot at purchase authorization / lot creation; support printable labels and future `/scan/lot/<tracking_id>` resolution.
- **Connected scale readiness:** add device-backed weight capture as a future structured input channel without changing the operator-facing material model. The current delivery already includes `ScaleDevice` and `WeightCapture` as the persistence layer for that later workflow.
- **Department UIs + governance:** **capabilities**, **purchase approval**, **Old Lots** + **soft delete**, and **`/dept` department hub + per-department pages** are implemented; continue to deepen per-department workflows (e.g. explicit “on stripper” stage, richer testing integrations) per **Operational departments & shared data model**.
- **Explicit close-out reasons** for potential lines (declined, lost, withdrawn) — optional enhancement beyond aging; supports analytics such as win rate by supplier without relying on soft-delete alone.
- **Slack → operational mapping:** phased roadmap under **Integrations — Slack** → **Proposed: Field mapping control panel (phased roadmap)** (Phase 1: mapping UI + preview; Phase 2: manual apply; Phase 3: resolution + breadth + optional automation).
- Consider consolidating Biomass Pipeline into Purchases by expanding purchase statuses to include pre-commitment stages (declared/testing), reducing duplication and sync logic.
- Add richer analytics screens (time series, variance by reactor/operator).
- Add COA upload + parsing, and stronger validation rules around potency/pricing.
- Add automated alerts for “missing $/lb” purchases linked to recent runs.
