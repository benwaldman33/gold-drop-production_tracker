# Gold Drop - Frequently Asked Questions

Short answers only. For step-by-step guidance see `USER_MANUAL.md`. For product rules see `PRD.md`. For developer-oriented implementation notes see `ENGINEERING.md`.

## Slack

**What is "Default Channel" vs "Channel history sync"?**  
Default channel is used for outbound Bot API posts (`chat.postMessage`) and as a convenience default. History sync uses the **Channel history sync** list (up to six rows). On a fresh database, **slot 0** is seeded from Default Channel once; you can change either independently afterward.

**How many channels can I pull history from?**  
Up to **six**. Leave a row blank to skip it.

**Why did my second sync run faster or fetch less?**  
After the first successful sync for a channel, the app stores a **per-channel cursor** (last Slack message timestamp). Later runs ask Slack only for messages after that cursor. **Days back** mainly applies to the first sync when no cursor exists for that slot.

**I changed the `#channel` name in Settings. What happens?**  
Saving a new hint clears that row's resolved channel ID and cursor so the next sync re-resolves the channel and can use **Days back** again from a clean slate for that slot.

**Does Slack sync create runs or purchases?**  
No. **Sync** only stores rows in **Slack imports**. It does not create Runs or Purchases by itself.

**How do I turn a Slack message into a Run?**  
Someone with **Slack Importer** access (or Super Admin) opens **Slack imports** -> **Preview**. The preview shows mapped Run fields plus candidate source lots. You can accept a suggested lot, manually choose a lot, or split the weight across multiple lots, then open **Create run from Slack**. The app opens **New Run** prefilled from mapping rules and your lot selection. You still must **Save** the run, which requires **User** or **Super Admin**.

**What do the inbox buckets on Slack imports mean?**  
They are triage groups: **Auto-ready**, **Needs confirmation**, **Needs manual match**, **Blocked**, and **Processed**. They help operators work the safest rows first and isolate ambiguity instead of guessing.

**How does the app decide which lot a Slack message should use?**  
It ranks candidate lots using supplier, strain, remaining quantity, and received date. If there is one clearly defensible lot, the preview suggests it. If there are multiple plausible lots, you must confirm or choose manually.

**Can I split one Slack run across multiple lots?**  
Yes. On the Slack preview page, enter per-lot weights on the candidate lot card. The selected split carries into the Run form as prefilled lot rows.

**Why won’t a Slack-created run save if the lot rows look mostly right?**  
Because the selected lot weights must add up exactly to **Lbs in Reactor**. The Run form now shows a live allocation summary and projected remaining lot balances so you can fix the difference before saving.

**Who can open Slack imports?**  
Users with the **Slack Importer** flag in **Settings -> Users**, and all **Super Admins**. Admins can also reach it from Settings.

**What is "Promotion" vs "Coverage" on the imports list?**  
**Promotion** means a saved Run exists with the same Slack `channel` + message `timestamp` backlink. **Coverage** is a preview heuristic showing how fully Run-mapping rules used the parsed fields before anyone applies the message.

**What if I apply the same Slack message twice?**  
The app warns and asks for confirmation before prefilling again if a run is already linked. A second run is still allowed after confirmation; remove mistakes from **Runs** if needed.

**Did the modular rebuild change URLs or operator workflow?**  
No. The refactor moved route ownership into `gold_drop/*_module.py` files for maintainability, but user-facing URLs, approvals, list behavior, Slack import flow, and inventory rules are intended to stay the same.

## List views, filters, and sorting

**Do I lose my filters when I leave Runs or Purchases and come back?**  
No. While your **login session** is active, the app saves list filters, date ranges, sort order, and related settings for key screens: **Runs**, **Purchases**, **Biomass Pipeline**, **Costs**, **Inventory**, **Strains**, and **Slack imports**. Use **Remove filters** to clear saved state for that screen.

**Will filters survive closing the browser or signing out?**  
Usually not. State is session-scoped and tied to your browser cookie.

**I applied a date range and the table went empty. Was data deleted?**  
No. Usually you were still on page 2 or later after the result set shrank; the app resets to page 1 when you apply filters or switch Purchases status tabs so matches stay visible.

