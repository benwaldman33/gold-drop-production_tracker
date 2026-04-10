# Gold Drop — Frequently Asked Questions

Short answers only. For step-by-step guidance see `USER_MANUAL.md`. For product rules see `PRD.md`. For developer-oriented implementation notes see `ENGINEERING.md`.

## Slack

**What is “Default Channel” vs “Channel history sync”?**  
Default channel is used for outbound Bot API posts (`chat.postMessage`) and as a convenience default. History sync uses the **Channel history sync** list (up to six rows). On a fresh database, **slot 0** is seeded from Default Channel once; you can change either independently afterward.

**How many channels can I pull history from?**  
Up to **six**. Leave a row blank to skip it.

**Why did my second sync run faster / fetch less?**  
After the first successful sync for a channel, the app stores a **per-channel cursor** (last Slack message timestamp). Later runs ask Slack only for messages **after** that cursor (incremental sync). **Days back** applies mainly to the **first** sync when no cursor exists for that slot.

**I changed the `#channel` name in Settings—what happens?**  
Saving a new hint clears that row’s **resolved channel ID** and **cursor** so the next sync re-resolves the channel and can use **Days back** again from a clean slate for that slot.

**Does Slack sync create runs or purchases?**  
**Sync** only stores rows in **Slack imports** (parsed hints). It does **not** create Runs or Purchases.

**How do I turn a Slack message into a Run?**  
Someone with **Slack Importer** (or Super Admin) opens **Slack imports** → **Create run** (or **Create run from Slack** on the preview). That opens **New Run** with fields prefilled from your mapping rules. You must still **Save** the run (requires **User** or **Super Admin**).

**Who can open Slack imports?**  
Users with the **Slack Importer** flag in **Settings → Users**, and all **Super Admins**. The link also appears under Settings as **View Slack imports** for admins.

**What is “Promotion” vs “Coverage” on the imports list?**  
**Promotion** means a **saved Run** exists with the same Slack `channel` + message `timestamp` backlink. **Coverage** is a **preview heuristic**: whether Run-mapping rules fully used the parsed fields before anyone applies (full / partial / none)—not a guarantee of what was typed on the saved run.

**What if I apply the same Slack message twice?**  
The app **warns** and asks for **confirm** before prefilling again if a run is already linked. You can still save a second run after confirming; clean up mistakes with **Runs → Delete** if needed.

## List views, filters & sorting

**Do I lose my filters when I leave Runs (or Purchases, etc.) and come back?**  
No—while your **login session** is active, the app **saves list filters, date ranges, sort order, and related settings** for key screens (**Runs**, **Purchases**, **Biomass Pipeline**, **Costs**, **Inventory**, **Strains**, **Slack imports**). You can move freely between sidebar pages and return to the same narrowed view. Use **Remove filters** (when shown) to clear saved list state for that screen and show the full default list.

**Will filters survive closing the browser or signing out?**  
They may **not**. State is kept in the server session tied to your browser cookie; signing out, clearing cookies, or a new browser session typically resets list filters.

**I applied a date range and the table went empty—was data deleted?**  
Nothing was deleted. Usually you were still on **page 2+** after the result set shrank; the app now resets to **page 1** when you **Apply filters** or switch **Purchases** status tabs so matches stay visible.

**What does “Hide complete & cancelled” on Purchases do?**  
It hides rows whose status is **complete** or **cancelled** from the list (and export can follow the same rule when that box is on). Turn it off and click **Apply filters** to show them again.

**Why is there a second Save on Edit Purchase?**  
The **Save Purchase** button at the **top** submits the same form as the one at the bottom so you do not have to scroll on long purchase records.

## Purchases — spreadsheet import

**How do I import many purchases from Excel or a CSV?**  
Open **Purchases** and use **Import spreadsheet**. You can **drag and drop** a **.csv**, **.xlsx**, or **.xlsm** file (or click to browse). The app detects the header row and maps common column names (e.g. **Vendor**, **Purchase Date**, **Invoice Weight**, **Actual Weight**, **Manifest**, **Amount**, **Paid Date**, **Payment Method**, **Week**). Fix any rows flagged with errors on the preview, choose which valid rows to import, then commit. You can optionally **create missing suppliers** by name (case-insensitive match).

**Is purchase import the same as Import (runs)?**  
No. The **Import** screen under the sidebar is for **run-style** Google Sheet exports. **Purchases** use **Import spreadsheet** on the Purchases page.

**Why did a row fail validation?**  
Common causes: missing **purchase date** (or **paid date** as fallback), missing both **invoice** and **actual** weight, **duplicate Batch ID / Manifest** already in the system, or values that cannot be parsed. The preview lists the reason per row.

**Are imported purchases approved automatically?**  
**No.** They are created **unapproved**. If the spreadsheet asked for an on-hand status, the app **downgrades** to a safe status (e.g. **ordered**) until someone uses **Edit Purchase** → **Approve purchase** and sets the real status.

## Batch edit (list screens)

