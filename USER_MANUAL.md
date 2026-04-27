# Gold Drop Production Tracker — User Manual

This guide explains how to use the Gold Drop web app day-to-day. It intentionally **does not include any usernames or passwords**. Ask your administrator for access.

**Other documents:** `FAQ.md` (quick answers), `PRD.md` (product requirements), `ENGINEERING.md` (technical implementation notes for developers).

**Current release note:** the app has now been split internally across dedicated route modules for dashboard, field intake, runs, purchases, biomass, costs, inventory, batch edit, suppliers/photos, purchase import, strains, settings, and Slack integration. The workflows in this manual are still the ones you should test: routes, page names, approvals, list screens, and Slack import behavior are intended to work the same as before.

**Operator-facing additions in the current release:** Purchases and Inventory are more status-first, the Journey page is richer, Slack imports now includes inbox buckets, lot labels now print with scannable barcodes, `Floor Ops` gives operators a recent activity surface, the standalone receiving app can now correct a confirmed receipt before downstream lot consumption, the standalone extraction app now mirrors the reactor workflow with touch-first controls, and the data model supports live smart-scale capture.

**Manager-facing note for the current release:** the app now includes the first usable derivative-lot genealogy layer. Current day-to-day workflows still use Purchases, Inventory, Runs, and Downstream Queues the same way, but the system can now bridge biomass lots into first-class material genealogy records, auto-create dry HTE / dry THCA derivative lots from eligible extraction runs, extend genealogy into accountable downstream child lots like GoldDrop / wholesale THCA / terp strip / HP base oil / distillate, expose manager-facing ancestry / descendant journey endpoints through the internal API, record correction-forward genealogy fixes instead of silently overwriting bad lineage, summarize open derivative cost basis through the internal API, surface linked derivative lots directly on downstream queue cards, provide a dedicated `Genealogy Report` page for manager reporting, open those lots or runs in a real HTML `Material Journey Viewer` with `By Lot` and `By Run` path tracing, and record actual revenue events against material lots for actual-vs-projected margin review.

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
- The sidebar is now grouped by workflow area instead of exposing every function as a flat first-level item.
- Each top-level sidebar section is collapsible, so you can keep submenus hidden until you need that workflow area.
- Treat the top-level sections this way:
  - `Purchasing` = buyer workflow and purchase review
  - `Inventory` = on-hand lot visibility
  - `Extraction` = overview, floor execution, and run administration
  - `Downstream` = queue triage plus destination-specific work surfaces
  - `Journey` = daily manager tracing, lineage, cost-basis visibility, and assumption-backed revenue projection
  - `Alerts` = action queue for supervisor and genealogy exceptions
  - `Settings` = Super Admin-only configuration grouped into operational, Journey financial, extraction, Slack/notification, access, integration, and maintenance sections
  - `More` = lower-frequency admin and specialist tools, including `Scorecards (beta)`
- **Extraction** (labeled on the home dashboard card): KPIs + quick actions
- **Biomass purchasing**: buyer weekly snapshot, field submission queues, and reviewed history
- **Scorecards (beta)**: the former Departments surface; a secondary management lens with quick links and thin rollups, not a primary daily operating workflow
- **Runs**: extraction runs log + cost/yield outputs
- **Supervisor Console**: supervisor/downstream launch surface for queue health, open alerts, blocked/stale work, reactor context, and handoffs into the focused work pages
- **Downstream Queues**: supervisor-facing post-extraction routing board for completed runs that now need a downstream destination or hold
- **Genealogy Report**: manager-facing lineage, derivative inventory, product summaries, cost, projected revenue, actual revenue, variance, financial-completeness reporting, and CSV export for accountable material lots
- **Journey Home**: manager dashboard for blocked/stale work, critical genealogy issues, aging derivative lots, low-margin runs, product financial cards, inventory value leaders, 7/30 day projected revenue and margin, actuals below projection, and financial completeness flags
- **Material Journey Viewer**: opened from the Genealogy Report or linked derivative lots; gives `By Lot` and `By Run` visual path tracing for genealogy-backed material and records/corrects/voids actual revenue events on lot pages
- **Inventory**: on-hand lots + in-transit purchases, including lot tracking IDs and remaining pounds
- **Purchases**: batch-level purchase records + batch IDs (same underlying rows as **Biomass Pipeline**); **Approve purchase** when your role allows; **Import spreadsheet** for bulk purchase upload; row **batch edit** on the list
- **Costs**: operational cost entries (solvent/personnel/overhead)
- **Biomass Pipeline**: pipeline view of **purchases** in early/procurement stages (**Declared** → **Testing** → **Committed** → **Delivered** / **Cancelled**); one **Batch ID** per row end-to-end
- **Suppliers**: supplier performance analytics
- **Strains**: strain performance analytics
- **Photo Library**: searchable media across supplier/purchase/field contexts; editors can upload and remove certain attachment types here (see **Photo Library** section)
- **Slack imports** (Slack Importer capability or Super Admin): triage synced Slack messages, preview mapped Run fields, review candidate source lots, optionally split a run across multiple lots, then **create run from Slack** (prefilled form)
- **Settings** (Super Admin only): system parameters, Journey revenue assumptions, extraction controls, Slack/notification routing, users/access, integrations, and maintenance actions
- Settings opens focused subpages from the left pane. Use **Slack & Notifications** for Slack credentials, outbound notification routing, channel history sync, Slack imports, and Slack field mappings; use **Launch Readiness** for acceptance testing and blocker tracking; use **Maintenance** only for run-cost recalculation, photo backfill, and remote-site cache pulls.
- **Cross-Site Ops** (only when enabled by Super Admin): cached local + remote-site rollups for multi-site reporting
- **Fresh operational reset** (server-side admin task): clears operational business data while keeping users, passwords, settings, KPI targets, Slack sync config, and cost entries
- **Import**: CSV import for **historical runs** (run-style exports)—not the same as **Purchases → Import spreadsheet**

Related mobile workflows:
- the standalone purchasing app is intended for buyer/intake users on phone or tablet
- the standalone receiving app is intended for dock / receiving users on phone or tablet
- the standalone extraction app is intended for extractors and assistant extractors on phone or tablet
- supervisor/downstream users should start in **Downstream -> Supervisor Console** in the main app
- all three workflows can be enabled or disabled independently by a Super Admin in **Settings -> Operational Parameters**
- the standalone purchasing and receiving apps are intentionally focused tools; use their `Open Purchase Review` / `Open in Main App` handoff links when you need the full main-app review surface

Journey revenue projections:
- Super Admins can enter assumed selling prices by derivative output type in **Settings -> Operational Parameters -> Journey Revenue Assumptions**.
- Journey and Genealogy Report use those assumptions to show projected revenue and projected gross margin for open output, released output, source-lot descendants, and run yield/cost rows.
- These are planning projections. Actual sales are recorded separately as material-lot revenue events from the Material Journey Viewer, then rolled up into actual revenue, actual margin, and projected-vs-actual variance.
- Financial completeness flags warn managers when cost basis, revenue assumptions, released-lot actual revenue, or genealogy issue cleanup is still missing.
- Use **Export Financial CSV** on Genealogy Report when you need product summaries, inventory groups, source-to-derivative rows, run yield rows, and financial flags in Excel.
- Use **Journey -> Finance & Accounting** when you need a period view of actual revenue, estimated COGS, gross margin, revenue by product, revenue by channel, and the revenue-event detail behind the totals.

### Standalone Extraction Lab App

- Use this app when you want a focused extraction surface without the rest of the admin UI.
- It is built for tablet and phone use by extractors and assistant extractors.
- The app emphasizes large buttons, weight sliders, quick `- / +` nudges, segmented reactor buttons, and minimal keyboard use.
- It also now includes a dedicated `Scan / Enter Lot` screen so operators can use the iPad camera, a Bluetooth scanner, or manual tracking-ID entry.
- The default charge preset is `100 lbs` per reactor whenever the lot has at least 100 lbs remaining; otherwise it defaults to the remaining lot weight.
- The manual tracking field auto-focuses on the scan screen, and the charge form remembers the last reactor used so repeat work moves faster.
- It mirrors the same charge and lifecycle workflow the main app uses on `Floor Ops`.
- After recording a charge, it can now open a dedicated standalone run-execution screen for the extractor workflow, and it can still open the main run form when deeper admin editing is needed.
- On the `Reactors` board, use the large `Open Run` button on the reactor card before `Mark Running` when the current policy requires a linked run.
- Inside the standalone run screen, use the guided progression buttons to move through the booth procedure with minimal typing: confirm vacuum, record solvent charge, start soak, run the mixer, confirm filter clear, start pressurization, begin recovery, move into flush, verify temperatures, record flush solvent charge, confirm flow resumed, run final purge, confirm final clarity, complete shutdown, then mark the run complete.
- The same screen now stores booth-specific proof fields such as primary solvent charge, flush chiller temperature, plate temperature, flush solvent charge, final purge timing, flow-resumed / clarity decisions, and the shutdown checklist.
- Use the `Booth evidence` section on the run screen to upload the required solvent chiller and plate temperature photos when your SOP calls for photo proof.
- The `Booth timing controls` section shows the live or recorded duration for primary soak, mixer, flush soak, and final purge, along with the configured target for each step.
- If flow has not resumed yet, choose `Still adjusting` and use the returned `Re-check Flow` step when recovery is ready to be checked again.
- If final clarity is not acceptable yet, choose `Not yet` and use `Resume Final Purge` to loop back through another purge pass before shutdown.
- `Settings -> Operational Parameters -> Extraction run defaults` controls the initial values the standalone run screen opens with for blend, fill count, total fill weight, flush count, total flush weight, stringer baskets, CRC blend, booth timing targets, and the per-step timing policy for primary soak, mixer, flush soak, and final purge.
- Timing policy defaults are intentionally permissive: primary soak, mixer, and flush soak default to `Warning only`, and final purge defaults to `Informational`. Super Admin can tighten any step to `Require supervisor override` or `Hard stop` when training or closer intervention is needed.