**What does "Hide complete & cancelled" on Purchases do?**  
It hides rows whose status is **complete** or **cancelled** from the list. Export can follow the same rule when that option is active.

**Why is there a second Save on Edit Purchase?**  
The **Save Purchase** button at the top submits the same form as the one at the bottom so you do not have to scroll on long purchase records.

## Purchases - spreadsheet import

**How do I import many purchases from Excel or CSV?**  
Open **Purchases** and use **Import spreadsheet**. You can drag and drop a `.csv`, `.xlsx`, or `.xlsm` file or browse for it. The app detects the header row, maps common column names, shows row-level validation, and lets you commit the valid rows.

**Is purchase import the same as Import (runs)?**  
No. The sidebar **Import** screen is for run-style Google Sheet exports. Purchases use **Import spreadsheet** on the Purchases page.

**Why did a row fail validation?**  
Common causes are missing purchase date or paid-date fallback, missing both invoice and actual weight, duplicate Batch ID / Manifest, or values that could not be parsed. The preview lists the reason per row.

**Are imported purchases approved automatically?**  
No. They are created unapproved. If the spreadsheet asked for an on-hand status, the app downgrades it to a safe status such as **ordered** until someone approves the purchase and sets the real status.

**Do I have to open a purchase to approve it?**
No. If your account has purchase-approval permission, unapproved rows now show an inline **Approve** button directly on the **Purchases** list and **Biomass Pipeline** list. The full **Edit Purchase** screen still has the same approval action.

**How do I start fresh without losing login access?**
Use the server-side reset script, not a manual database wipe. `python scripts/reset_operational_data.py --yes` clears operational data but keeps users/passwords, system settings, KPI targets, Slack sync config, scale-device config, and cost entries. It also creates a SQLite backup automatically when applicable.

**What is `/api/v1/sync/manifest` for?**
It is a machine-readable site summary for future internal rollups. It reports the site identity plus basic dataset counts and freshness markers so an aggregator can decide what to pull next.

**What are the new `/api/v1/aggregation/*` endpoints for?**
They expose the locally cached cross-site rollup layer. `/api/v1/aggregation/sites` shows registered remote sites and their latest cached payloads, `/api/v1/aggregation/summary` combines the local site with cached remote summaries for higher-level internal reporting, and the supplier/strain aggregation endpoints compare performance across cached sites without live fan-out.

**How do I know what sort order and filters an internal API list actually used?**
Look at the response `meta`. List and search endpoints now return `count`, `limit`, `offset`, plus `sort` and `filters`. `sort` tells you the applied ordering, and `filters` echoes the normalized filter values the endpoint actually used after validation/defaulting.

**Why did a blank database come back with demo/history records?**
That used to happen because startup bootstrap seeded historical/demo data automatically when no runs existed. The app now only seeds baseline users/settings/KPIs on startup. Demo/history loading is explicit via `python scripts/seed_demo_data.py --yes`.

## Batch Journey

**Where do I open the Batch Journey timeline?**  
From **Purchases** click **Journey** on a row, or open **Edit Purchase** and click **View Journey**.

**What does the Journey show now besides stages?**  
It now shows inventory lots, lot tracking IDs, remaining and allocated weights, and run allocations so you can trace which lots fed which runs.

**Can I export a batch timeline?**  
Yes. On the Journey page use **Export JSON** or **Export CSV**.

**What happens if I pass an unknown Journey export format in the URL?**  
The app returns an explicit **400** error with supported formats (`csv`, `json`) instead of guessing.

**Why can’t I open Journey for an archived purchase?**  
Archived purchases require **Super Admin** and `include_archived=1` (via the Journey page toggle or URL) to view/export.

## Batch edit

**What is "Batch edit..." on Runs, Purchases, and other lists?**  
You can select **two or more** rows with checkboxes, then click **Batch edit...** or **Batch rename...** on Strain Performance. **Select all** and **Select none** apply to the current page only.

**Who can batch edit?**  
The same rules as single-row editing apply: **User / Super Admin** for runs, biomass, costs, suppliers, and strain rename; **purchase editors** for purchases and inventory lot rows.

**Why did my batch purchase update fail?**  
Batch purchase changes run the same inventory lot maintenance and weekly biomass budget checks as saving one purchase. If the batch would violate a rule, the transaction rolls back and shows an error.

