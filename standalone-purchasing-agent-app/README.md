# Gold Drop Purchasing Agent App

Standalone mobile-first frontend for field buyers and intake staff.

This app is intentionally separated from the main Gold Drop backend UI. It consumes a small API surface and is designed to run on phone or tablet.

## Scope

Included:
- login
- home
- supplier search/context
- create opportunity
- my opportunities
- opportunity detail
- edit before approval
- record delivery against approved/committed opportunity
- photo upload UI

Excluded:
- approval actions
- run creation
- barcode/scanner flows
- scale workflows
- broad admin access

## Folder Layout

- `index.html` - app entry point
- `styles.css` - app styling
- `src/` - browser modules
- `tests/` - Node tests for contract logic
- `scripts/dev-server.mjs` - tiny static dev server
- `DEPLOYMENT.md` - deployment/runbook notes
- `PILOT_QA_CHECKLIST.md` - pilot validation checklist
- `PRODUCTION_ROLLOUT.md` - production deployment and smoke-test runbook
- `deploy/nginx-site.conf` - sample Nginx site config for same-origin `/api/*` proxying

## Local Development

Start the app:

```bash
node scripts/dev-server.mjs
```

The dev server proxies `/api/*` to the Gold Drop backend on `http://127.0.0.1:5050` by default.
To point it somewhere else:

```bash
BACKEND_URL=http://localhost:5050 node scripts/dev-server.mjs
```

Open:

```text
http://127.0.0.1:4173
```

Run tests:

```bash
node --test --experimental-test-isolation=none tests/api.test.mjs tests/domain.test.mjs tests/ui-helpers.test.mjs
```

## Mock-First Mode

The app defaults to mock mode so frontend work can proceed before the backend write endpoints are available.

Switch to live mode later by editing `src/config.js` or injecting `window.__PURCHASING_APP_CONFIG__` before `src/app.js` loads.

Example live config:

```html
<script>
  window.__PURCHASING_APP_CONFIG__ = {
    mode: "live",
    apiBaseUrl: ""
  };
</script>
```

The live app uses user-based auth for mobile workflows and keeps write actions under `/api/mobile/v1`.
It also uses `/api/mobile/v1/suppliers` for authenticated supplier search/context because the bearer-token-only internal read API is not appropriate for the mobile user session.
The app now reads mobile `capabilities` so it can show a clear unavailable state if the standalone purchasing workflow is disabled or the user lacks access.

## Backend Contract

The app is designed around:
- `Opportunity` as the primary object
- `Delivery` as a downstream action on an approved/committed opportunity
- edit only before approval
- one attachment collection with `photo_context`
- `/api/mobile/v1` for auth and writes
- existing read endpoints reused where practical

## Testing

The standalone app includes Node-based tests for:
- domain helpers
- API adapter behavior
- UI helper parsing/building

Run them with:

```bash
node --test --experimental-test-isolation=none tests/api.test.mjs tests/domain.test.mjs tests/ui-helpers.test.mjs
```

## Important Notes

- delivery is not a separate sibling object
- supplier creation allows fuzzy duplicate detection and user verification
- photo upload is in scope for v1
- the current live app uses `/api/mobile/v1` for auth, writes, and supplier reads

## Pilot Readiness

Use these documents before rollout:

- [DEPLOYMENT.md](DEPLOYMENT.md)
- [PILOT_QA_CHECKLIST.md](PILOT_QA_CHECKLIST.md)
- [PRODUCTION_ROLLOUT.md](PRODUCTION_ROLLOUT.md)