---

## Saved filters, sorts, and list state
Many **list screens** remember the filters and sort options you last used **for your current login session**, so you can **move freely between sections** (Dashboard, Runs, Purchases, Slack imports, etc.) and **come back without redoing your work**.

**Where this applies:** **Runs** (including search, date range, supplier, potency, HTE pipeline, and column sort), **Purchases** (filters, status, date range, potency, optional **Hide complete & cancelled**), **Biomass Pipeline**, **Costs**, **Inventory**, **Strains** (e.g. All time vs last 90 days), and **Slack imports** (date range, channels, promotion/coverage, text filters, and related toggles).

**How to clear:** When a list has active saved filters, use **Remove filters** to drop saved state for that page and return to the default “show everything” view (exact defaults vary by screen).

**Pagination:** After you **Apply filters** or change **Purchases** status chips, the list returns to **page 1** so a smaller result set is not hidden on an empty later page.

**Session limits:** Saved list state lives in your **session** (browser cookie). It is meant for **day-to-day navigation**, not permanent storage—**signing out**, **closing the browser** (depending on settings), or **clearing cookies** may reset it.

**Small UX notes:** Date fields use a **high-contrast calendar control** on dark backgrounds. On **New / Edit Purchase**, **Save Purchase** appears at both the **top** and **bottom** of the form.

---

## Batch editing from list screens

On several lists, if you can **Edit** a single row, you can often update **many rows at once**:

1. Use the checkboxes on the left of each row (where shown).
2. Use **Select all** or **Select none** to toggle every row on the **current page** of the table (pagination: if you use page 2, only page 2 rows are selected).
3. When **at least two** rows are checked, **Batch edit…** (or **Batch rename…** on **Strains**) becomes available.

You’ll see a page where only the fields you fill in are applied to **every selected record**; leave something blank or on “no change” to skip it.

**Where it works (and who):**

| Screen | What you’re editing | Typical access |
|--------|---------------------|----------------|
| **Runs** | Run type, HTE pipeline stage, rollover/decarb flags, load source (optional), append notes | **User** / **Super Admin** |
| **Purchases** | Status, delivery date, queue placement, append notes | Anyone with **purchase edit** (includes **Super Buyer** where enabled) |
| **Inventory** — On Hand | Lot strain, location, milled, potency, append lot notes | Purchase editors |
| **Inventory** — In Transit | Same kinds of fields as **Purchases** (these rows are purchases) | Purchase editors |
| **Biomass Pipeline** | Stage (maps to purchase **status**), testing status/timing, append notes | **User** / **Super Admin** (moving to/from **Committed** still needs a **purchase approver** on the form—see **Biomass Pipeline** section) |
| **Costs** | Cost type, append notes | **User** / **Super Admin** |
| **Suppliers** | Set suppliers active/inactive, append supplier notes | **User** / **Super Admin** |
| **Strains** | **Batch rename…** — one new strain name applied to all **purchase lots** matching each selected strain+supplier pair | **User** / **Super Admin** |

**Purchases batch edit** uses the same rules as saving one purchase: inventory lots and **weekly biomass budget** limits still apply. If the batch would break a limit, you may see an error and **no** row from that batch save is kept—fix the selection or values and try again.

**Strain batch rename** is powerful: it changes **lot** strain names everywhere they match the table row you selected. Use it when you are standardizing spelling or labels, not for routine tweaks to a single lot (use **Edit** on the purchase/lot instead).

---

## Dashboard
The Dashboard shows:
- **Summary stats**: total runs, lbs processed, dry output, biomass on hand
- **KPI cards**: color-coded performance vs targets
- **Quick actions**: shortcuts to create new runs/purchases/suppliers

### Analytics filter banner (optional)
If you see a banner saying analytics are excluding runs missing biomass pricing ($/lb), your admin has enabled a data-quality filter in **Settings**. Supplier/strain KPIs will ignore runs with missing purchase pricing on any input lot.

### Cross-Site Ops (optional)
This area is hidden unless a **Super Admin** enables **Cross-Site Ops UI** in **Settings -> Operational Parameters**.

When enabled, the sidebar exposes:
- **Cross-Site Ops**: local + cached remote site rollup
- **Supplier Comparison**: compare supplier performance across sites
- **Strain Comparison**: compare strain performance across sites
- **Reconciliation**: compare exception and Slack-import pressure across sites

These pages use the cached remote-site data already managed under **Settings -> Remote Sites**. They do not push changes back to remote sites.

---

## Runs (Extraction Runs)
The Runs page is the core production log.

Use the filter bar (**Start / end date**, supplier, THCA % range, **HTE pipeline**) and **Search** to narrow the list; **sort** by clicking column headers (e.g. **Date**). Your choices are **saved for your session**—see **Saved filters, sorts, and list state** above. **Apply filters** / search returns you to **page 1** of results when pagination is in use.

### What a run records
Typical fields include:
- Run date, reactor number, rollover flag, run type
- Biomass processed (lbs) and derived grams ran
- Wet and dry output for **HTE** and **THCA**
- Notes

The **Bio in House** field is now auto-populated from inventory (not manually entered).

#### HTE — lab and terp pipeline (after THCA/HTE separation)
For runs that produce dry HTE, you can track what happens **after extraction**:
- **Pipeline stage:** e.g. **Awaiting lab test** (material staged or out for testing), **Lab clean** (cleared for menu/sale), **Lab dirty — queued for Prescott strip** (waiting for Terp Tubes / stripping), **Stripped** (terp pass complete).
- **Lab / COA files:** attach photos or PDFs of test results to the run; remove old files with the checkboxes before saving.
- **After stripping:** enter **Terpenes recovered (g)** and **Retail distillate (g)** when the run is in the **Stripped** stage (or when your process dictates).

This is separate from **supplier-level** lab history on the **Suppliers** screen—both can be used together.

On the **Runs** list, use the **HTE pipeline** filter to see only runs in a given stage; the table includes a short **HTE** column for the current stage.

### Adding a new run
1. Go to **Runs** → **+ New Run**
2. Fill in the run details and outputs.
3. Add **input lots** (the biomass lots consumed by this run) and the weight used from each lot.
4. Save.

Before you save, the form now shows a live allocation summary:
- **Total allocated**
- **Target Lbs in Reactor**
- **Delta** (over / under / exact)

Each lot row also shows a projected remaining balance so you can see the impact before committing the run. The run will not save unless the selected lot weights add up exactly to **Lbs in Reactor**.

### Creating a run from Slack (optional)
If your account has **Slack Importer** access (or you are a Super Admin), you can promote a synced channel message into a **prefilled** new run:

1. Open **Slack imports** in the sidebar (or **Settings → View Slack imports** if you are a Super Admin).
2. Use **filters** (message date, channel, promotion status, mapping coverage) to find the row you want. Filter choices **persist while your session is active** when you navigate away and return—see **Saved filters, sorts, and list state**. Use **Remove filters** to reset. Rows that cannot be assigned a calendar date from the Slack timestamp are **not removed** solely because you set a date range (they still appear alongside in-range messages).
3. Click **Preview** to see mapped Run fields, ranked candidate source lots, and any suggested lot allocation.
4. If the Slack message refers to biomass going into a run, you can:
   - accept the suggested lot,
   - manually assign one lot, or
   - split the run across multiple candidate lots before leaving the preview page.
5. Choose one of these actions:
   - **Create run / Create run from Slack** when you want a prefilled run and may need a split allocation across multiple lots.
   - **Create extraction charge from Slack** when the message clearly maps to exactly one source lot, one reactor, and one biomass weight.
6. If you choose **Create run**, the app opens **New Run** with values filled from your active **Slack → Run** mapping rules and with your selected lot rows prefilled.
7. If you choose **Create extraction charge from Slack**, the app records the extraction charge immediately, then opens **New Run** with that saved charge attached.
8. Review everything before saving. Nothing is written to Runs until you save the run form.

**Roles:** Opening the Slack imports UI and the apply flow requires the **Slack Importer** flag (Settings → Users) or **Super Admin**. **Saving** the run still requires **User** or **Super Admin** (edit access). If you are a **Viewer** with Slack Importer, you can review the prefilled form, but Save stays disabled until an editor saves the run (or your role is upgraded).

**Second apply / duplicates:** If a run is already linked to the same Slack message (`channel` + message `ts`), the app warns you and asks for **explicit confirmation** before opening another prefilled run. Saving a second run is allowed after you confirm; use sparingly and soft-delete mistaken duplicates from **Runs** if needed.

**Traceability:** When you save a new run started from Slack apply, the run stores a **backlink** to that Slack message (`slack_channel_id`, `slack_message_ts`, and applied timestamp). The Slack imports list shows **Promotion** (not promoted vs linked runs) and **Coverage** (how completely mapping rules used the parsed payload—heuristic, not a guarantee of what you typed on the form).
Slack-created extraction charges also keep a backlink to the imported Slack message and show up on **Floor Ops** immediately because they are stored as normal `ExtractionCharge` records with source mode `slack`.

### What happens on save
- **Approved lots only:** you cannot allocate weight from a lot whose purchase is **not approved**; the app shows an error naming the batch. Approve the purchase on **Edit Purchase** (or complete the **Committed** approval path on **Biomass Pipeline**) first.
- **Exact allocation required:** the sum of your selected lot rows must match **Lbs in Reactor** exactly. If the total is over or under, fix the lot weights before saving.
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
- **Hard Delete (Super Admin)**: permanently removes run records for sandbox cleanup.

