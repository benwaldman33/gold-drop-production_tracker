# Receiving Intake App Deployment

## Recommended Shape

- serve the standalone app as a static site
- proxy `/api/*` to the Gold Drop backend
- keep the app and backend under the same parent domain so cookie-based mobile auth works cleanly

Example:

- `https://receiving.example.com/`
- `https://receiving.example.com/api/*` -> Gold Drop backend

## Reverse Proxy Requirements

The frontend needs these mobile endpoints available:

- `GET /api/mobile/v1/auth/me`
- `POST /api/mobile/v1/auth/login`
- `POST /api/mobile/v1/auth/logout`
- `GET /api/mobile/v1/receiving/queue`
- `GET /api/mobile/v1/receiving/queue/<id>`
- `PATCH /api/mobile/v1/receiving/queue/<id>`
- `POST /api/mobile/v1/receiving/queue/<id>/receive`
- `POST /api/mobile/v1/receiving/queue/<id>/photos`

Current workflow note:

- receipt confirmation and receipt correction use the same purchase-backed mobile workflow
- `PATCH /api/mobile/v1/receiving/queue/<id>` is required for the post-receipt `Edit Receipt` flow
- once a downstream run consumes one of the purchase's lots, the API reports the receipt as locked and edits are rejected

## Pilot Checklist

Before rollout:

1. confirm user accounts with purchase-edit access can log in
2. confirm receiving queue shows approved and committed purchases
3. confirm receipt updates appear in the main app
4. confirm `Edit Receipt` works before downstream lot usage exists
5. confirm receipt editing locks after downstream run usage and shows a clear lock reason
6. confirm delivery photos appear in purchase review
7. confirm real phone/tablet browsers can stay signed in over HTTPS
