# Gold Drop Production Tracker — User Manual

This guide walks you through every section of the Gold Drop web application with step-by-step instructions. It is written for new users who have never used the system before. Ask your administrator for login credentials — this manual intentionally does not include any usernames or passwords.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard](#dashboard)
3. [Extraction Runs](#extraction-runs)
4. [Inventory](#inventory)
5. [Purchases](#purchases)
6. [Biomass Pipeline](#biomass-pipeline)
7. [Operational Costs](#operational-costs)
8. [Suppliers](#suppliers)
9. [Strain Performance](#strain-performance)
10. [Settings (Super Admin)](#settings-super-admin)
11. [CSV Import](#csv-import)
12. [CSV Export](#csv-export)
13. [Understanding Calculations](#understanding-calculations)
14. [Troubleshooting](#troubleshooting)

---

## Getting Started

### Logging In

1. Open the site URL provided by your administrator in any web browser.
2. Enter your **Username** and **Password** in the login form.
3. Click **Sign In**.
4. You will be taken to the Dashboard.

If you see "Invalid username or password," double-check your credentials and try again. Your session lasts 8 hours before you need to sign in again.

### User Roles

Your role determines what you can do in the system:

| Role | Can View | Can Create/Edit | Can Access Settings |
|------|----------|-----------------|---------------------|
| **Viewer** | All pages | Nothing | No |
| **User** | All pages | Runs, Purchases, Costs, Biomass, Suppliers, Import | No |
| **Super Admin** | All pages | Everything | Yes (Settings, Users) |

If a button or action is missing from your view, your role may not have permission for it. Contact your administrator to request a role change.

### Navigating the Application

The left sidebar is your primary navigation. It is always visible and contains links to every section:

- **Dashboard** — Performance overview and KPI cards
- **Runs** — Extraction run log
- **Inventory** — On-hand biomass and incoming orders
- **Purchases** — Batch-level purchase records
- **Biomass Pipeline** — Pre-purchase tracking from farm declaration to delivery
- **Costs** — Operational cost entries (solvent, personnel, overhead)
- **Suppliers** — Farm performance analytics
- **Strains** — Strain-level yield and cost comparison
- **Settings** — System configuration (Super Admin only)
- **Import** — CSV data upload

Your username and role are shown at the bottom of the sidebar. Click **Logout** to end your session.

---

## Dashboard

The Dashboard is the landing page after login. It provides a high-level view of production performance.

### Viewing the Dashboard

1. Click **Dashboard** in the sidebar (or it loads automatically after login).
2. At the top you will see four **summary cards**:
   - **Total Runs** — Number of extraction runs in the selected period
   - **Lbs Processed** — Total biomass input in pounds
   - **Dry Output (g)** — Total dry grams produced (THCA + HTE combined)
   - **Biomass On Hand (lbs)** — Current available inventory

### Filtering by Time Period

1. Look for the row of period buttons below the page title: **Today**, **7 Days**, **30 Days**, **90 Days**, **All Time**.
2. Click any button to filter all summary stats and KPI cards to that time window.
3. The default view is **30 Days**.

### Reading KPI Cards

Below the summary stats you will see color-coded KPI cards. Each card shows:

- The KPI name (e.g., "THCA Yield %")
- The current value for the selected period
- The target value

Cards are color-coded:

| Color | Meaning |
|-------|---------|
| **Green** | Meeting or exceeding the target |
| **Yellow** | Close to target but not quite meeting it |
| **Red** | Below acceptable threshold |
| **Gray** | No data available for this period |

### Using Quick Actions

If you have User or Super Admin access, the Dashboard shows shortcut buttons:

1. **+ Log New Run** — Opens the new extraction run form.
2. **+ New Purchase** — Opens the new purchase form.
3. **+ Add Supplier** — Opens the new supplier form.
4. **Export Runs CSV** — Downloads all run data as a CSV file.

### Analytics Filter Banner

If you see a yellow banner at the top saying "Analytics filter enabled," your admin has turned on a data-quality filter. This means runs that have missing biomass pricing ($/lb) are excluded from KPI calculations. This setting can be changed in **Settings**.

---

## Extraction Runs

Runs are the core of the system. Each run represents a single extraction operation where biomass is processed into HTE and/or THCA products.

### Viewing the Runs List

1. Click **Runs** in the sidebar.
2. You will see a table of all extraction runs, sorted by date (newest first).
3. The table shows: Date, Reactor #, Source (strain and supplier info), Lbs, Wet HTE/THCA, Dry HTE/THCA, Yield %, THCA %, HTE %, $/gram, Type, and an Edit button.

### Searching for Runs

1. On the Runs page, find the **search box** at the top of the page.
2. Type a strain name to search for.
3. Click **Search** (or press Enter).
4. The table filters to show only runs matching that strain.
5. Clear the search box and search again to remove the filter.

### Sorting the Table

1. Click any column header to sort by that column.
2. Click the same header again to reverse the sort order (ascending/descending).

### Understanding Pricing Badges

In the Source column, you may see colored badges:

- **No $/lb** (red) — None of the run's input lots have a price per pound on their purchase. Cost analytics for this run are incomplete.
- **Partial $/lb** (yellow) — Some input lots have pricing, others do not.
- No badge — All input lots are fully priced.

### Navigating Pages

The list shows 25 runs per page. Use the **Previous** / **Next** links and numbered page buttons at the bottom to navigate.

### Creating a New Run

1. Click **+ New Run** at the top of the Runs page.
2. Fill in the **Run Details** section:
   - **Date** — Select the date the extraction was performed (defaults to today).
   - **Reactor #** — Choose which reactor was used (Reactor 1, 2, or 3).
   - **Run Type** — Select Standard, Kief, or Liquid Diamond.
   - **Rollover checkbox** — Check this if the run combined leftovers or blended multiple sources.
3. Fill in the **Source Material** section:
   - A dropdown shows all available lots with remaining weight.
   - Select a lot. The dropdown shows the strain name, supplier, and remaining weight.
   - Enter the **Lot Weight** in pounds — how much of that lot this run consumed.
   - To add more lots, click **+ Add Source Lot** and repeat.
   - To remove a lot row, click the **X** button on that row.
4. Fill in the **Input** section:
   - **Lbs in Reactor** (required) — Total biomass weight loaded into the reactor.
   - **Bio in House** — Optional backup biomass on hand (not in reactor).
   - **Butane in House** — Optional solvent inventory.
   - **Solvent Ratio**, **System Temp**, **Fuel Consumption** — Optional operational details.
5. Fill in the **Output** section:
   - **Wet HTE** and **Wet THCA** — Pre-drying output weights in grams.
   - **Dry HTE** and **Dry THCA** (at least one required) — Final dried product weights in grams.
6. Optionally check **Decarb sample done** and add **Notes**.
7. Click **Save Run**.

After saving:
- Yield percentages are automatically calculated.
- Cost per gram is calculated based on biomass pricing and any operational costs in the date range.
- Lot remaining weights are decremented by the amounts you entered.

### Editing a Run

1. On the Runs list, click the **Edit** button for the run you want to change.
2. Modify any fields as needed.
3. Click **Save Run**.
4. The system will restore the original lot weights, apply your changes, and recalculate everything.

### Deleting a Run

1. Open the run for editing.
2. Click the **Delete Run** button (red, at the bottom-left).
3. Confirm the deletion when prompted.
4. The run is removed and all lot remaining weights are restored.

---

## Inventory

The Inventory page shows your current biomass position at a glance.

### Viewing Inventory

1. Click **Inventory** in the sidebar.
2. At the top, four summary cards show:
   - **On Hand** — Total pounds of biomass currently available.
   - **In Transit** — Total pounds ordered/committed but not yet received.
   - **Days of Supply** — How many days your on-hand inventory will last at the current daily throughput target. Color-coded: green (5+ days), yellow (3–5 days), red (under 3 days).
   - **Total Available** — On Hand + In Transit combined.

### Reading the Biomass On Hand Table

This table lists every lot that still has remaining weight, grouped from purchases with a delivered/received status.

| Column | What It Shows |
|--------|---------------|
| Strain | Cannabis strain name |
| Supplier | Which farm it came from |
| Original (lbs) | Weight when first received |
| Remaining (lbs) | Weight still available (after extraction runs have consumed some) |
| Potency % | Tested or estimated THC potency |
| Milled | Whether the biomass has been milled (Yes/No) |
| Location | Where it is stored |

### Reading the In Transit / On Order Table

This table lists purchases that have been committed, ordered, or are in transit but not yet delivered.

| Column | What It Shows |
|--------|---------------|
| Supplier | Farm name |
| Status | Current status (committed, ordered, in_transit) |
| Weight (lbs) | Stated weight of the order |
| Order Date | When the purchase was placed |
| Expected Delivery | When delivery is expected |
| Price/lb | Agreed price per pound (if known) |

### Exporting Inventory Data

1. Click **Export CSV** at the top of the Inventory page.
2. A CSV file downloads containing all on-hand lot data.

---

## Purchases

Purchases are batch-level records that track biomass from ordering through receiving. Each purchase can contain one or more lots (strains).

### Viewing the Purchases List

1. Click **Purchases** in the sidebar.
2. You will see a table of all purchases sorted by date (newest first).

### Filtering by Status

1. At the top of the page, find the row of status filter buttons: **All**, **Committed**, **Ordered**, **In Transit**, **Delivered**, **Complete**, **Cancelled**.
2. Click any button to show only purchases with that status.
3. Click **All** to remove the filter.

### Understanding the Purchases Table

| Column | What It Shows |
|--------|---------------|
| Date | Purchase date |
| Batch | Unique batch identifier (auto-generated or manually entered) |
| Supplier | Farm name |
| Status | Current status (color-coded badge) |
| Stated Lbs | Weight at time of order |
| Actual Lbs | Actual received weight (if different) |
| Potency % | Stated potency and tested potency (if available) |
| $/lb | Price per pound |
| Total Cost | Full cost of the batch |
| True-Up | Adjustment amount based on potency variance (red = you owe more, green = credit) |
| Lots | Count of strain lots in this purchase |

### Creating a New Purchase

1. Click **+ New Purchase** at the top of the Purchases page.
2. Fill in **Purchase Details**:
   - **Supplier** (required) — Select from the dropdown of active suppliers.
   - **Purchase Date** (required) — When the purchase was made (defaults to today).
   - **Status** — Set the current status (e.g., committed, ordered, delivered).
   - **Batch ID** — Leave blank to auto-generate, or type a custom unique ID.
3. Fill in **Weight & Pricing**:
   - **Stated Weight (lbs)** (required) — The expected weight of the batch.
   - **Actual Weight (lbs)** — Fill in after receiving if different from stated.
   - **Delivery Date** — When the batch was or will be delivered.
   - **Stated Potency %** — Expected THC potency. If entered, the system auto-calculates price per pound using the potency rate from Settings.
   - **Tested Potency %** — Lab-tested potency. Triggers true-up calculation.
   - **Price/lb** — Cost per pound. Auto-calculated from potency if left blank, or enter manually.
4. Optionally fill in **Biomass Details**: clean/dirty status, indoor/outdoor, harvest date, and notes.
5. Optionally add **Lots/Strains**: enter a strain name and weight for each lot. Click **+ Add Lot** for additional strains.
6. Click **Save Purchase**.

### Understanding Batch IDs

Batch IDs follow the format: `PREFIX-DDMONYY-WEIGHT`

- **PREFIX** — First 5 letters of the supplier name (uppercase)
- **DDMONYY** — Delivery date (or purchase date if no delivery date)
- **WEIGHT** — Actual weight (or stated weight) in pounds

Example: `FARML-15FEB26-200` means supplier "Farmland," delivered Feb 15 2026, 200 lbs.

If you enter a Batch ID that already exists, you will see an error. Either choose a different ID or leave the field blank to auto-generate.

### Editing a Purchase

1. Click the **Edit** button on any purchase row.
2. Modify fields as needed.
3. Click **Save Purchase**.
4. If the purchase is linked to a Biomass Pipeline record, changes to status will sync back to the pipeline.

### Adding Lots to an Existing Purchase

1. Open the purchase for editing.
2. Scroll below the Save button to find the **Add Lot to This Purchase** section.
3. Enter the **Strain Name**, **Weight (lbs)**, and optionally **Potency %**.
4. Click **Add Lot**.
5. The lot is added immediately and appears in the Lots table above.
6. Repeat for additional lots.

Lots create inventory that can be consumed by extraction runs.

---

## Biomass Pipeline

The Biomass Pipeline tracks farm availability from initial declaration through testing, commitment, and delivery. It is the recommended way to manage incoming biomass because it automatically creates and syncs Purchase records.

### Viewing the Pipeline

1. Click **Biomass Pipeline** in the sidebar.
2. You will see a table of all pipeline records.

### Filtering by Stage

1. Use the filter buttons at the top: **All**, **Declared**, **Testing**, **Committed**, **Delivered**, **Cancelled**.
2. Click a button to show only records at that stage.

### Understanding Pipeline Stages

| Stage | Meaning |
|-------|---------|
| **Declared** | The supplier has declared they have biomass available. No commitment yet. |
| **Testing** | The biomass is being lab-tested (or testing results are pending). |
| **Committed** | You have committed to purchase. A Purchase record is automatically created or updated. |
| **Delivered** | The biomass has arrived. The linked Purchase is updated to delivered status. |
| **Cancelled** | The deal was cancelled. The linked Purchase (if any) is marked cancelled. |

### Understanding the Pipeline Table

| Column | What It Shows |
|--------|---------------|
| Supplier | Farm name |
| Batch | Linked Purchase batch ID (click to open the purchase). Appears once stage reaches Committed. |
| Strain | Cannabis strain name |
| Stage | Current stage (color-coded badge) |
| Avail Date | When the supplier said biomass would be available |
| Declared Lbs | Weight the supplier declared |
| Declared $/lb | Price the supplier quoted |
| Est Potency % | Estimated THC potency |
| Testing | Testing timing (before/after delivery), status (pending/completed/not needed), date, and tested potency |
| Committed | Commitment date, delivery date, committed weight, and committed price |

### Creating a New Pipeline Record

1. Click **+ New Availability** at the top of the Biomass Pipeline page.
2. Fill in **Step 1 — Declaration of Availability**:
   - **Supplier** (required) — Select the farm from the dropdown.
   - **Availability Date** (required) — When the biomass will be available.
   - **Strain** — The strain name (e.g., "Rockets x Humboldt").
   - **Declared Weight (lbs)** — How many pounds the supplier declared.
   - **Declared Price ($/lb)** — The supplier's quoted price per pound.
   - **Estimated Potency (%)** — Expected THC potency.
3. Fill in **Step 2 — Testing** (optional, fill as information becomes available):
   - **Testing Timing** — Select "Before delivery" or "After delivery."
   - **Testing Status** — Set to "Pending," "Completed," or "Not needed."
   - **Testing Date** — When the lab test was or will be performed.
   - **Tested Potency (%)** — The lab-verified potency result.
4. Fill in **Step 3 — Commitment to Purchase** (optional, fill when committing):
   - **Commitment Date** — When you committed to buy.
   - **Delivery Date** — Expected or actual delivery date.
   - **Committed Price ($/lb)** — The final agreed price.
   - **Committed Weight (lbs)** — The final agreed weight.
5. Set the **Stage** dropdown to match the current status of this biomass.
6. Optionally add **Notes**.
7. Click **Save**.

### What Happens When You Change the Stage

- **Moving to Committed or Delivered**: The system automatically creates a Purchase record if one does not already exist. The Purchase is pre-filled with the supplier, dates, weights, potency, and pricing from the pipeline record.
- **Moving to any stage**: If a linked Purchase already exists, its status is updated to match (declared, in_testing, committed, delivered, or cancelled).
- **Key fields stay synchronized**: Changes to supplier, dates, weights, potency, and pricing on the pipeline record are synced to the linked Purchase on every save.

### Editing a Pipeline Record

1. Click the **Edit** button on any pipeline row.
2. Update any fields, including changing the stage.
3. Click **Save**.
4. The linked Purchase (if any) will be updated automatically.

### Deleting a Pipeline Record

1. Open the record for editing.
2. Click the **Delete** button (red, bottom-left).
3. Confirm when prompted.
4. The pipeline record is deleted. The linked Purchase (if any) is **not** deleted — you must delete it separately from the Purchases page if needed.

---

## Operational Costs

The Costs section lets you record operational expenses (solvent, personnel, overhead) so they can be allocated into the cost-per-gram calculation for extraction runs.

### Viewing Costs

1. Click **Costs** in the sidebar.
2. At the top, four summary cards show totals by category:
   - **Solvent Costs** — Total of all solvent-type entries
   - **Personnel Costs** — Total of all personnel-type entries
   - **Overhead Costs** — Total of all overhead-type entries
   - **Total OpEx** — Combined total across all categories

### Filtering by Cost Type

1. Use the filter buttons: **All**, **Solvents**, **Personnel**, **Overhead**.
2. Click a button to show only that category.

### Understanding the Costs Table

| Column | What It Shows |
|--------|---------------|
| Type | Category badge: solvent (gold), personnel (green), overhead (gray) |
| Name | Description (e.g., "N-Butane," "Lead Technician," "Facility Rent") |
| Unit Cost | Cost per unit with unit label (e.g., "$2.50 / lb") |
| Qty | Quantity used |
| Total | Total cost for the period |
| Period | Date range (start date – end date) |
| Notes | Additional details |

### Creating a New Cost Entry

1. Click **+ New Cost Entry** at the top of the Costs page.
2. Fill in **Cost Details**:
   - **Cost Type** (required) — Select Solvent, Personnel, or Overhead.
   - **Name** (required) — A description of the cost (e.g., "N-Butane," "Booth Operator," "Rent").
   - **Unit** — The measurement unit (e.g., "lbs," "hours," "month").
3. Fill in **Amount**:
   - **Unit Cost** — Cost per unit (e.g., $2.50/lb).
   - **Quantity** — Amount used (e.g., 500 lbs).
   - **Total Cost** (required) — Automatically calculated as Unit Cost x Quantity if both are provided, or enter the total directly.
4. Fill in **Period**:
   - **Start Date** (required) — When the cost period begins.
   - **End Date** (required) — When the cost period ends.
5. Optionally add **Notes**.
6. Click **Save Cost Entry**.

### How Costs Affect Run Pricing

Operational costs are allocated to runs based on date ranges:

1. The system looks at all cost entries whose date range contains a given run's date.
2. It sums the total dollars of those cost entries.
3. It divides by the total dry grams produced by **all** runs in that date range.
4. That per-gram rate is added to each run's biomass cost to produce the final $/gram.

After adding or editing cost entries, go to **Settings** and click **Recalculate All Run Costs** to update all historical run pricing.

### Editing a Cost Entry

1. Click the **Edit** button on any cost row.
2. Modify fields as needed.
3. Click **Save Cost Entry**.

### Deleting a Cost Entry

1. Click the **Delete** button on any cost row.
2. Confirm when prompted.
3. Remember to recalculate run costs after deleting (Settings → Recalculate All Run Costs).

---

## Suppliers

The Suppliers page shows performance analytics for each farm, helping you compare which suppliers yield the best results.

### Viewing Supplier Performance

1. Click **Suppliers** in the sidebar.
2. Each supplier is displayed as its own card.
3. Each card shows:
   - **Supplier name** and a count of total runs and total lbs processed.
   - A **performance table** with three time periods:

| Period | What It Shows |
|--------|---------------|
| **All Time** | Averages across the supplier's entire history |
| **Last 90 Days** | Averages from the past 90 days only |
| **Last Batch** | Results from the most recent batch |

   - Each period shows: Overall Yield %, THCA Yield %, HTE Yield %, Cost/Gram, and Run Count.
   - Values are color-coded green/yellow/red based on your KPI targets.
   - Below the table: Total Dry THCA and Total Dry HTE produced from this supplier.

### Adding a New Supplier

1. Click **+ Add Supplier** at the top of the Suppliers page.
2. Fill in the form:
   - **Farm / Supplier Name** (required) — The name of the farm or supplier.
   - **Contact Name** — Primary contact person.
   - **Phone** — Contact phone number.
   - **Email** — Contact email.
   - **Location** — Geographic location of the farm.
   - **Notes** — Any additional information.
3. Click **Save Supplier**.

### Editing a Supplier

1. Click the **Edit** button on any supplier card.
2. Modify fields as needed.
3. To mark a supplier as inactive, uncheck the **Active Supplier** checkbox. Inactive suppliers will not appear in dropdown lists for new purchases or pipeline records, but their historical data is preserved.
4. Click **Save Supplier**.

---

## Strain Performance

The Strains page lets you compare yield and cost metrics across different cannabis strains and their suppliers.

### Viewing Strain Analytics

1. Click **Strains** in the sidebar.
2. The table shows one row per strain-supplier combination.

### Filtering by Time Period

1. Use the period buttons at the top: **All Time** or **Last 90 Days**.
2. Click to filter the analytics to that window.

### Understanding the Strains Table

| Column | What It Shows |
|--------|---------------|
| Strain | Cannabis strain name |
| Supplier | Which farm grew it |
| Avg Yield % | Average overall yield (color-coded vs KPI target) |
| Avg THCA % | Average THCA yield (color-coded) |
| Avg HTE % | Average HTE yield |
| Avg $/gram | Average cost per gram |
| Total Lbs | Total biomass processed |
| Total THCA (g) | Total dry THCA produced |
| Total HTE (g) | Total dry HTE produced |
| Runs | Number of extraction runs |

The table is sorted by average yield (best performers first). Use this to identify which strains from which suppliers produce the best results.

---

## Settings (Super Admin)

The Settings page is only accessible to Super Admin users. It controls system-wide configuration.

### Accessing Settings

1. Click **Settings** in the sidebar. If you do not see it, your role does not have access.

### Configuring Operational Parameters

1. Scroll to the **Operational Parameters** section.
2. Adjust values as needed:
   - **Potency Rate ($/lb/%pt)** — The rate used to auto-calculate price per pound from potency percentage (default: $1.50).
   - **Number of Reactors** — How many reactors you operate.
   - **Reactor Capacity (lbs)** — Pounds each reactor can hold.
   - **Runs Per Day Target** — Target number of runs per day.
   - **Operating Days/Week** — Days per week you operate.
   - **Daily Throughput Target (lbs)** — Used for Days of Supply calculation on the Inventory page.
   - **Weekly Throughput Target (lbs)** — Used for the Weekly Throughput KPI.
3. To enable the data-quality filter, check **Exclude runs missing biomass pricing ($/lb) from yield + cost analytics**. When enabled, runs without valid purchase pricing on all input lots are excluded from KPI calculations on the Dashboard, Suppliers, and Strains pages.
4. Select a **Cost Allocation Method**:
   - **Uniform** (default) — THCA and HTE both get the same $/gram.
   - **Split 50/50** — Total run cost is split equally between THCA and HTE products.
   - **Custom split** — You specify what percentage of cost goes to THCA (the remainder goes to HTE). Set the **THCA % of total cost** field below.
5. Click **Save Settings**.

### Configuring KPI Targets

1. Scroll to the **KPI Targets** section.
2. For each KPI, you can set three values:
   - **Target** — The goal value you are aiming for.
   - **Green Threshold** — Values better than this are shown in green.
   - **Yellow Threshold** — Values between yellow and green thresholds are shown in yellow. Values worse than yellow are shown in red.
3. Current KPIs include:
   - THCA Yield %, HTE Yield %, Overall Yield % (higher is better)
   - Cost per Potency Point, Cost per Gram (lower is better)
   - Weekly Throughput (higher is better)
4. Click **Save KPI Targets**.

### Managing Users

1. Scroll to the **Users** section.
2. The table shows all existing users with their username, display name, role, and creation date.
3. To create a new user:
   - Enter a **Username** (lowercase, no spaces, must be unique).
   - Enter a **Display Name** (the name shown in the app).
   - Select a **Role**: Viewer (read-only), User (can edit data), or Super Admin (full access).
   - Enter a **Password** (minimum 8 characters).
   - Click **Create User**.

### Recalculating Run Costs

After making changes that affect cost calculations (adding cost entries, changing the cost allocation method, or correcting purchase pricing), you should recalculate all historical run costs:

1. Scroll to the **Maintenance** section at the bottom of Settings.
2. Click **Recalculate All Run Costs**.
3. Confirm when prompted.
4. The system recomputes cost-per-gram for every run using current pricing and cost data.
5. A confirmation message tells you how many runs were recalculated.

---

## CSV Import

The Import feature lets you load historical data from CSV files (typically exported from Google Sheets).

### Importing Data Step by Step

1. Click **Import** in the sidebar.
2. Click **Choose File** and select a CSV file from your computer.
3. Click **Upload & Preview**.
4. The system processes the file:
   - Repeated header rows are automatically filtered out.
   - Dates are normalized to a standard format.
   - A preview table shows the first 50 rows of data.
5. Review the preview to make sure the data looks correct.
6. Click **Confirm Import** to proceed, or click **Upload Different File** to start over.
7. After confirmation, the system imports the data:
   - New suppliers are created automatically from the Source column if they do not already exist.
   - Duplicate records (matching on date + strain + source) are skipped.
   - Purchases and lots are created for each new supplier/strain combination.
   - Runs are created with yields auto-calculated.
8. A summary message shows how many rows were imported, skipped, and had errors.
9. You are redirected to the Runs page to see the imported data.

### Supported CSV Format

The CSV should have columns matching the run report format. Recognized column names include:

- Date, Source, Strain, Price
- Bio in House, Lbs Ran, Grams Ran
- Wet HTE, Wet THCA
- Dry HTE, Dry THCA
- Butane in House, Solvent Ratio

Column matching is case-insensitive. The first 500 rows are processed.

### Tips for Successful Import

- Export each Google Sheet tab (Run Report, Kief Runs, LD Runs, Intakes) as a separate CSV file.
- The importer handles repeated header rows (common in multi-section Google Sheets).
- Always review the preview before confirming.
- After importing, spot-check a few runs to verify the data imported correctly.

---

## CSV Export

Most pages offer a CSV export button for downloading data.

### Exporting Data

1. Navigate to the page with the data you want to export (Runs, Purchases, Inventory, Biomass Pipeline, or Costs).
2. Click the **Export CSV** button at the top of the page.
3. A CSV file downloads automatically.
4. The filename includes the data type and today's date (e.g., `runs_2026-02-16.csv`).

### Available Exports

| Page | What the Export Contains |
|------|-------------------------|
| **Runs** | Date, Reactor, Source, Lbs, Wet/Dry HTE/THCA, Yields, Cost/Gram, Notes |
| **Purchases** | Date, Batch ID, Supplier, Status, Weights, Potency, Pricing, True-Up, Strains |
| **Inventory** | Strain, Supplier, Weight, Remaining, Potency, Milled, Location |
| **Biomass Pipeline** | Stage, Supplier, Strain, All declaration/testing/commitment fields, Batch ID |
| **Costs** | Type, Name, Unit Cost, Quantity, Total, Period, Notes |

---

## Understanding Calculations

This section explains the key calculations the system performs automatically.

### Yield Calculations

When a run is saved, yields are computed as:

- **Grams Ran** = Lbs in Reactor x 454
- **Overall Yield %** = (Dry HTE + Dry THCA) / Grams Ran x 100
- **THCA Yield %** = Dry THCA / Grams Ran x 100
- **HTE Yield %** = Dry HTE / Grams Ran x 100

### Cost Per Gram

The cost per gram combines two components:

1. **Biomass cost**: The sum of (lbs used from each lot x that lot's purchase price per pound), divided by total dry grams output.
2. **Operational cost**: All cost entries whose date range covers the run date are allocated proportionally across all dry grams produced in that period, then applied to this run.
3. **Combined $/gram** = (Biomass Cost + Operational Cost) / Total Dry Grams

The allocation to individual products (THCA vs HTE) depends on the cost allocation method chosen in Settings.

### True-Up Amount

When a purchase has stated potency, tested potency, actual weight, and a potency rate:

**True-Up** = (Tested Potency - Stated Potency) x Potency Rate x Actual Weight

- Positive value = you owe additional money (higher potency than expected).
- Negative value = you are owed a credit (lower potency than expected).

### Days of Supply

**Days of Supply** = Total On-Hand Biomass (lbs) / Daily Throughput Target (lbs)

The daily throughput target is set in Settings (default: 500 lbs/day).

---

## Troubleshooting

### "No $/lb" badges appear on my runs

This means the input lots for those runs do not have a Price/lb set on their parent Purchase. To fix:
1. Go to **Purchases** and find the relevant purchase.
2. Edit it and fill in the **Price/lb** field.
3. Go to **Settings** → **Recalculate All Run Costs**.

### Supplier or Strain analytics seem too low or data is missing

Check if the "Exclude runs missing biomass pricing" filter is enabled in **Settings**. When enabled, any run with incomplete pricing is excluded from analytics. Either:
- Disable the filter in Settings, or
- Add pricing to the relevant purchases.

### Cost numbers changed after I added new cost entries

This is expected. Operational costs are allocated across all runs in the cost entry's date range. Adding a new cost entry increases the $/gram for all runs in that period. Use **Recalculate All Run Costs** in Settings to ensure everything is up to date.

### A pipeline record did not create a Purchase

Purchases are only created automatically when the stage is set to **Committed** or **Delivered**. Make sure:
1. The **Supplier** field is filled in.
2. The **Availability Date** is valid.
3. The **Stage** is set to Committed or Delivered.
4. Click **Save** again.

### I accidentally deleted a run and need the inventory back

When you delete a run, the system automatically restores the lot remaining weights. Your inventory should already be correct. Verify by checking the **Inventory** page.

### My Batch ID already exists

Batch IDs must be unique. Either:
- Clear the Batch ID field and let the system auto-generate one, or
- Enter a different custom ID that is not already in use.

### I do not see the Settings page

Only Super Admin users can access Settings. Contact your administrator to request role elevation if needed.

### Days of Supply shows an unexpected value

Days of Supply is calculated using the **Daily Throughput Target** set in Settings. If the number seems off, check that the target is set correctly (Settings → Operational Parameters → Daily Throughput Target).