### Batch editing runs
From the **Runs** list, select two or more runs and use **Batch edit…** to change shared fields (see **Batch editing from list screens**). Yields and cost per gram are recalculated when relevant fields change.

---

## Departments
**Departments** opens a grid of team-focused pages. Each page includes:
- A short intro for that lens
- **Quick links** to existing screens (e.g. Runs, Inventory, Biomass Pipeline) with filters where helpful
- **Live rollups** (counts, last-30-day totals, pipeline snapshots—varies by department)

Examples:
- **Testing** — rollups for **HTE lab pipeline** (runs with dry HTE by stage) and supplier lab test activity; links to filtered **Runs** (e.g. awaiting lab, lab clean, dirty/strip queue).
- **Terpenes distillation** — strip queue vs stripped runs; terpene and retail distillate totals from runs marked stripped (recent window).

Use **Departments** for day-to-day orientation; all underlying data is the same as on **Runs**, **Purchases**, etc.

---

## Inventory
Inventory shows the current biomass position.

**Supplier** and **strain** filters are **saved for your session** while you work elsewhere; use **Remove filters** to clear them (see **Saved filters, sorts, and list state**).

### Summary tiles (top of the page)
- **On Hand**: total **remaining** pounds on lots from purchases that are **approved** and in statuses the app treats as on-hand (**delivered**, **in testing**, **available**, **processing**). Purchases still in **ordered** / **committed** / **in transit** (or not yet approved) do not contribute here.
- **In Transit**: total **stated** pounds on purchases that are committed, ordered, or in transit—not yet treated as on-hand inventory.
- **Total**: **On Hand + In Transit**—your combined pounds in-house and on the way.
- **Days of Supply**: how many days the **On Hand** amount would last at your configured **Daily Throughput Target** (Settings). **In-transit weight is not included** in this number; it only reflects material already on hand.

If you filter by **supplier**, all four summaries and both tables use that supplier. If you also filter by **strain** (text match on lot strain), only the **on-hand** table and the **On Hand** and **Days of Supply** tiles use that strain slice; **In Transit** (and the portion of **Total** that comes from in-transit) still includes every in-transit purchase for the selected supplier, not strain-filtered.

### Biomass On Hand
This table lists lots with remaining weight, including:
- Strain, supplier
- Original weight and **remaining** weight
- Potency (if recorded on the lot)
- Milled flag and location

Purchase editors see **Select all**, **Select none**, and **Batch edit…** above this table to change strain name, location, milled, potency, or notes on **multiple lots** at once (see **Batch editing from list screens**).

Each on-hand row now also gives direct action buttons:
- `Edit` opens a dedicated lot editor so you can change strain, potency, location, floor state, prep state, and notes without changing purchase-level status
- `Charge` opens the extraction-charge workflow
- `Scan` opens the scanned-lot execution page
- `Label` opens the printable lot label
- `Journey` opens the purchase journey filtered to that lot

Use **Inventory -> Import spreadsheet** when you need to update many existing lots at once from Excel or CSV.

That importer:
- matches rows by **Tracking ID**
- lets you remap spreadsheet columns before commit
- previews exactly which lot each row will update
- supports only the same safe lot-edit fields already available in `Edit`:
  - strain
  - potency
  - location
  - floor state
  - milled state
  - notes

It does **not** create lots or change:
- tracking IDs
- original lot weight
- remaining pounds
- live allocation balances

Lots may also show a **tracking ID**. This is the permanent machine-readable identity for that physical lot and now drives the printed barcode and scan route for that lot.

Where available, use the **Label** action from Inventory, Purchases, or Journey to print a lot-facing label page. The label now renders a printable **Code 39 barcode**, a **QR code**, and the scan route for that exact lot.
If you open **Label** from Inventory, the label page now returns you to Inventory instead of defaulting back to Purchases.

### Floor Ops
Use **Floor Ops** from the left navigation when you want a quick operator view of:
- recent barcode scans
- recent smart-scale captures
- open lot count
- active scale devices
- lots already staged and ready for extraction
- open lots still pending prep or testing
- a live board for the configured/observed reactors showing the current charge state
- pending extraction charges by reactor
- recently applied charges already linked to saved runs

The page now uses the same card treatment for the top snapshot metrics, extraction-readiness metrics, floor-state rollups, reactor queues, and recent activity lists so operators can scan it the same way as the rest of the site.

The page also rolls open lots up by floor state:
- in inventory
- in vault
- in reactor staging
- in quarantine
- custom movement

Each recent scan row includes an **Open Scan Page** shortcut back into the lot execution workflow.

The page now also includes a reactor-oriented extraction queue:
- **Active Reactor Board** shows each reactor as:
  - **Empty**
  - **Charged / waiting**
  - **Run linked**
- each reactor card shows the latest lot, charged lbs, charge time, queue depth, and the operator label when present
- when a reactor already has a saved run linked, the card exposes **Open Run**
- the current reactor card can also expose direct lifecycle actions:
  - **Mark In Reactor**
  - **Mark Running**
  - **Mark Complete**
  - **Cancel Charge**
- each lifecycle action writes a timestamped history entry to the extraction charge
- by default, **Mark Running** requires that the charge already has a linked run
- completed or cancelled charges stay visible on the board for the rest of the local day, then move to history-only visibility
- if you open a run from **Active Reactor Board** or **Recently Applied Charges**, the run form now shows **Back to Floor Ops** plus a separate **Open Runs** button so operators can return to the floor screen without losing context
- **Board view** lets operators focus the board on:
  - all reactors
  - active only
  - pending only
  - running only
  - completed today
  - cancelled today
- **Reactor History Today** shows the same-day charge and lifecycle milestones for each reactor, including linked run shortcuts where available
- **Pending Charges** summarizes lbs already charged into production but not yet linked to a saved run
- **Reactor Charge Queue** groups pending charges by reactor
- **Recently Applied Charges** shows charges that have already been finalized into saved runs and provides an **Open Run** shortcut

### Scan Center
Use **Floor Ops -> Open Scan Center** when you want to scan with a tablet or phone camera.

The scan center supports:
- browser-camera scanning on supported devices and browsers
- manual tracking ID entry
- Bluetooth barcode scanners that type into the input field

When the browser detects a supported barcode or QR code, it opens the scanned lot page automatically.

Camera notes:
- `http://localhost` works for local desktop testing
- tablets usually require HTTPS for camera access
- if camera scanning is not supported in the browser, use the manual field or a paired scanner

### Scanned lot execution
When the app opens `/scan/lot/<tracking_id>`, the page is optimized for floor execution.

Use **Open Charge Form** to choose one of these guided run-start modes:
- **Blank run form**: open the charge screen without a prefilled lbs amount
- **Use full remaining lot**: prefill the charge with the lot's full remaining lbs
- **Use partial amount**: enter a partial lbs amount before opening the charge screen
- **Scale capture first**: open the charge screen with scale-first guidance before the run is saved

On the charge screen, record:
- the actual lbs going into production
- the reactor
- the charge time
- optional notes

Saving the charge opens **New Run** with the lot allocation already attached. The charge is also stored as its own event for traceability before the run is finalized.

### Standalone run execution

Inside the standalone extraction app, use **Open Run** after a charge is recorded.

That screen inherits:
- reactor
- source lot / source summary
- strain
- biomass weight

It then lets extractors capture:
- run / fill timing
- biomass blend `% milled / % unmilled`
- number and weight of fills
- number and weight of flushes
- number of stringer baskets
- CRC blend
- notes

The timer-heavy fields use touch-first buttons instead of keyboard entry:
- `Start / Now`
- `Stop / Now`

The top of the run screen now shows the current stage and the next action buttons. The normal booth sequence is:

- **Confirm Vacuum Down**
- **Record Solvent Charge**
- **Start Primary Soak**
- **Start Mixer**
- **Stop Mixer**
- **Confirm Filter Clear**
- **Start Pressurization**
- **Begin Recovery**
- **Begin Flush Cycle**
- **Verify Flush Temps**
- **Record Flush Solvent Charge**
- **Start Flush**
- **Stop Flush**
- **Confirm Flow Resumed**
- **Start Final Purge**
- **Stop Final Purge**
- **Confirm Final Clarity**
- **Complete Shutdown**
- **Mark Run Complete**

Those actions write the matching timestamps and booth checkpoints automatically. When the run is marked complete, the run stores a completed timestamp and the linked extraction charge moves to completed as well when that charge is still the active reactor event.

### Supervisor booth review

On the main app `Run` edit screen, supervisors now have a `Booth Review` block above the editable extraction fields.

Use it to review:
- current booth stage
- timing status for primary soak, mixer, flush soak, and final purge
- configured timing policy for each booth timer
- deviation flags such as flow still adjusting or clarity not yet acceptable
- recent booth event history
- linked booth evidence uploads

If a timing step is configured as `Require supervisor override` and the operator finished short, the same `Booth Review` block now shows the active policy block message so supervisors can see why progression is paused.

This section is intended as a read/review surface first. Supervisors still make corrections through the normal run fields below it.

### Supervisor notifications

Supervisors now also have an in-app notification queue on the main `Dashboard`.

Use it to review:
- run completions
- booth timing misses that finished short of target
- booth exceptions such as `Flow adjustment required`
- booth exceptions such as `Final clarity still out of scope`
- reminder notifications when warning or critical booth alerts have stayed unresolved past the configured delay

Each notification shows:
- severity and class (`Completions`, `Warnings`, or `Reminders`)
- timestamp
- direct `Open run` link when the alert is tied to a run
- recent delivery status if Slack outbound delivery was attempted
- operator reason when the deviation required one
- supervisor override decision and reason when one has been recorded

