# Standalone Extraction Lab App

Touch-first operator app for the extraction lab workflow. It mirrors the main app's extraction board and charge flow while stripping away non-essential admin UI.

## Current Scope

- session-cookie login against Gold Drop mobile auth
- active reactor board and same-day reactor history
- dedicated `Scan / Enter Lot` screen with camera and manual fallback
- chargeable lot search
- touch-friendly extraction charge form with `100 lbs`, `Half lot`, `Full lot`, and `Last used` presets plus last-reactor recall
- standalone run-execution screen with timer controls, blend capture, fill / flush fields, CRC blend, baskets, and notes
- settings-driven defaults for common run fields so the screen opens with the site's usual blend / count assumptions
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
7. In `Open Run`, use the touch-first timers and counters to capture execution details without leaving the tablet workflow.
