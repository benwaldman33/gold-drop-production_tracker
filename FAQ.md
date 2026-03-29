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
No. It stores ingested messages for **review** (`Slack imports` / parsed-field hints). Automation may come later.

## Data & analytics

**Why do some runs show “No $/lb”?**  
The linked purchase is missing a **Price/lb**. Set pricing on the purchase (or enable/disable “exclude unpriced” in Settings depending on how you want analytics to behave).

---

Add new questions here as operators raise them; keep answers brief and link to the manual where useful.