Supervisors can:
- `Acknowledge` a notification when they have reviewed it
- `Approve Deviation` when the run may proceed or be accepted off-target
- `Require Rework` when the operator must correct the booth condition before the alert can be cleared
- `Resolve` a notification when the issue is fully closed

The app stores the notification first. Slack is only an optional outbound delivery channel and is not the system of record.

### GoldDrop Production Queue

The `GoldDrop Production Queue` is now a staged workflow instead of a single list of interchangeable actions.

Runs move through these stages:
- `New in queue`
- `Reviewed`
- `Queued for production`
- `In production`
- `Packaging ready`
- `Released complete`

The queue page now only shows the next actions that make sense from the current stage.

Typical flow:
- `Mark Reviewed`
- `Queue For Production`
- `Start Production`
- `Mark Packaging Ready`
- `Release Complete`

If the run should not stay in GoldDrop, use `Send Back For Re-routing`.

### Liquid Loud Hold

The `Liquid Loud Hold` is now also a staged workflow instead of a flat hold/release list.

Runs move through these stages:
- `New in hold`
- `Reviewed`
- `Reserved for Liquid Loud`
- `Release ready`
- `Released to GoldDrop queue` or `Released complete`

Typical flow:
- `Mark Reviewed`
- `Reserve For Liquid Loud`
- `Mark Release Ready`
- then either:
  - `Release To GoldDrop Queue`
  - or `Release Complete`

The release actions do not appear until the run is marked `Release ready`.

### Terp Strip / CDT Cage

The `Terp Strip / CDT Cage` is now a staged workflow instead of a flat strip-action list.

Runs move through these stages:
- `New in cage`
- `Reviewed`
- `Queued for Prescott`
- `Strip in progress`
- `Strip complete`

Typical flow:
- `Mark Reviewed`
- `Queue Prescott`
- `Start Strip Work`
- `Strip Complete`

The `Strip Complete` action does not appear until the run is marked `Strip in progress`.

Reminder automation:
- is configured under `Settings -> Slack Integration`
- can be enabled or disabled separately from outbound Slack delivery
- defaults to one durable reminder per unresolved alert after the configured age threshold
- uses separate delay thresholds for `critical` vs `warning` supervisor alerts

### Operator deviation reasons

When the booth workflow records an off-target or exception condition, the operator must now enter a reason before the step can be submitted.

Current required-reason cases include:
- mixer finished short of target
- flush soak finished short of target
- final purge finished short of target
- flow still adjusting
- final clarity not yet acceptable

Those reasons are stored in the booth event trail and shown to supervisors in the dashboard notification queue and on the run's `Booth Review` panel.

### Post-extraction handoff (Phase 1)

After **Mark Run Complete**, the same standalone run screen opens the first downstream handoff step.

1. Choose the **Downstream pathway**:
- `100 lb pot pour`
- `200 lb minor run`

2. Tap **Start Post-Extraction**.
- The extraction run must already be complete.
- A pathway must be selected first.

3. Enter the initial output weights:
- `Wet HTE (g)`
- `Wet THCA (g)`

4. Tap **Confirm Initial Outputs**.
- Both wet output fields are required before confirmation.
- The run stores the downstream start time and the initial-output confirmation time.

This is the current Phase 1 foundation only. The later THCA-path / HTE-path workflow screens are still planned. For now, the system stores the chosen pathway and the initial downstream handoff on the run itself so the team has a structured starting point for post-extraction orchestration.

### Downstream state tracking (Phase 2)

The same run screen now stores the first structured downstream fields instead of leaving that state in Slack or free-text notes.

#### Pot pour path

Use these fields when the downstream pathway is `100 lb pot pour`:
- `Warm Off-Gas Start`
- `Warm Off-Gas End`
- `Daily Stirs`
- `Centrifuged At`

#### THCA path

Use these fields to track the THCA side after the run:
- `THCA Oven Start`
- `THCA Oven End`
- `Milled At`
- `THCA Destination`

`THCA Destination` supports:
- `Sell THCA`
- `Make LD`
- `Formulate in badders / sugars`

#### HTE path

Use these fields to track the HTE side after the run:
- `HTE Off-Gas Start`
- `HTE Off-Gas End`
- `Clean Decision`
- `Filter Outcome`
- `Prescott Processed At`
- `Potency Disposition`
- `Queue Destination`

Typical queue / disposition values now supported:
- `GoldDrop production queue`
- `Liquid Loud hold`
- `Terp stripping / CDT cage`
- `Hold for HP base oil`
- `Hold to be made into distillate`

This is still not the final downstream operator workflow. It is the structured data foundation for the later guided THCA / HTE workflow screens.

### Guided downstream workflow on the iPad

The standalone extraction app now turns the downstream portion of **Open Run** into a guided sequence instead of leaving operators on one flat form.

The sequence is:

1. Choose the downstream pathway.
2. Start post-extraction.
3. Confirm the initial wet THCA / wet HTE outputs.
4. Follow the branch-specific steps:
- `100 lb pot pour`:
  - warm off-gas
  - daily stir count
  - centrifuge handoff
- `200 lb minor run`:
  - THCA branch
  - HTE branch

The key difference is that the screen now works top-to-bottom, with numbered step cards and tap-first choice buttons for pathway and decision fields. The main app still keeps the full raw fields for supervisor editing.

Use **Open in Main App** only when a supervisor needs the full admin run form.

### Supervisor Console

Use **Downstream -> Supervisor Console** as the supervisor's first page during daily operations.

The console shows:
- launch role coverage for buyer, receiver, extractor, and supervisor
- supervisor alert counts and recent alert cards
- active downstream queue counts
- unassigned, stale, and blocked queue pressure
- queue health by destination
- supervisor attention items with direct run links

Use this page to decide where to go next: Floor Ops for reactor/floor context, Alerts for notification work, Journey for tracing and finance, Queue Overview for routing, or a destination queue for focused downstream work.

### Launch Readiness

Super Admins can use **Settings -> Launch Readiness** to manage the launch blocker register.

The register starts with default acceptance items for:
- buyer workflow
- receiving and inventory workflow
- extraction SOP workflow
- supervisor/downstream workflow
- Journey, cost, and revenue validation
- production data readiness
- backup/restore rehearsal
- deployment rehearsal
- final security handoff readiness

Classify each item as `Launch blocker`, `Pilot blocker`, `Post-launch`, or `Wishlist`. Use the status, owner, target date, and notes fields to keep the launch path separate from future polish.

### Downstream Queues in the main app

After a completed run has started post-extraction and the initial wet outputs are confirmed, supervisors can use **Downstream Queues** in the left sidebar to manage the next destination without opening every run one by one.

The page currently groups runs into:
- `Needs Queue Decision`
- `GoldDrop production queue`
- `Liquid Loud hold`
- `Terp strip / CDT cage`
- `HP base oil hold`
- `Distillate hold`

For each queue card, the page shows:
- run date and reactor
- source strain / supplier / tracking IDs
- wet and dry THCA / HTE totals
- linked derivative lots when genealogy output lots already exist for that run
- current THCA destination and HTE decision context when available
- a direct **Open Run** action

When derivative lots are shown on a queue card, use the journey links there to open manager-facing lineage context without leaving the downstream queue workflow first.

Use the destination dropdown on a queue card to:
- move a run to another downstream queue
- move it into a potency-based hold
- or mark the downstream queue item complete

Each active downstream queue card also shows `Queue owner`.

Use the owner dropdown on a queue card to:
- assign the item to a specific editor
- reassign it to a different editor
- or set it back to `Unassigned`

This ownership control only applies once a run is in an active downstream destination or hold. It is not used for `Needs Queue Decision`.

The shared downstream board now also includes queue reporting:
- `Blocked`
- `Stale 3+ Days`
- `Completed 7 Days`
- `Rework 30 Days`

Each queue card also shows `Queue age`, plus `Blocked` or `Stale` status when applicable.

When you open a run from this page, the main run form now shows **Back to Downstream Queues** so you can return to the same supervisor queue surface.

### GoldDrop Production Queue

`GoldDrop production queue` now also has its own dedicated page for the first destination-specific downstream workflow.

Open it from:
- **Downstream Queues** using **Open GoldDrop Queue**

Use this page when a run is already routed to `GoldDrop production queue` and you need to track what happened next.

Each queue card shows:
- current queue state
- source strain / supplier / lot context
- wet and dry THCA / HTE totals
- linked derivative lots with direct journey links when genealogy output lots already exist
- current queue owner when assigned
- queue history with timestamps and operator names

Available actions:
- `Mark Reviewed`
- `Queue For Production`
- `Release Complete`
- `Send Back For Re-routing`

Use **Queue note (optional)** to capture a short planning or handoff note alongside the queue action.

Use the queue-owner dropdown on the card when you need explicit accountability for who currently owns that GoldDrop item.

`Release Complete` removes the run from the GoldDrop queue.

When a GoldDrop item reaches `Release Complete`, the genealogy layer can now create a first-class `golddrop` derivative lot linked back to the original dry HTE lot and all upstream biomass ancestry.

`Send Back For Re-routing` removes it from the queue so it can be routed again from **Downstream Queues**.

### Liquid Loud Hold, Terp Strip / CDT Cage, and HP Base Oil Hold

The other downstream destinations now also have dedicated workflow pages reached from **Downstream Queues**:
- **Open Liquid Loud Hold**
- **Open Terp Strip Cage**
- **Open HP Base Oil Hold**

Use these when a run has already been routed to that downstream destination and you want a cleaner operational surface than the generic routing board.

