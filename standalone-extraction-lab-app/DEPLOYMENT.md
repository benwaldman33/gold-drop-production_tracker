# Standalone Extraction Lab App Deployment

## Purpose

Deploy a focused extraction workflow frontend that talks to the main Gold Drop backend through the mobile extraction API endpoints.

## Requirements

- Gold Drop backend deployed and reachable
- `standalone_extraction_enabled` enabled in `Settings -> Operational Parameters`
- users need extraction permissions (`can_extract_lab`)

## Local / pilot serving

```bash
cd standalone-extraction-lab-app
npm run dev
```

This serves the app locally and proxies `/api/*` to the configured Gold Drop backend URL.

## Static hosting

This app is plain HTML/CSS/JS. Any static host or Nginx site can serve it. The only runtime requirement is that `/api/*` requests must reach the Gold Drop backend while preserving the browser-facing host for same-origin mobile-write enforcement.

## Production checklist

1. Serve the app from its own path or hostname.
2. Proxy `/api/*` to the main Gold Drop backend.
3. Preserve the browser-facing `Host` header on proxied requests.
4. Use HTTPS if you want iPad camera scanning to work in production.
5. Confirm login works with session cookies.
6. Confirm `Scan / Enter Lot`, `Reactors`, `Lots`, and `Charge` screens all load.
