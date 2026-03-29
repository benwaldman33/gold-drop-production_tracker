# Gold Drop — Frequently Asked Questions

Short answers only. For step-by-step guidance see `USER_MANUAL.md`. For product rules see `PRD.md`.

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

---

Add new questions here as operators raise them; keep answers brief and link to the manual where useful.