These pages also show and edit the same `Queue owner` assignment used on the shared downstream board.

#### Liquid Loud Hold
- `Mark Reviewed`
- `Reserve For Liquid Loud`
- `Release To GoldDrop Queue`
- `Release Complete`
- `Send Back For Re-routing`

`Release To GoldDrop Queue` moves the run directly into the dedicated **GoldDrop Production Queue** and preserves queue history on both sides.

#### Terp Strip / CDT Cage
- `Mark Reviewed`
- `Queue Prescott`
- `Start Strip Work`
- `Strip Complete`
- `Send Back For Re-routing`

Typical staged flow:
- `Mark Reviewed`
- `Queue Prescott`
- `Start Strip Work`
- `Strip Complete`

`Queue Prescott` marks the HTE filter outcome as needing Prescott handling. `Start Strip Work` marks the run as actively in terp strip / CDT handling. `Strip Complete` does not appear until strip work has started, and then removes the run from the cage while marking the HTE pipeline stage as stripped.

When `Strip Complete` is recorded, genealogy can now create a `terp_strip_output` child lot from the accountable dry HTE lot.

#### HP Base Oil Hold
- `Mark Reviewed`
- `Confirm Hold`
- `Mark Release Ready`
- `Release Complete`
- `Send Back For Re-routing`

Typical staged flow:
- `Mark Reviewed`
- `Confirm Hold`
- `Mark Release Ready`
- `Release Complete`

This page is for low-potency output held for HP base oil decisions. `Release Complete` does not appear until the hold is marked release-ready.

When `Release Complete` is recorded here, genealogy can now create an `hp_base_oil` child lot from the accountable dry HTE lot.

### Distillate Hold

`Distillate Hold` is now also a dedicated downstream destination page reached from **Downstream Queues -> Open Distillate Hold**.

Use it when high-potency output is being held to be made into distillate.

Actions:
- `Mark Reviewed`
- `Confirm Hold`
- `Mark Release Ready`
- `Release Complete`
- `Send Back For Re-routing`

Typical staged flow:
- `Mark Reviewed`
- `Confirm Hold`
- `Mark Release Ready`
- `Release Complete`

This mirrors the HP base oil hold pattern, but for the distillate path instead of the low-potency hold path. `Release Complete` does not appear until the hold is marked release-ready.

When `Release Complete` is recorded here, genealogy can now create a `distillate` child lot from the accountable dry HTE lot. If retail distillate grams are already recorded on the run, that quantity is used as the accountable distillate output.

Use **Confirm Movement** to record a standard movement action:
- move to vault
- move to reactor staging
- move to quarantine
- move back to inventory
- or store a custom location detail

### Genealogy Report

Use **Genealogy Report** from the left sidebar when you need a manager-facing summary of material lineage instead of a single run or queue card.

The page currently shows:
- product financial summary rows by material type
- open derivative inventory by type
- released derivative inventory by type
- projected revenue, actual revenue, and variance for open and released material
- source-to-derivative yield rows by biomass lot
- run-level yield and cost review rows
- actual revenue and projected-vs-actual variance for source descendants and run yield/cost rows when revenue events exist
- rework volume from correction-backed genealogy transformations
- correction impact on reported yield
- open genealogy reconciliation issues
- recent derivative lots with direct viewer / raw lineage links

From that report, use **Open Journey Viewer** or any linked derivative lot to open the HTML genealogy viewer.
Use **Export Financial CSV** to download the financial reporting rows for spreadsheet review.

The **Material Journey Viewer** supports:
- `By Lot`: start from a material lot and trace upstream inputs plus downstream child lots
- `By Run`: start from an extraction run and trace source lots, allocations, and derivative outputs
- **Journey Graphic**: a live source-to-product map that shows supplier/source biomass, the extraction or transformation step, and derivative product lots such as THCA, HTE, GoldDrop, HP base oil, distillate, or terp strip outputs
- in `By Lot`, the viewer now also shows:
  - open reconciliation issues on that lot
  - correction history for that lot
  - a direct `Correct This Lot` action
  - a `Revenue Actuals` panel with projected revenue, actual revenue, variance, actual margin, and the event history recorded for that lot

To record actual revenue for a material lot, open the lot in **Material Journey Viewer**, use **Record Revenue**, and enter:
- event date
- sold quantity
- unit price
- buyer or channel
- optional reference and notes

The app stores the total actual revenue event against that material lot. Journey Home and Genealogy Report then use that actual revenue to compare real results against the configured Journey revenue assumptions.

If a revenue entry is wrong, use the inline **Update** controls on that event row. If the entry should no longer count, enter a reason and use **Void**. Voided events stop contributing to actual revenue but remain visible in the voided history for audit purposes.

Financial completeness flags:
- **Missing cost basis** means the lot has quantity but no rolled cost basis.
- **Missing revenue assumption** means Settings does not have an assumed selling price for that lot type.
- **Missing actual revenue** means a released lot has no revenue event yet.
- **Open genealogy issue** means lineage or reconciliation problems may affect financial reporting.

Use `View JSON` when you want the exact underlying payload for the current viewer page.
On the report table, `Ancestry JSON` and `Descendants JSON` expose the raw lineage payloads for that lot.

Use the viewer when you need a path-tracing answer instead of just a summary, for example:
- start from a distillate or GoldDrop lot and trace it back to its biomass source lots
- start from a run and see every accountable derivative lot created from it
- move from a downstream queue card into the full lineage for a linked derivative lot
- find a genealogy problem and move directly into correction from the same lot view

In `By Run`, the `Run Reconciliation` section highlights:
- open genealogy issues attached to the run
- source-allocation exceptions already detected on that run journey
- links into any affected derivative lots

### Genealogy Issue Queue

Use **Open Issue Queue** from the genealogy report or viewer when you want to manage unresolved lineage problems across runs and lots.

The queue supports:
- owner assignment
- statuses:
  - `open`
  - `investigating`
  - `needs follow-up`
  - `resolved`
- working notes on the issue
- recent audit history for issue updates
- explicit lifecycle actions:
  - `Start Investigating`
  - `Mark Follow-Up`
  - `Resolve With Note`
  - `Reopen`
- queue filters for:
  - status
  - severity
  - owner
  - age / overdue state
- reminder tracking for stale unresolved issues

Use it when you need to:
- assign a lineage problem to a specific person
- mark an issue as actively being worked
- keep investigation notes on the issue itself
- review which issues are still unresolved
- focus only on overdue or critical genealogy problems

When you record a lot correction from the genealogy viewer, the correction form now also asks what to do with linked genealogy issues:
- resolve them immediately
- keep them in follow-up
- or leave them open with an updated note

Use the report’s cost/yield sections when you need to answer:
- which source lots produced which derivative outputs and cost basis
- which runs now look correction-heavy
- where rolled-forward derivative cost is concentrated across recent runs

Use this page for questions like:
- what derivative inventory is still open by type
- what product lots have already been released
- which biomass lots fed a finished GoldDrop, distillate, or wholesale THCA lot
- where genealogy still has unresolved reconciliation problems

Use **Confirm Testing** to update testing state without opening the purchase form.

The **Recent Scan Activity** section records these floor actions with context, including:
- guided run-start mode
- extraction-charge lbs / reactor / timestamp
- planned partial lbs
- movement action and location
- testing confirmations

### Starting extraction from the main app
You do not have to scan a label first.

From **Purchases -> Edit**, the **Lots** table now includes **Charge Lot** for any active lot with remaining inventory. That opens the same extraction-charge workflow used by the scan page, so office or desktop users can record:
- source lot
- lbs charged
- reactor
- charge time
- notes

### In Transit / On Order
This table lists purchases that are not yet fully received, including:
- Supplier and status
- Stated weight
- Order date and expected delivery
- Price per lb (if known)

Purchase editors see **Select all**, **Select none**, and **Batch edit…** above this table to update several in-transit purchases at once (same as batch edit on **Purchases**).

### Days of Supply (detail)
Same as the **Days of Supply** summary tile: **on-hand lbs ÷ Daily Throughput Target**. It does not add in-transit pounds. If the target is zero or unset in a way that makes it zero, the app shows **0** days.

---

## Purchases (Batches)
Purchases are batch-level records used for pricing, receiving, and inventory creation.

On the **Purchases** list, use **Apply filters** for supplier, **purchase date range**, potency range, and optional **Hide complete & cancelled**. Status chips (**All**, **Committed**, **Ordered**, …) keep your other filters where possible. Filter and status choices **persist for your session** when you leave the page and come back—see **Saved filters, sorts, and list state**. **Remove filters** clears saved list state for Purchases.

### Batch IDs
Each purchase has a **unique Batch ID** (human-readable). You can:
- **Leave it blank** to auto-generate, or
- Enter a custom Batch ID (must be unique)

Batch IDs are used across the app to make batches easy to identify and to link into the Biomass Pipeline.

### Batch Journey (purchase timeline)
You can open a per-batch timeline from:
- **Purchases** list → **Journey** button on the row
- **Edit Purchase** → **View Journey** button

The Journey page shows derived lifecycle stages:
- declared, testing, committed, delivered, inventory, extraction, post-processing, sales

Each stage includes:
- status badge
- timestamps (when known)
- key metrics
- links back to source records

The Journey page now also shows:
- **Inventory lots** for the purchase, including remaining weight, allocated weight, potency, clean/dirty state, testing state, and tracking ID when available
- **Run allocations** showing which runs consumed which lots and how much weight was allocated into each run

Exports:
- **Export JSON**
- **Export CSV**
- If a bad export format is requested (for example, from a copied/custom URL), the app returns a clear error instead of silently changing formats.

Archived rows:
- Super Admin can include archived data using the **Include archived** toggle.

