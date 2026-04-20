# Standalone Extraction Lab App

Touch-first operator app for the extraction lab workflow. It mirrors the main app's extraction board and charge flow while stripping away non-essential admin UI.

## Current Scope

- session-cookie login against Gold Drop mobile auth
- active reactor board and same-day reactor history
- chargeable lot search
- touch-friendly extraction charge form
- reactor lifecycle actions from the board
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
2. Open `Reactors` to see active lifecycle state and same-day history.
3. Open `Lots`, search by tracking id, supplier, strain, or batch id.
4. Tap `Charge`, set lbs, reactor, and time using touch controls.
5. Record the charge, then optionally open the main run form from the success panel.
