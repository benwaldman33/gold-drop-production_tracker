# Gold Drop Production Tracker — User Manual

This guide explains how to use the Gold Drop web app day-to-day. It intentionally **does not include any usernames or passwords**. Ask your administrator for access.

---

## Getting started
- Open the site URL provided by your administrator.
- Sign in using the account you’ve been assigned.
- Your **role** controls what you can do:
  - **Viewer**: view-only
  - **User**: create/edit operational data
  - **Super Admin**: everything, including Settings and user management

### Navigation overview
Use the left sidebar:
- **Dashboard**: KPIs + quick actions
- **Runs**: extraction runs log + cost/yield outputs
- **Inventory**: on-hand lots + in-transit purchases
- **Purchases**: batch-level purchase records + batch IDs
- **Costs**: operational cost entries (solvent/personnel/overhead)
- **Biomass Pipeline**: pre-purchase pipeline tracking (declared → testing → committed → delivered/cancelled)
- **Suppliers**: supplier performance analytics
- **Strains**: strain performance analytics
- **Settings** (Super Admin only): system parameters, KPIs, users, maintenance actions
- **Import**: CSV import review + confirm

---

## Dashboard
The Dashboard shows:
- **Summary stats**: total runs, lbs processed, dry output, biomass on hand
- **KPI cards**: color-coded performance vs targets
- **Quick actions**: shortcuts to create new runs/purchases/suppliers

### Analytics filter banner (optional)
If you see a banner saying analytics are excluding runs missing biomass pricing ($/lb), your admin has enabled a data-quality filter in **Settings**. Supplier/strain KPIs will ignore runs with missing purchase pricing on any input lot.

---

## Runs (Extraction Runs)
The Runs page is the core production log.

### What a run records
Typical fields include:
- Run date, reactor number, rollover flag, run type
- Biomass processed (lbs) and derived grams ran
- Wet and dry output for **HTE** and **THCA**
- Notes

### Adding a new run
1. Go to **Runs** → **+ New Run**
2. Fill in the run details and outputs.
3. Add **input lots** (the biomass lots consumed by this run) and the weight used from each lot.
4. Save.

### What happens on save
- **Yields** are recalculated automatically (overall, THCA, HTE).
- **Lot remaining weights** are automatically decreased based on the input weights.
- **Cost per gram** is recalculated based on:
  - Biomass input pricing ($/lb) from linked purchases, and
  - Allocated operational costs (from the Costs module).

### Missing pricing badges
On the Runs list, the Source column may show:
- **No $/lb**: none of the run’s input lots have purchase pricing
- **Partial $/lb**: some input lots have pricing, some are missing

These badges help identify runs that may skew cost analytics.

### Editing or deleting runs
- **Edit**: updates calculations again on save.
- **Delete**: restores lot remaining weights (so inventory stays correct).

---

## Inventory
Inventory shows the current biomass position.

### Biomass On Hand
This table lists lots with remaining weight, including:
- Strain, supplier
- Original weight and **remaining** weight
- Potency (if recorded on the lot)
- Milled flag and location

### In Transit / On Order
This table lists purchases that are not yet fully received, including:
- Supplier and status
- Stated weight
- Order date and expected delivery
- Price per lb (if known)

### Days of Supply
Days of supply is based on:
- Total on-hand biomass
- Your configured **Daily Throughput Target** (set in Settings)

---

## Purchases (Batches)
Purchases are batch-level records used for pricing, receiving, and inventory creation.

### Batch IDs
Each purchase has a **unique Batch ID** (human-readable). You can:
- **Leave it blank** to auto-generate, or
- Enter a custom Batch ID (must be unique)

Batch IDs are used across the app to make batches easy to identify and to link into the Biomass Pipeline.

### Creating a new purchase
1. Go to **Purchases** → **+ New Purchase**
2. Choose supplier, purchase date, status, and weight/pricing fields.
3. (Optional) add lots/strains for the purchase at creation time.
4. Save.

### Potency-based pricing and true-up
Purchases support:
- Stated potency and tested potency
- Price per lb (can be entered directly)
- True-up amount calculation when potency changes and actual weight is known

### Editing purchase status
Purchase status affects:
- Whether it is treated as in-transit vs on-hand inventory views
- If the purchase is linked to a Biomass Pipeline record, the pipeline stage is kept in sync