**What is “Batch edit…” on Runs, Purchases, etc.?**  
You can select **two or more** rows with the checkboxes, then click **Batch edit…** (or **Batch rename…** on Strain Performance). **Select all** / **Select none** apply to the **current page** of the table. The next screen lists fields you can set for **all** selected records at once; leave a field unchanged to skip it for that batch.

**Who can batch edit?**  
Same rules as editing a single row: **User / Super Admin** for runs, biomass, costs, suppliers, and strain rename; **purchase editors** (including **Super Buyer** where `can_edit_purchases` applies) for purchases and inventory lot rows.

**Why did my batch purchase update fail?**  
Batch purchase changes run the same **inventory lot maintenance** and **weekly biomass budget** checks as saving one purchase. If the batch would violate a cap, the transaction is rolled back and you will see an error—adjust the selection or fields and try again.

**What does Strain Performance “Batch rename…” do?**  
It renames the **strain** on every **purchase lot** that matches the selected **strain + supplier** pairs from the performance table. Use carefully; it is a bulk data change.

## Data & analytics

**Why do some runs show “No $/lb”?**  
The linked purchase is missing a **Price/lb**. Set pricing on the purchase (or enable/disable “exclude unpriced” in Settings depending on how you want analytics to behave).

## Inventory

**What does “Total” mean on Inventory?**  
**On Hand** (remaining lbs on arrived lots) **plus** **In Transit** (stated lbs on committed/ordered/in-transit purchases). It is a combined position, not “usable today only.”

**Why doesn’t Days of Supply include in-transit?**  
Days of supply is **on-hand lbs only**, divided by your **Daily Throughput Target** (Settings). Material still on the way is shown in **In Transit** and in **Total**, but it is not counted toward days until it is on hand.

**Why don’t I see a purchase on the On Hand inventory table?**  
**On Hand** only lists lots from purchases that are both in an **arrived** status (**delivered**, **in_testing**, **available**, **processing**, **complete**) **and** **approved** (`purchase_approved_at` set). Use **Edit Purchase** → **Approve purchase** (if you have approver access), or complete the pipeline approval path for **Committed** on **Biomass Pipeline**, then set the right status.

---

## Biomass Pipeline & Purchases

**Is Biomass Pipeline still a separate table from Purchases?**  
**No.** Pipeline rows are **`Purchase`** records with pipeline statuses (**`declared`**, **`in_testing`**, **`committed`**, …) and extra fields (availability date, declared weight, testing metadata, field photos). The legacy **`biomass_availabilities`** table may still exist for migration/backfill, but the UI reads and writes **purchases**.

**What does “Testing” on the pipeline list mean internally?**  
The UI stage **Testing** maps to purchase status **`in_testing`** (not a separate entity).

**Who can move a batch to Committed?**  
**Super Admin** or any user with the **purchase approver** flag (`is_purchase_approver`). That transition stamps **approval** and is audited. Moving **away** from **Committed** / **Delivered** back toward early stages also requires the same permission.

**Why can’t I set my purchase to Delivered?**  
If the banner says **Not yet approved**, use **Approve purchase** first. The app blocks **on-hand** statuses until approval so unapproved material does not appear in inventory or runs.

---

## Departments

**What are “Departments” in the sidebar?**  
The same database and screens as everywhere else, organized by team (finance, purchasing, intake, extraction, THCA/HTE/Liquid Diamonds, terpenes, testing, bulk sales). Each page has **quick links** and **rollups** (counts, recent totals) for that lens. See **`USER_MANUAL.md` → Departments**.

**Do Departments duplicate data?**  
No. Numbers should match the underlying **Runs**, **Purchases**, etc. Department pages are navigation + summary, not a second source of truth.

---

## HTE lab & terp pipeline (runs)

**What is the “HTE pipeline” on a run?**  
After **dry HTE** is separated from THCA, you can record where that material is in downstream processing: **awaiting outside lab test**, **lab clean** (menu/sale path), **lab dirty — queued for Prescott strip**, or **stripped** with terpene and retail distillate grams. Optional **COA/lab files** attach to the **Run**.

**Is this the same as lab tests on Suppliers?**  
No. **Suppliers** can hold **historical lab tests** per supplier. **Run** pipeline fields track **this extraction batch’s** HTE after separation. You can use both.

**How do I filter runs by pipeline stage?**  
On **Runs**, use the **HTE pipeline** dropdown in the filter bar (or open a quick link from **Departments → Testing** or **Terpenes distillation**).

**Does export include HTE fields?**  
Yes. **Export CSV** on Runs includes pipeline label, terp/distillate grams, and lab file paths when present, and respects the active **HTE pipeline** filter.

---

## Git & deploy (self-hosted)

**How do I put new code on the server?**  
Merge your work into **`main`** (e.g. on GitHub), then on the server: **`git pull`** on **`main`** and **restart the app** (e.g. systemd/Gunicorn). Git does not reload Python by itself.

**Does pulling lose database data?**  
No. `git pull` only updates application files. Your **database** (SQLite file or PostgreSQL) is separate—back it up on its own schedule.

---

Add new questions here as operators raise them; keep answers brief and link to the manual where useful.
