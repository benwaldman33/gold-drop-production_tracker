# Purchasing Agent App Production Rollout

This runbook is for taking the standalone buyer app from local/pilot use to a real deployed environment.

## Target Shape

- buyer app hosted as static files
- `/api/*` on the buyer app origin reverse-proxied to the main Gold Drop backend
- HTTPS enabled
- same-origin browser session for mobile login and writes

Recommended shape:

- `https://buy.example.com/` -> static standalone app
- `https://buy.example.com/api/*` -> Gold Drop backend on the same site via proxy

## 1. Prepare the Main App

Before exposing the buyer app:

- deploy the latest main Gold Drop code with `/api/mobile/v1` support
- confirm standalone purchasing is enabled in `Settings -> Operational Parameters`
- confirm intended buyer accounts have purchase-edit access
- confirm approvers know where to review mobile-created opportunities in `Purchases`

## 2. Publish the Static App

Copy the standalone app assets to the web root:

- `standalone-purchasing-agent-app/index.html`
- `standalone-purchasing-agent-app/styles.css`
- `standalone-purchasing-agent-app/src/`

Suggested target:

- `/var/www/gold-drop-purchasing-agent-app`

Do not expose the local dev server in production.

## 3. Configure the Reverse Proxy

Use the sample config in:

- [deploy/nginx-site.conf](deploy/nginx-site.conf)

Requirements:

- `location /` serves the static buyer app
- `location /api/` proxies to the main Gold Drop app
- HTTPS enabled

## 4. Browser Session Validation

After the site is live, verify on a real device:

- login succeeds
- page refresh keeps the session
- logout clears the session
- backend-origin errors do not appear in browser console

## 5. Production Smoke Test

Run this flow with a real buyer user:

1. log in
2. search an existing supplier
3. create a near-duplicate supplier and verify duplicate warning appears
4. create an opportunity
5. upload an opportunity photo
6. edit the opportunity before approval
7. approve or commit it in the main app
8. confirm it is locked for editing in the buyer app
9. record delivery
10. upload a delivery photo
11. verify approver review surfaces show origin, creator, delivery recorder, and photos

## 6. Failure Conditions To Check

- site toggle disabled:
  - buyer app should show a clear workflow-unavailable message
- user lacks permission:
  - buyer app should show a clear access message
- backend unavailable:
  - buyer app login or data requests should fail clearly instead of silently
- duplicate supplier:
  - user must be able to choose existing supplier or confirm new

## 7. Operational Hand-Off

Before calling rollout complete:

- buyer quick-start shared
- approver review expectations shared
- supplier merge process confirmed with admins
- rollback approach documented:
  - disable standalone purchasing in Settings
  - leave deployed files in place if needed

## 8. Go-Live Definition

The buyer app is production-ready when:

- deployment is live on HTTPS
- reverse proxy is stable
- buyer login works on phone/tablet
- full smoke test passes
- approvers can process mobile-created opportunities cleanly
