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

## Data & analytics

**Why do some runs show “No $/lb”?**  
The linked purchase is missing a **Price/lb**. Set pricing on the purchase (or enable/disable “exclude unpriced” in Settings depending on how you want analytics to behave).

## Inventory

**What does “Total” mean on Inventory?**  
**On Hand** (remaining lbs on arrived lots) **plus** **In Transit** (stated lbs on committed/ordered/in-transit purchases). It is a combined position, not “usable today only.”

**Why doesn’t Days of Supply include in-transit?**  
Days of supply is **on-hand lbs only**, divided by your **Daily Throughput Target** (Settings). Material still on the way is shown in **In Transit** and in **Total**, but it is not counted toward days until it is on hand.

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