### Creating a new purchase
1. Go to **Purchases** → **+ New Purchase**
2. Choose supplier, purchase date, status, and weight/pricing fields.
3. (Optional) add lots/strains for the purchase at creation time.
4. Save.

When a lot is created or later approved into active inventory, the app now assigns it machine-readable tracking fields so it is ready for future labels and scan-based workflows.

### Editing purchase details created from iPad / mobile opportunity intake
The mobile opportunity flow and the main purchase form now save to the same purchase fields.

On **Edit Purchase**, review or update:
- **Availability Date**
- **Testing Notes**
- normal purchase notes, weights, pricing, and status fields

If a buyer created or edited the opportunity on iPad first, those values should now be visible on the main purchase form and stay saved when you save the purchase from the desktop app.

### Importing purchases from a spreadsheet
Use **Purchases** → **Import spreadsheet** when you have many purchases in Excel or CSV (for example accounting exports with **Vendor**, **Purchase Date**, **Invoice Weight**, **Actual Weight**, **Manifest**, **Amount**, **Paid Date**, **Payment Method**, **Week**).

1. Drag a **.csv**, **.xlsx**, or **.xlsm** file onto the drop zone (or click to browse). Upload starts automatically after you pick a file.
2. The app finds a header row and suggests mappings for familiar column names. On the preview page, adjust any column mappings you want before importing.
3. Choose which valid rows to import. You can turn on **Create missing suppliers** so new vendor names become supplier records (matched case-insensitively by name).
4. Confirm import.

**Tips:** A **Download sample CSV** link on the import page shows expected-style headers. If **purchase date** is empty but **paid date** is filled, the app may use paid date as the purchase date. If **invoice weight** is empty but **actual weight** is present, actual weight can stand in for stated weight. **Amount** is stored as **total cost**; **Week** / paid date / payment method are added to **notes** for traceability. The preview mapper now also supports purchase workflow fields such as **Availability Date**, **Testing Notes**, **Delivery Notes**, **Testing Timing / Status / Date**, and single-lot fields like **Strain**, **Lot location**, **Floor state**, **Milled**, **Lot potency**, and **Lot notes**.

**Approval:** Imported rows are created **without** automatic approval. If a row’s status would normally put material **on hand**, the app stores a non-on-hand status (typically **ordered**) until someone **Approves** the purchase and sets the correct status on **Edit Purchase**.

This path is **only for purchases**. The sidebar **Import** screen is for **run** history from Google Sheets—see **Import (CSV)** below.

### Potency-based pricing and true-up
Purchases support:
- Stated potency and tested potency
- Price per lb (can be entered directly)
- True-up amount calculation when potency changes and actual weight is known

### Purchase approval and status
- **Approve purchase** (top of **Edit Purchase**, and now inline on **Purchases** and **Biomass Pipeline** list rows for eligible approvers): sets **Approved** with a timestamp. Until then, a yellow banner explains that material **cannot** be used in extraction runs or appear in **On Hand** inventory.
- You **cannot** set on-hand statuses (**Delivered**, **In testing**, **Available**, **Processing**) until the purchase is approved; try **Approve purchase** first, then change status.
- **Biomass Pipeline** and **Purchases** are the **same records**: changing status on either screen is changing that purchase.

### Purchase deletion
- **Delete Purchase** performs a safe (soft) delete.
- **Hard Delete (Super Admin)** is available for sandbox cleanup when no run history depends on the purchase.

### Adding lots to an existing purchase
Open a purchase and use “Add Lot to This Purchase” to add strain lots. Lots create inventory that can be consumed by runs.

### Splitting a confirmed lot
If a confirmed purchase already has a lot in inventory and you need to break part of it into a second lot, open **Edit Purchase** and use **Split Existing Lot**.

1. Choose the existing lot from the dropdown.
2. Enter the split weight.
3. Optionally set a different strain name, location, potency, or notes on the new child lot.
4. Submit **Split Lot**.

Rules:
- the split weight must be greater than zero
- the split weight must be less than the source lot's current remaining inventory
- the original lot keeps the remaining balance
- the new child lot gets its own tracking ID and can be used independently in later runs

### Supporting documentation (photos and scans)
On **New Purchase** and **Edit Purchase**, use the **Supporting documentation** section to attach files that should stay with the batch record (contracts, scans, invoices, COAs, photos, etc.).

- **Who can upload:** **User** or **Super Admin** (same as saving purchases). Viewers cannot upload.
- **Formats:** JPG, JPEG, PNG, WEBP, HEIC, HEIF, and PDF.
- **Size limit:** up to **50 MB per file**.
- Choose a **category**, optional **title**, and optional **tags** (comma-separated) for the batch you are uploading; then click **Save Purchase** (at the **top** or **bottom** of the form) to store the files.
- After save, files appear under **Supporting documents on file** on the purchase (with **Delete** for editors) and in the **Photo Library** (filter by purchase if needed).
- **Field intake audit photos** (from approved biomass/purchase field forms) are listed separately on the purchase; those are not replaced by this upload area and are managed through the field submission workflow.

### Batch editing purchases from the list
Select two or more rows on the **Purchases** list, then **Batch edit…**, to set **status**, **delivery date**, **queue placement**, or **append notes** for all selected purchases at once. See **Batch editing from list screens** for limits (current page only, weekly budget rules).

---

## Biomass Pipeline
The Biomass Pipeline is a **view of the same purchase batches** you see under **Purchases**. Early work uses statuses **Declared** and **Testing** (stored as **`declared`** and **`in_testing`**); later stages match normal purchasing (**Committed**, **Delivered**, **Cancelled**). Each row has a **Batch ID** and optional **lots** for strain tracking.

List **filters** (supplier, **availability date range**, strain text) and bucket/stage context are **saved for your session** when you navigate elsewhere—see **Saved filters, sorts, and list state**. Use **Remove filters** to clear.

**Buckets:** **Current** / **Old Lots** / **All** / (Super Admin) **Archived** control how **Declared** and **Testing** rows age out; **Committed** and later stages normally stay on **Current**. See on-screen help text for the day thresholds (settings: **potential lot** aging).

Editors can use **Select all** / **Select none** and **Batch edit…** on the pipeline list to change **stage**, **testing** fields, or **notes** on multiple rows (see **Batch editing from list screens**). Batch edit updates **`Purchase`** records directly.

### Stages (UI → system)
- **Declared** — early declaration (`declared`): availability date, declared weight/price, estimated potency, optional strain/lot
- **Testing** — in-pipeline testing (`in_testing`): timing, status, optional tested potency and date
- **Committed** — firm buy (`committed`): committed dates/weight/price; **requires a purchase approver** (or **Super Admin**); approval is recorded when you enter this stage
- **Delivered** — must follow **Committed**; same rules as purchases for receiving
- **Cancelled** — batch cancelled

### Creating a pipeline record
1. Go to **Biomass Pipeline** → **+ New Availability**
2. Fill Step 1 (Declaration)
3. Optionally fill Step 2 (Testing) and Step 3 (Commitment)
4. Set the Stage and Save

You can open the same batch anytime from **Purchases** (search by **Batch ID** or supplier). There is **no separate “link” step**—one row serves both screens.

### Approvers and Committed
Only **Super Admin** or users with **purchase approval** permission may move a batch **into** or **out of** **Committed** (and therefore control the approval stamp tied to that transition). If you lack permission, ask an approver to edit the batch or adjust your user flag in **Settings**. If you do have permission, you can approve directly from the **Biomass Pipeline** row without opening the form first.

### Adding field photos
Field intake for biomass declarations (and purchase requests) still supports optional photo uploads; stored paths attach to the resulting **purchase** record.

What users can do:
- Attach multiple photos from camera or gallery before submitting.
- On the **Potential Purchase** form there are three separate buckets: **Supplier / License**, **Biomass**, and **Testing / COA**—each can hold many photos, independently.
- On the **biomass declaration** field form, there is one photo bucket for the declaration.
- **Mobile / in-app browser:** each photo uses its own native file control (not a merged list), so submission works reliably on iPhone and embedded webviews. Tap **Add photo**, then on the new row tap **Take or choose photo** (camera or gallery). Repeat **Add photo** for more images.
- **Remove before submit:** each row has **Remove** to unselect that photo before you send the form (empty rows are discarded on submit).
- Each section allows up to **30** images by default (configurable by your administrator via `FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET`).
- Upload formats: JPG, JPEG, PNG, WEBP, HEIC, HEIF (images only on field intake).
- Max size per image: **50 MB**.

What admins can see:
- In **Settings**, pending field submissions show categorized thumbnails (supplier/license, biomass, testing/COA).
- Clicking a thumbnail opens the full image in a new tab.

### Office purchase opportunities
The **Biomass Purchasing** button now creates the same underlying **Purchase opportunity** record used by the standalone buyer app.

What that means:
- Office-created opportunities no longer create a separate pending submission object.
- They appear directly in **Purchases** and use the normal purchase approval flow.
- The older **Field purchase approvals** screens now refer specifically to external or field-intake submissions.

### Updated mobile purchase form fields
The field purchase form supports:
- Harvest date
- Storage note
- License information
- Queue placement (Aggregate, Indoor, Outdoor)
- Testing/COA status text
- Optional strain names on lot lines
- Optional lot weights on lot lines

### Validation and error messages
If something is missing or invalid (bad date, negative weight, invalid stage), you’ll see a clear error message. Fix the input and save again.

---

## Costs (Operational Costs)
Use Costs to capture operating expenses that should be included in run $/g.

**Cost type** chips and the **start/end date** filters on the list are **saved for your session** while you work in other sections—see **Saved filters, sorts, and list state**. **Remove filters** clears them.

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

