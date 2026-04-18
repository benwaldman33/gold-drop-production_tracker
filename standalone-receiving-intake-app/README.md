# Gold Drop Receiving Intake App

Standalone mobile-first web app for receiving staff to confirm delivery against approved or committed purchases.

## Scope

This app is intentionally narrow:

- log in with a Gold Drop user account
- view the receiving queue
- open one receiving item
- confirm receipt
- upload delivery photos
- queue multiple delivery photos across repeated picks before saving receipt

It does not create suppliers or opportunities. It operates on existing `Purchase` rows that are already approved or committed.

## Local Development

From the repo root:

```powershell
.\.venv\Scripts\Activate.ps1
python app.py
```

Then in a second shell:

```powershell
Set-Location .\standalone-receiving-intake-app
node scripts/dev-server.mjs
```

The dev server proxies `/api/*` to the Gold Drop backend so login and session cookies stay same-origin:

```text
http://127.0.0.1:4174
```

To point at a different backend:

```powershell
$env:BACKEND_URL="http://127.0.0.1:5050"
node scripts/dev-server.mjs
```

## Live Endpoints Used

- `POST /api/mobile/v1/auth/login`
- `POST /api/mobile/v1/auth/logout`
- `GET /api/mobile/v1/auth/me`
- `GET /api/mobile/v1/receiving/queue`
- `GET /api/mobile/v1/receiving/queue/<id>`
- `POST /api/mobile/v1/receiving/queue/<id>/receive`
- `POST /api/mobile/v1/receiving/queue/<id>/photos`

## Mock Mode

The app supports mock mode through `window.__RECEIVING_APP_CONFIG__` in [index.html](index.html).

## Supporting Docs

- [DEPLOYMENT.md](DEPLOYMENT.md)
- [PILOT_QA_CHECKLIST.md](PILOT_QA_CHECKLIST.md)
