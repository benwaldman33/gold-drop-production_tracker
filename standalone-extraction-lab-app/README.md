# Standalone Extraction Lab App

Touch-first operator app for the extraction lab workflow. It mirrors the main app's extraction board and charge flow while stripping away non-essential admin UI.

## Current Scope

- session-cookie login against Gold Drop mobile auth
- active reactor board and same-day reactor history
- dedicated `Scan / Enter Lot` screen with camera and manual fallback
- chargeable lot search
- touch-friendly extraction charge form with `100 lbs`, `Half lot`, `Full lot`, and `Last used` presets plus last-reactor recall
- standalone run-execution screen with lockstep booth progression, active-checkpoint inputs, timer status, blend capture, fill / flush fields, CRC blend, baskets, and notes
- role-based run layouts:
  - extractors / assistant extractors: focused operator screen with one primary action at a time
  - managers / supervisors / admins: broader supervisor review screen with full timing cards
- settings-driven defaults for common run fields so the screen opens with the site's usual blend, aggregate weight, and count assumptions
- guided downstream workflow on the same `Open Run` screen after extraction completion, with pathway-driven steps for post-extraction handoff plus pot-pour or minor-run downstream decisions
- post-extraction quick fix: single run form after completion, immediate pathway save, step buttons instead of page-level Save during post-extraction
- deferred full post-extraction UX polish tracked in `FIX_BACKLOG.md`
- gated post-extraction handoff: pathway selection before start, wet-output entry in Step 3, undo-before-confirm on Step 2
- reactor lifecycle actions from the board
- full-size `Open Run` button on reactor cards so the linked-run step is obvious on iPad
- handoff link into the main run form after recording a charge

## Local Development

```bash
cd standalone-extraction-lab-app
npm test
npm run dev
```

By default the dev server runs at `http://127.0.0.1:4175` and proxies `/api/*` to `http://127.0.0.1:5050`.

## Operator Flow

1. Log in with a Gold Drop user who has extraction workflow access.
2. Open `Scan / Enter Lot` to scan or type a tracking ID directly into the charge workflow. The manual field auto-focuses for Bluetooth scanner use.
3. Open `Reactors` to see active lifecycle state and same-day history.
4. Open `Lots` when you need browser-style search by tracking id, supplier, strain, or batch id.
5. On the charge form, use the default `100 lbs` preset or tap `Half lot`, `Full lot`, or `Last used`. The app also preselects the last reactor used when possible.
6. Record the charge, then choose `Open Run`, `Open Run in Main App`, `Back to Reactors`, or `Charge Another Lot`.
7. In `Open Run`, use the current checkpoint card and progression buttons in order. The tablet shows only the active booth-step inputs and the next allowed action; later checkpoint fields stay hidden until the predicate is satisfied.
8. At final clarity, select `Clear enough` or `Not yet` before tapping `Confirm Final Clarity`; the selected decision is stored with that progression action.
9. If the active checkpoint cannot be completed because equipment or process conditions are blocking it, use `Request Manager Bypass` with a reason. Continue only after manager approval exposes `Use Approved Bypass`.
10. After `Mark Run Complete`, continue into the **Guided downstream workflow** on the same screen:
    - Step 1: choose the downstream pathway
    - Step 2: start post-extraction (`Undo Session Start` is available here until initial outputs are confirmed)
    - Step 3: enter wet THCA / wet HTE and confirm initial outputs
    - Step 4+: follow the pot-pour or minor-run branch steps top to bottom

Pending and completed downstream steps collapse to headers only so the active step stays obvious.