Editors can **Batch edit…** from the **Costs** list to change **cost type** or **append notes** on multiple entries (see **Batch editing from list screens**).

---

## Suppliers (Performance)
Suppliers shows performance analytics by farm, including:
- All-time and recent averages (yield %, THCA %, cost/gram)
- Last-batch performance snapshot
- Best-yielding supplier month-over-month spotlight

Supplier profiles also include:
- Historical lab test records (attach result files: images or PDF, up to **50 MB per file**)
- Supplier lab attachments (COAs/results/licenses; images or PDF, up to **50 MB per file**)
- Field-approved supplier/license photos are automatically added into supplier attachments

**Deleting supplier files:** Remove lab test rows or supplier attachments from the supplier profile; that also drops the linked Photo Library entries for those uploads.

If the “exclude runs missing $/lb” setting is enabled, these analytics ignore runs with incomplete biomass pricing.

Editors can use **Select all** / **Select none** and **Batch edit…** from the supplier cards area to **activate/deactivate** suppliers or **append notes** (see **Batch editing from list screens**). Checkboxes appear next to each supplier card title.

When creating a supplier from the main **Add Supplier** screen, the app now warns if the name is very close to an existing active supplier. Review the suggested matches before saving a new supplier.
If it really is a different supplier with a similar name, use the explicit confirmation option on that screen to keep both records.

Super Admins can also open a supplier record and use **Merge Supplier** to combine duplicates safely. The merge screen shows an impact summary first, then archives the source supplier, moves linked records to the target supplier, and keeps lineage and audit history intact.

### Importing suppliers from a spreadsheet
Use **Suppliers** -> **Import spreadsheet** when you have many suppliers in Excel or CSV.

1. Drag a **.csv**, **.xlsx**, or **.xlsm** file onto the drop zone (or click to browse). Upload starts automatically after you pick a file.
2. The app finds a header row and suggests mappings for columns like supplier name, contact name, phone, email, location, notes, and active status.
3. On the preview page, adjust any column mappings you want before importing.
4. Review the action column:
   - **Create** means the row will create a new supplier.
   - **Update** means the supplier name already matches an existing supplier exactly.
5. If you want exact name matches to overwrite the existing supplier, turn on **Update existing suppliers** before importing.
6. Confirm import.

**Tip:** The preview also shows possible duplicate hints for new suppliers with close-but-not-exact names, so you can catch typo-close rows before creating more cleanup work.

---

## Strains (Performance)
Strains compares yield/cost metrics grouped by strain + supplier.

Your **All time / Last 90 days** choice **persists for your session** when you navigate away and return—see **Saved filters, sorts, and list state**. **Remove filters** restores the default (All time).

If the “exclude runs missing $/lb” setting is enabled, these analytics ignore runs with incomplete biomass pricing.

Editors can select two or more rows and use **Batch rename…** to set one **new strain name** on all **purchase lots** that match each selected strain+supplier combination. Read the warning on the batch screen—this is a bulk rename, not the same as editing a single lot (see **Batch editing from list screens**).

### Importing strain renames from a spreadsheet
Use **Strains** -> **Import spreadsheet** when you have many strain label cleanups to apply at once.

1. Drag a **.csv**, **.xlsx**, or **.xlsm** file onto the drop zone (or click to browse). Upload starts automatically after you pick a file.
2. The app finds a header row and suggests mappings for:
   - **Supplier name**
   - **Current strain name**
   - **New strain name**
   - optional **Notes**
3. On the preview page, adjust any column mappings you want before importing.
4. Review the **Matched lots** column to confirm how many purchase lots will be renamed for each row.
5. Confirm import.

**Important:** This importer does **not** create a separate strain master record. It safely renames the `strain_name` on matching purchase lots for the supplier/current-strain pair you specify.

---

## Photo Library
The Photo Library is a single place to **search and preview** media that is tied to suppliers, purchases, field submissions, lab tests, and manual uploads.

### Who can do what
- **View / filter:** anyone signed in (**Viewer** and up).
- **Upload and delete (limited types):** **User** or **Super Admin** only.

### Browsing
Use search (tags, title, path text) and filters for supplier, purchase, and category. Open any thumbnail or PDF tile to view the file in a new tab.

### Uploading (editors)
At the top of **Photo Library**, use **Upload to library**:
- **Formats:** images and PDF (same extensions as supplier lab uploads).
- **Size limit:** **50 MB per file**.
- Optionally set **category**, **title**, **tags**, and link a **supplier** and/or **purchase** so the asset appears under the right filters.

### Deleting (editors)
- **Manual library uploads** and **supporting documents uploaded on a purchase** can be removed from the grid (**Delete** on the card). The app deletes the file on disk when nothing else references that path.
- Assets created by **field intake**, **supplier lab tests**, or **supplier attachments** **cannot** be deleted from the Photo Library alone—use the field workflow or the supplier record (delete the lab test row or attachment) so data stays consistent.

### Relationship to other screens
- Purchase **Supporting documentation** uploads are stored as photo-library assets linked to that purchase.
- Field submission photos appear with source **field_submission**; purchase pages also show them under **Field intake audit photos**.

---

## Settings (Super Admin)
Settings control system behavior and performance targets.

### Operational Parameters
Includes:
- Potency rate used for potency-based pricing
- Reactor count/capacity
- Throughput targets
- Reactor lifecycle controls:
  - show or hide `In Reactor`, `Running`, `Completed`, and `Cancelled`
  - make lifecycle states required before later transitions
  - require a linked run before **Mark Running**
  - show or hide state history on the **Active Reactor Board**
- Optional analytics filter: **Exclude runs missing biomass pricing ($/lb)**
- Cost allocation method: **Uniform**, **Split 50/50**, or **Custom split**
- Site identity for internal API consumers:
  - `site_code`
  - `site_name`
  - `site_timezone`
  - `site_region`
  - `site_environment`

### KPI Targets
Set KPI targets and green/yellow thresholds to match operational goals.

### Users
Admins can create users and assign roles. (This manual does not include any credentials.)
- Disabled users can be reactivated.

### Access Control
Use **Settings -> Access Control** to grant or revoke access separately from creating a user.
- Role templates define the default permissions for Viewer, Super Buyer, User, and Super Admin.
- Per-user overrides can temporarily grant or revoke individual permissions without changing the user's base role.
- Import and export are separate permissions, so someone may be allowed to view a screen without being allowed to bulk import or export data.
- Standalone purchasing, receiving, and extraction access is controlled from the same screen.
- Finance and Journey actions such as financial export, revenue recording, revenue voiding, and genealogy correction have their own permissions.

### Audit Log
Use **Settings -> Audit Log** to investigate operating history.
- Filter by date range, user, action, entity type, and text/details.
- Open details to review structured JSON audit payloads such as import source, mobile workflow, revenue edits, correction notes, and access-control updates.
- This is intended for transparency, troubleshooting, and management review; it does not replace final security hardening.

### API Clients
Super Admin can manage bearer-token clients for the internal read-only API under **Settings -> API Clients**.
The available scopes are populated from the same API registry used by `/api/v1/capabilities`, so the client setup screen stays aligned with the implemented Internal API endpoints.
- Create a named client and choose its read scopes.
- The raw bearer token is shown only once when the client is created.
- Clients can be revoked, reactivated, and deleted later from the same table.
- The table also shows **Last Used** plus the last endpoint/scope the token touched, which helps with internal audit and troubleshooting.
- The same section now shows a **Recent API Request Log** so you can quickly see which client hit which endpoint, with method, scope, status, and timestamp.

### Remote Sites
Super Admin can manage cross-site cache registrations under **Settings -> Remote Sites**.
- Register a remote site with its base URL, optional bearer token, and notes.
- Pull an individual site on demand to cache its current site identity, manifest, and summary payloads locally.
- Remote pulls now also cache supplier-performance and strain-performance payloads for cross-site comparison.
- Disable a site without deleting it.
- Delete only after it has been disabled.

### Maintenance: Pull all remote sites
Use **Pull all remote sites** in **Settings -> Maintenance** to refresh the local cache from every active remote-site registration at once.

Server-side equivalent:

```bash
source venv/bin/activate
python scripts/pull_remote_sites.py
```

### Fresh start / operational reset

If you want to start over with a clean operating database but still keep login access and financial settings, use the server-side reset script instead of deleting the database file manually.

The supported reset keeps:
- users and passwords
- system settings and KPI targets
- Slack sync configuration
- cost entries
- scale-device configuration

It clears:
- purchases, lots, runs, and run inputs
- Slack imports
- field submissions and field access tokens
- suppliers, related attachments/tests/photos
- audit/history rows

Run from the project root on the server:

```bash
source venv/bin/activate
python scripts/reset_operational_data.py --yes
sudo systemctl restart golddrop
```

If you explicitly want demo/historical data in a fresh environment, seed it separately:

```bash
source venv/bin/activate
python scripts/seed_demo_data.py --yes
sudo systemctl restart golddrop
```
- Permanent delete is available only when no historical audit activity exists.
- **Slack Importer:** For accounts that are not Super Admin, you can grant **Slack import** (sidebar **Slack imports**, preview, and apply-to-new-run). Super Admins always have this capability. Optionally check **Slack Importer** when creating a user. Editors with this flag can complete the full apply flow; **Viewer + Slack Importer** can review prefilled runs but cannot save them.

### Field links/tokens
- Tokens can be revoked immediately.
- Revoked or expired tokens can be deleted from the table to keep Settings clean.

