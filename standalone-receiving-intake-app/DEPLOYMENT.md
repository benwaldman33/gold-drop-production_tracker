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
- `POST /api/mobile/v1/receiving/queue/<id>/receive`
- `POST /api/mobile/v1/receiving/queue/<id>/photos`

## Pilot Checklist

Before rollout:

1. confirm user accounts with purchase-edit access can log in
2. confirm receiving queue shows approved and committed purchases
3. confirm receipt updates appear in the main app
4. confirm delivery photos appear in purchase review
5. confirm real phone/tablet browsers can stay signed in over HTTPS