**What does Strain Performance "Batch rename..." do?**  
It renames the strain on every **PurchaseLot** matching the selected **strain + supplier** pairs. Use it for standardizing labels, not for one-off tweaks.

## Data and analytics

**Why do some runs show "No $/lb"?**  
The linked purchase is missing **Price/lb**. Set pricing on the purchase, or review whether **exclude unpriced** is enabled in Settings.

## Inventory

**What does "Total" mean on Inventory?**  
**On Hand** plus **In Transit**. It is a combined position, not "usable today only."

**Why doesn't Days of Supply include in-transit?**  
Days of supply uses on-hand pounds only, divided by your **Daily Throughput Target**. Material still on the way is shown in **In Transit** and included in **Total**, but not in days-of-supply.

**Why don't I see a purchase on the On Hand inventory table?**  
**On Hand** only lists lots from purchases that are both in an arrived status (**delivered**, **in_testing**, **available**, **processing**) and approved (`purchase_approved_at` set). Approve the purchase first, then set the right status.

**What is a tracking ID on a lot?**  
It is the permanent machine-readable identity for that physical lot. The app now stores it so future barcode / QR label workflows can use the same lot record.

**Can I print a lot label already?**  
Yes. Label pages are available from Purchases, Inventory, and Journey surfaces. They currently print the lot identity, payloads, and scan path even before full barcode / QR image rendering is added.

**What are the new `/api/v1/tools/*` endpoints for?**
They are read-only semantic endpoints for internal automation and future MCP / AI tooling. They provide higher-level answers like inventory snapshots, open-lot lookup, canonical journey resolution, and reconciliation overview without stitching together several low-level API calls first.

**How do I refresh remote-site cache data?**
Super Admin can do it in **Settings -> Maintenance -> Pull all remote sites**, or from the server shell with `python scripts/pull_remote_sites.py`.

**Is the app ready for smart scales?**  
At the data-model level, yes. The system now has `ScaleDevice` and `WeightCapture` so future device-captured weights can attach to intake, lot, or run workflows without redesigning the material model.

## Biomass Pipeline and Purchases

**Is Biomass Pipeline still a separate table from Purchases?**  
No. Pipeline rows are `Purchase` records with pipeline statuses such as `declared`, `in_testing`, and `committed`, plus extra fields like availability date, declared weight, testing metadata, and field photos.

**What does "Testing" on the pipeline list mean internally?**  
The UI stage **Testing** maps to purchase status `in_testing`.

**Who can move a batch to Committed?**  
**Super Admin** or any user with the purchase approver flag. That transition stamps approval and is audited.

**Why can't I set my purchase to Delivered?**  
Because on-hand statuses are blocked until approval. Use **Approve purchase** first if you have approver access.

## Departments

**What are "Departments" in the sidebar?**  
They are team-focused views on the same underlying data: finance, purchasing, intake, extraction, THCA/HTE/Liquid Diamonds, terpenes, testing, and bulk sales.

**Do Departments duplicate data?**  
No. Department pages are navigation and summary views over the same Runs, Purchases, Inventory, and related data.

## HTE lab and terp pipeline

**What is the "HTE pipeline" on a run?**  
After dry HTE is separated from THCA, you can track it through downstream processing: awaiting lab, lab clean, lab dirty / queued for strip, or stripped with terpene and retail distillate grams recorded.

**Is this the same as lab tests on Suppliers?**  
No. Supplier lab tests are supplier-level history. Run pipeline fields track that extraction batch's HTE after separation.

**How do I filter runs by pipeline stage?**  
Use the **HTE pipeline** dropdown on **Runs** or the quick links from **Departments**.

**Does export include HTE fields?**  
Yes. Runs export includes pipeline label, terp/distillate grams, and lab file paths when present, and respects the active HTE pipeline filter.

## Git and deploy

**How do I put new code on the server?**  
Merge work into `main`, then on the server run `git pull` on `main` and restart the app process. Git does not reload Python by itself.

**Does pulling lose database data?**  
No. `git pull` only updates application files. Your database is separate and should be backed up on its own schedule.

Add new questions here as operators raise them; keep answers brief and link to the manual where useful.