### Slack integration
- **Production events URL:** For the current production server, use `https://3.230.126.196/api/slack/events` in the Slack app's **Event Subscriptions -> Request URL** field unless the public hostname changes.
- **Where to find each Slack value:**
- **Webhook URL:** Slack app -> **Features -> Incoming Webhooks**. Turn on **Activate Incoming Webhooks**, then install or reinstall the app to the workspace and copy the generated `https://hooks.slack.com/services/...` URL.
- **Signing Secret:** Slack app -> **Basic Information** -> **App Credentials** -> **Signing Secret**.
- **Bot Token:** Slack app -> **Features -> OAuth & Permissions** -> **Bot User OAuth Token** (`xoxb-...`). If it is missing, install or reinstall the app to the workspace after adding the needed bot scopes.
- **Security rule:** Never write live Slack secrets into `USER_MANUAL.md`, any repo file, screenshots, tickets, or Git history. Store the real Signing Secret and Bot Token only in Slack app settings, the app's Slack Integration screen, and a secure password manager or vault. If a secret is exposed in chat, email, docs, or source control, rotate it immediately.
- Configure webhook URL, signing secret, bot token, and default channel in Settings.
- **Outbound:** notifications for key actions (when enabled).
- **Inbound:** Slash commands and interactivity use `/api/slack/command` and `/api/slack/interactivity`.
- **Event Subscriptions:** In the Slack app, set the Request URL to `https://your-site/api/slack/events` (HTTPS). The app answers Slack’s URL challenge and accepts `event_callback` pings (extend later for channel messages). The **Signing Secret** in Slack must match the value saved in Settings.
- **Channel history sync:** Under **Settings → Slack Integration → Channel history sync**, configure up to **six** channels (`#name` or channel ID), then use **Settings → Maintenance → Sync Slack channel history**. The **Days back** value applies to the **first** sync of each channel; after that, each channel keeps its own cursor (last message timestamp) so only newer messages are scanned. The bot must be **invited** to every channel and have `channels:history` + `channels:read` (and for private channels, `groups:history` + `groups:read`). Each message is stored once (deduped by channel + Slack timestamp).
- **Outbound notification routing:** Under **Settings → Slack Integration**, you can now enable in-app supervisor notifications separately from outbound Slack delivery. When outbound Slack delivery is enabled, you can point completions, warnings, and reminders at separate webhook URLs; if a class-specific webhook is blank, the general outbound webhook is used.
- **Reminder automation:** The same Slack Integration section now controls whether unresolved warning/critical supervisor alerts should emit reminders automatically, along with separate delay thresholds for critical vs warning alerts. A reminder is stored in-app first, then optionally delivered to Slack through the reminders webhook route.
- **Slack imports & apply:** Sync **stores messages only**—it does not create Runs. Users with **Slack Importer** (or Super Admin) use **Slack imports** to filter/triage rows, open **Run preview**, review candidate source lots, optionally assign or split lot weights, and **Create run from Slack** so the normal Run form opens prefilled from **Settings → Slack → field mappings** (Run destination rules). Runs are created only when someone **saves** the Run form. Mapping rules for non-Run destinations remain preview/storage for future modules. Super Admins edit mappings at **`/settings/slack-run-mappings`**; the imports list is at **`/settings/slack-imports`** and is also linked from the sidebar for importers.
- **Slack field mappings screen:** The mapping editor now shows business-friendly labels first and the stored field key in parentheses, for example `Wet THCA (g) (wet_thca_g)`. Use the **App area** picker first, then choose the matching **App field** from the destination-specific dropdown. Only use **Custom field...** when the field you need is not listed yet.

### Maintenance: Recalculate all run costs
Use **Recalculate All Run Costs** after:
- entering new operational costs,
- changing cost allocation settings, or
- correcting biomass pricing

This recomputes cost-per-gram fields for all historical runs using current rules.

### Maintenance: Historical photo backfill
Use **Run Photo Backfill** if you have older approved field submissions from before photo indexing was enabled.

What it does:
- Adds missing supplier attachments for supplier/license photos from approved field submissions.
- Creates searchable photo-library records for supplier, biomass, and COA images tied to those submissions.
- Safe to run more than once (deduplicates existing records).

---

## Import (CSV) — runs and run-style history
The sidebar **Import** screen is for **extraction run** history exported from Google Sheets (run reports, kief/LD tabs, etc.). It is **not** for loading **purchase** batches—use **Purchases → Import spreadsheet** for those.

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
- Runs (includes **HTE pipeline** label, terp/distillate grams, and lab file paths when present; respects the **HTE pipeline** filter if you applied one)
- Purchases
- Inventory
- Biomass Pipeline
- Suppliers
- Strains
- Costs

Exports support criteria filters (depending on tab), including date range, supplier/status, strain text, potency range, on **Runs** the **HTE pipeline** stage filter, and on **Purchases** the **Hide complete & cancelled** option when it is active on the list.

Use exports for reporting, reconciliation, or offline analysis. Export buttons only appear for users with the relevant export permission in **Settings -> Access Control**.

---

## Troubleshooting
- **I see “No $/lb” on runs**: ensure each input lot’s purchase has `Price/lb` set.
- **Supplier/Strain analytics look “low”**: check if “exclude runs missing $/lb” is enabled in Settings.
- **Cost numbers changed after adding costs**: that’s expected; run $/g reflects operational costs in the relevant date ranges.
- **A pipeline record didn’t create a purchase**: set stage to **Committed** (or Delivered) and save; ensure required fields are valid.
- **I don’t see Slack imports in the sidebar**: ask a Super Admin to enable **Slack Importer** on your user (Super Admins always have access).
- **Slack prefilled run won’t save**: you need **User** or **Super Admin** to save Runs; Viewer accounts can only review the prefilled form.
- **Slack prefilled run won’t save because the lot total is wrong**: the selected lot rows must add up exactly to **Lbs in Reactor**. Use the live allocation summary on the Run form to find the difference.
- **What do the inbox buckets on Slack imports mean?**: they separate rows into **Auto-ready**, **Needs confirmation**, **Needs manual match**, **Blocked**, and **Processed** so operators can work the safest rows first.
- **Slack says this message is already linked to a run**: expected after a successful apply; confirm only if you intentionally need a second run from the same Slack message.
- **Upload rejected (file too large or wrong type)**: field intake photos allow **images only** up to **50 MB** each; Photo Library uploads, purchase supporting docs, and supplier lab/attachment uploads allow **images or PDF** up to **50 MB** each. Compress or split large PDFs if needed.
- **Field intake says too many photos in one section**: each category has a cap (default **30** images per supplier/biomass/COA bucket on the purchase form, and **30** on the biomass form). Remove extras in the list before submitting, or ask your administrator to raise `FIELD_INTAKE_MAX_PHOTOS_PER_BUCKET` if policy allows.
## Scanner workflow

- Print or open a lot label from **Purchases**.
- Scan the lot QR / tracking link or open `/scan/lot/<tracking_id>`.
- On the scanned lot page you can:
  - use **Start Run From This Lot** to preselect that lot on a new run
  - use **Confirm Movement** to update the lot storage location
  - use **Confirm Testing** to update the purchase testing status
  - review **Recent Scan Activity** for that lot

## Smart scales

- Go to **Settings -> Smart Scales** to register a device.
- Use **Test ingest** with a raw payload such as `ST,GS, 124.6 lb` to confirm the parser and save a capture.
- On **Runs -> New Run**, use **Capture from Scale** to prefill **Lbs in Reactor** from a live payload before saving the run.
- The saved run keeps the linked device capture for later audit and analytics.

## Standalone Purchasing Agent App

- The standalone purchasing app is intended for buyer and intake workflows on phone or tablet.
- Creating a new supplier from the standalone app now warns on typo-close duplicate names before saving and lets the buyer use an existing supplier instead.
- Approvers should review mobile-created opportunities from the main app:
  - `Purchases` list shows when a line originated from the `Mobile app`
  - purchase edit pages surface submission origin, created-by user, delivery-recorded-by user, opportunity photos, and delivery photos
- Supplier duplicates created from fast mobile entry can be corrected from `Suppliers -> Edit -> Merge Supplier`.

## Standalone Receiving Intake App

- The standalone receiving app is intended for receiving and intake staff on phone or tablet.
- It shows approved or committed purchases that are ready to record delivery.
- Receiving confirmation updates the purchase to `delivered`, records the receiving user, and can attach delivery photos.
- After receipt is confirmed, the receiving app now offers `Edit Receipt` until the lot is used in a downstream run.
- Once downstream processing starts, the receiving record becomes read-only and the main purchase screen shows the locked reason.
- Delivery photos and receiving metadata are visible from the main purchase review screen.
- `Settings -> Operational Parameters` can enable or disable the standalone purchasing, receiving, and extraction workflows independently.
- `Settings -> API Clients` now also shows recent mobile workflow activity for audit visibility.

### Typical receiving flow

1. Sign into the standalone receiving app with your normal Gold Drop user account.
2. Open a queue item that is already approved or committed.
3. Confirm delivered weight, delivery date, location, floor state, testing status, and notes.
4. Upload any delivery photos needed for the record.
5. Submit the receipt.
6. If the dock count or receiving details need correction before the lot is consumed in a run, use `Edit Receipt`.

### What "ready to record delivery" means

When the standalone app marks a purchase as **ready to record delivery**, it means:
- the purchase has advanced far enough in approval / commitment that receiving can act on it
- the receiving team can record the actual delivered weight and delivery date
- the receiving team can also capture testing state, notes, photos, location, and floor state for the delivered lot

### When `Edit Receipt` is available

- You can edit a confirmed receipt while none of that purchase's lots have been used in downstream processing.
- Once one of the lots is consumed by a run, the receiving record locks automatically.
- When locked, the receiving detail and the main purchase review screen show the lock reason instead of allowing more edits.
