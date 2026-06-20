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
- post-extraction guided handoff: single run form after completion, immediate pathway save, server-stamped `Start Post-Extraction` / `Confirm Initial Outputs`, and step-local save buttons for branch fields
- form draft sync: checkpoint numeric/text fields retain typed values across toasts and screen refreshes until the step action or Save submits them
- **Reactor Emptied** after pour-out on completed charges (shared board API + Floor Ops + Open Run)
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
7. In `Open Run`, use the current checkpoint card and progression buttons in order (`Confirm Under Vacuum` through `Mark Run Complete`). After `Record Solvent Charge`, the next required checkpoint is `Confirm 50 PSI` before `Start Primary Soak`. During primary extraction, use `Start Mixer` and `End Mixer`; if needed before filter clear, `Restart Mixer` is available to re-enter the mixing stage. The tablet shows only the active booth-step inputs and the next allowed action; later checkpoint fields stay hidden until the predicate is satisfied. Active timers now show live ticking elapsed/remaining (or over-target) time.
8. Use the collapsible **Evidence Photos** panel whenever you need proof capture. It stays available throughout run execution and supports camera/upload input for chiller, plate, and other booth photos.
   - The upload controls are isolated from the main run form so they do not interfere with Step 3 wet-output confirmation.
9. At final clarity, select `Clear enough` or `Not yet` before tapping `Confirm Final Clarity`; the selected decision is stored with that progression action.
10. If the active checkpoint cannot be completed because equipment or process conditions are blocking it, use `Request Manager Bypass` with a reason. Continue only after manager approval exposes `Use Approved Bypass`.
11. If you need to return to the immediately previous booth checkpoint, use the one-step back controls:
    - `Admin` and `Super Admin`: apply one-step back directly
    - other roles: request step-back approval with a reason, then apply after supervisor approval
    - all step-back actions are written to booth history and are blocked once the run is complete
12. After `Mark Run Complete`, continue into the **Guided downstream workflow** on the same screen and complete each step in order:
    - Step 1: choose the downstream pathway
    - Step 2: start post-extraction (`Undo Session Start` is available here until initial outputs are confirmed; timestamp is recorded from the action)
    - Step 3: enter wet THCA / wet HTE and confirm initial outputs (confirmation timestamp is recorded from the action)
    - Step 4+: follow the pot-pour or minor-run branch steps top to bottom, using the step-local save buttons where shown

Pending and completed downstream steps collapse to headers only so the active step stays obvious.
