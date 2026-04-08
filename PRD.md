# Gold Drop Production Tracker — Product Requirements Document (PRD)

## Summary
Gold Drop is an operations tracker for biomass intake → inventory → extraction runs → yield/cost analytics. It supports:
- A **Biomass Pipeline** (farm declarations through testing and commitment),
- **Purchases** with **unique batch identifiers**,
- **Inventory lots** consumed by **Runs**,
- **Operational cost entries** allocated into **$/g**,
- **Analytics controls** to exclude runs missing biomass pricing,
- **Audit logging** for traceability and compliance.

**Cross-cutting product direction (department views & governance):** the same underlying data should be exposed through **department-focused UIs** (finance, purchasing, intake, extraction, downstream processing, testing, sales) without duplicating business rules; **Slack** remains the **authoritative operational input channel** for floor capture until a future phase (e.g. barcodes, connected scales). **Purchase approval** uses **per-user capabilities**; a single approval promotes a potential purchase to a **system-wide commitment**, including the **weekly budget dashboard**. **Potential** pipeline lines that never close otherwise **age out** to **Old Lots** and then **soft-delete** on a configurable schedule anchored to **`created_at`**.

**Operator workflow — list views:** On primary **list screens** (Runs, Purchases, Biomass Pipeline, Costs, Inventory, Strains, Slack imports), **filters, date constraints, sort order, and related query state** are **persisted in the user’s server session** so operators can **navigate freely between app sections** and return **without re-entering** those choices—reducing repetitive work and supporting multi-step review (e.g. cross-checking Slack imports against Purchases). Persistence is **session-scoped** (not a permanent per-user database preference): sign-out, cookie loss, or timeout ends it. Each list exposes **Remove filters** (or equivalent) to restore the default unfiltered view. **Pagination** resets to **page 1** when filters are applied or certain primary facets change (e.g. Purchases status) so narrowed result sets are not shown as empty due to a stale page index.

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
- **Department UIs (initial scope):** replacing Slack as the authoritative capture layer for weights/production logs (see **Operational input authority** below); full barcode / Wi‑Fi or Bluetooth scale integration (roadmap)

---

## Users & Permissions

### Base roles (existing)
- **Super Admin** — Full access; can manage users; Settings + Maintenance (e.g. recalculate all run costs).
- **User** — Can create/edit operational data (runs, purchases, biomass pipeline, costs), subject to capabilities below.
- **Viewer** — Read-only access; cannot approve purchases or persist operational edits.

### Capabilities (preferred model)
Authorization should use **named capabilities per user** (flags or equivalent), not a separate database “role enum” for every combination of job duties. Examples: **`can_approve_purchase`**, existing **Slack Importer** (`is_slack_importer` / `can_slack_import`), and future narrow grants as needed. **Super-Buyer**, **COO**, and **Super Admin** are **business labels**; provisioning may default certain flags for those accounts, but enforcement is always via capabilities.

### Purchase approval
- **Eligible approvers:** any account with **`can_approve_purchase`**. The business requires that **Super-Buyer**, **COO**, and **Super Admin** users be able to approve; it is **any one** of these (or any user with the flag)—**not** a multi-signature workflow.
- **Effect on approve:** the potential purchase becomes a **commitment everywhere** the product represents commitments: pipeline linkage, purchase/financial obligation views, logistics and intake planning, and the **buyer weekly budget dashboard** (budget vs commitments vs actual purchases). All surfaces must derive from the **same** approval/commitment state.
- **Audit:** log **who** approved and **when**; approval is **idempotent** (subsequent approve actions are no-ops or blocked with a clear message).

### Operational input authority
- **Today:** **Slack** is the **authoritative** channel for operational posts (e.g. intake weights, photos, production variables) that operators treat as ground truth; the app **ingests, links, or mirrors** that information per existing Slack integration behavior.
- **Future:** optional **barcode** and **connected scales** as additional input channels; department web UIs prioritize **visibility**, **rollup**, and **downstream data entry** that does not conflict with Slack authority until product explicitly changes this.

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
  - On-hand lots (from arrived purchase statuses: delivered, in_testing, available, processing, complete), using each lot’s **remaining** weight
  - In-transit purchases (statuses committed, ordered, in_transit), using **stated** weight
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

---

#### Phase 3 — Resolution, breadth, optional automation

**Goal:** Reduce manual matching work and extend mapping beyond Runs where justified.

**Requirements** (prioritize by business need)

1. **Entity resolution strategies** (configurable per mapping or global defaults):
   - Match Slack `source` / supplier-like strings to **Supplier** (exact, fuzzy, manual pick list in UI).
   - Match `strain` to **Strain** / **PurchaseLot** context where applicable.
   - Clarify behavior when **no match**: block apply, create placeholder note, or require manual selection.

2. **Additional entity targets** (as separate mapping rules):
   - **Purchases** / **Biomass Pipeline** / **Inventory**-related notes or fields (many may be “append note” or “suggested follow-up” rather than strict column mapping).
   - **Costs**: conservative design—likely **suggestions** or notes unless product defines a clear Cost Entry shape from Slack.
   - **Photo Library**: only if Slack posts include **usable file URLs or file IDs** and legal/retention policies allow ingest; scope separately.

3. **Optional automation** (off by default):
   - Post-sync hook: “auto-preview queue” or “auto-create draft Run” for messages matching strict rules, with notification and rollback path.

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
3. Intake weighs and documents receipt; variance vs promised matters; media may flow through **Slack**; strains enter **inventory**.
4. Extraction consumes lots in **runs** (e.g. batch sizes, multiple reactors); production variables captured per operational policy (**Slack**-authoritative today).
5. Outputs split into **wet THCA** and **wet HTE**, then dry weights; downstream: THCA → powder or Liquid Diamonds; HTE → outside lab test (staged/awaiting), then **clean** (menu/sale) or **dirty** (queued for Prescott terp strip) → **stripped** with terpenes and retail distillate grams recorded on the **Run**.
6. **Bulk sales** reduces finished inventory.

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
- **Department UIs + governance:** **capabilities**, **purchase approval**, **Old Lots** + **soft delete**, and **`/dept` department hub + per-department pages** are implemented; continue to deepen per-department workflows (e.g. explicit “on stripper” stage, richer testing integrations) per **Operational departments & shared data model**.
- **Explicit close-out reasons** for potential lines (declined, lost, withdrawn) — optional enhancement beyond aging; supports analytics such as win rate by supplier without relying on soft-delete alone.
- **Slack → operational mapping:** phased roadmap under **Integrations — Slack** → **Proposed: Field mapping control panel (phased roadmap)** (Phase 1: mapping UI + preview; Phase 2: manual apply; Phase 3: resolution + breadth + optional automation).
- Consider consolidating Biomass Pipeline into Purchases by expanding purchase statuses to include pre-commitment stages (declared/testing), reducing duplication and sync logic.
- Add richer analytics screens (time series, variance by reactor/operator).
- Add COA upload + parsing, and stronger validation rules around potency/pricing.
- Add automated alerts for “missing $/lb” purchases linked to recent runs.