### Adding lots to an existing purchase
Open a purchase and use “Add Lot to This Purchase” to add strain lots. Lots create inventory that can be consumed by runs.

---

## Biomass Pipeline
The Biomass Pipeline tracks farm availability before it becomes a purchase.

### Stages
- **Declared**: supplier declares availability (date/weight/price/potency)
- **Testing**: testing step (timing + status + results)
- **Committed**: you commit to purchase (delivery date, $/lb, committed weight)
- **Delivered**: arrived (or close-out stage if you use it that way)
- **Cancelled**: batch is cancelled

### Creating a pipeline record
1. Go to **Biomass Pipeline** → **+ New Availability**
2. Fill Step 1 (Declaration)
3. Optionally fill Step 2 (Testing) and Step 3 (Commitment)
4. Set the Stage and Save

### Linking to Purchases (sync behavior)
- When a pipeline record is moved to **Committed** (or Delivered), the app will create a linked Purchase if one does not already exist.
- If a linked Purchase exists, key fields stay synchronized (supplier/date/weights/potency/$/lb/status).
- The pipeline list shows the linked Batch ID (when present) and links directly to the Purchase.

### Validation and error messages
If something is missing or invalid (bad date, negative weight, invalid stage), you’ll see a clear error message. Fix the input and save again.

---

## Costs (Operational Costs)
Use Costs to capture operating expenses that should be included in run $/g.

### What a cost entry represents
Each entry has:
- Type: **solvent**, **personnel**, or **overhead**
- A **date range** (start/end)
- Total cost (required)
- Optional unit cost + quantity + unit for tracking detail

### How costs affect $/g
Operational costs are allocated as:
- total dollars in a period ÷ total dry grams produced in that period
- applied as an additional $/g to runs occurring inside the cost entry’s date range

### Adding a cost entry
1. Go to **Costs** → **+ New Cost Entry**
2. Choose type, name, date range, and total cost
3. Save

---

## Suppliers (Performance)
Suppliers shows performance analytics by farm, including:
- All-time and recent averages (yield %, THCA %, cost/gram)
- Last-batch performance snapshot

If the “exclude runs missing $/lb” setting is enabled, these analytics ignore runs with incomplete biomass pricing.

---

## Strains (Performance)
Strains compares yield/cost metrics grouped by strain + supplier.

If the “exclude runs missing $/lb” setting is enabled, these analytics ignore runs with incomplete biomass pricing.

---

## Settings (Super Admin)
Settings control system behavior and performance targets.

### Operational Parameters
Includes:
- Potency rate used for potency-based pricing
- Reactor count/capacity
- Throughput targets
- Optional analytics filter: **Exclude runs missing biomass pricing ($/lb)**
- Cost allocation method: **Uniform**, **Split 50/50**, or **Custom split**

### KPI Targets
Set KPI targets and green/yellow thresholds to match operational goals.

### Users
Admins can create users and assign roles. (This manual does not include any credentials.)

### Maintenance: Recalculate all run costs
Use **Recalculate All Run Costs** after:
- entering new operational costs,
- changing cost allocation settings, or
- correcting biomass pricing

This recomputes cost-per-gram fields for all historical runs using current rules.

---

## Import (CSV)
Import supports loading historical data via CSV with a review step.

### Import flow
1. Go to **Import**
2. Upload a CSV file
3. Review the preview (the app filters repeating header rows)
4. Confirm import

The importer attempts to:
- normalize dates
- create suppliers as needed
- avoid obvious duplicates

---

## Export (CSV)
Most list screens include **Export CSV**. Exports available include:
- Runs
- Purchases
- Inventory
- Biomass Pipeline

Use exports for reporting, reconciliation, or offline analysis.

---

## Troubleshooting
- **I see “No $/lb” on runs**: ensure each input lot’s purchase has `Price/lb` set.
- **Supplier/Strain analytics look “low”**: check if “exclude runs missing $/lb” is enabled in Settings.
- **Cost numbers changed after adding costs**: that’s expected; run $/g reflects operational costs in the relevant date ranges.
- **A pipeline record didn’t create a purchase**: set stage to **Committed** (or Delivered) and save; ensure required fields are valid.

