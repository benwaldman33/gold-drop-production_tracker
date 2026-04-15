# Purchasing Agent App Deployment

This app is a separate mobile-first frontend for buyers and intake staff.

## Recommended Production Shape

- Serve the standalone app as static files behind Nginx or another simple web server.
- Keep it on the same parent domain as the main Gold Drop app if possible.
- Route `/api/*` from the standalone app origin to the main Gold Drop backend.
- Use HTTPS in every non-local environment.

Example shape:

- `https://buy.example.com/` -> standalone app static files
- `https://buy.example.com/api/*` -> reverse-proxy to the Gold Drop backend

This keeps browser auth and session behavior straightforward.

## Local Development

Start the main app first:

```bash
python app.py
```

Then start the standalone dev server:

```bash
node scripts/dev-server.mjs
```

By default the dev server proxies `/api/*` to:

```text
http://127.0.0.1:5050
```

Override the backend target with:

```bash
BACKEND_URL=http://localhost:5050 node scripts/dev-server.mjs
```

## Reverse Proxy Requirements

The standalone app expects:

- `GET /api/mobile/v1/auth/me`
- `POST /api/mobile/v1/auth/login`
- `POST /api/mobile/v1/auth/logout`
- `GET /api/mobile/v1/suppliers`
- `POST /api/mobile/v1/suppliers`
- `POST /api/mobile/v1/opportunities`
- `GET /api/mobile/v1/opportunities/mine`
- `GET /api/mobile/v1/opportunities/<id>`
- `PATCH /api/mobile/v1/opportunities/<id>`
- `POST /api/mobile/v1/opportunities/<id>/delivery`
- `POST /api/mobile/v1/opportunities/<id>/photos`

## Pilot Environment Checklist

- backend reachable from the standalone host
- `/api/*` proxy configured
- HTTPS enabled
- mobile buyer/test users created
- purchase edit permission granted only to intended buyer users
- approvers able to review mobile-created opportunities in the main app

## Approval / Review Expectations

Approvers should verify:

- `Purchases` list shows `Mobile app` origin where relevant
- purchase edit page shows:
  - submission origin
  - created-by user
  - delivery-recorded-by user
  - opportunity photos
  - delivery photos

