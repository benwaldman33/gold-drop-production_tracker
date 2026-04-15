# API Reference

This document describes the current internal API and MCP access surface for the Gold Drop application.

Status:
- Internal
- Read-only
- Intended for trusted internal systems, site-to-site aggregation, and AI/MCP consumers

Additional mobile workflow surface:
- `/api/mobile/v1` is a user-authenticated write API for the standalone Purchasing Agent App
- it uses logged-in Gold Drop users and session cookies rather than bearer-token API clients

Primary HTTP API source of truth:
- [gold_drop/api_v1_module.py](gold_drop/api_v1_module.py)

Related implementation files:
- [services/api_auth.py](services/api_auth.py)
- [services/api_serializers.py](services/api_serializers.py)
- [services/api_queries.py](services/api_queries.py)
- [services/api_site.py](services/api_site.py)
- [services/purchases_journey.py](services/purchases_journey.py)
- [services/mcp_tools.py](services/mcp_tools.py)
- [scripts/mcp_server.py](scripts/mcp_server.py)

## Purpose

The `/api/v1` surface exists so other internal apps, analytics workflows, aggregation services, and MCP/AI tools can read structured operational data without depending on the main HTML UI or direct database access.

Current scope:
- site-local reads
- traceability reads
- inventory, purchase, run, supplier, and strain reads
- reconciliation and exception reads
- scanner and scale reads
- aggregation cache reads

Out of scope for this version:
- general write access
- external/public customer access
- cross-site transactional sync

## Mobile Workflow API (`/api/mobile/v1`)

This surface is separate from `/api/v1`.

Authentication:
- user-based login
- session cookies
- intended for the standalone mobile/tablet Purchasing Agent App

### Auth

- `POST /api/mobile/v1/auth/login`
- `POST /api/mobile/v1/auth/logout`
- `GET /api/mobile/v1/auth/me`

`login` returns:
- authenticated user identity
- site identity
- app permissions

### Opportunities

- `POST /api/mobile/v1/opportunities`
- `GET /api/mobile/v1/opportunities/mine`
- `GET /api/mobile/v1/opportunities/<opportunity_id>`
- `PATCH /api/mobile/v1/opportunities/<opportunity_id>`
- `POST /api/mobile/v1/opportunities/<opportunity_id>/delivery`
- `POST /api/mobile/v1/opportunities/<opportunity_id>/photos`

Behavior:
- opportunity is the primary object
- buyer-side edits are allowed only before approval
- delivery is only allowed after approval or commitment
- delivery transitions the opportunity to `delivered`
- photo uploads use one attachment collection with `photo_context` values of `opportunity` or `delivery`

### Suppliers

- `POST /api/mobile/v1/suppliers`

Behavior:
- supplier creation is allowed
- duplicate warnings can return `requires_confirmation` with `duplicate_candidates`
- confirmed creation uses `confirm_new_supplier=true`
- duplicate resolution and supplier merge/correction are handled in the main app

## Authentication

All `/api/v1/*` endpoints require bearer-token authentication.

Header:

```http
Authorization: Bearer <token>
```

Tokens are managed as internal API clients.

Token creation options:
- `Settings -> Internal API Clients`
- CLI script:

```bash
cd /opt/gold-drop
source venv/bin/activate
python scripts/create_api_client.py --name "internal-bi" --scopes read:site,read:lots,read:inventory
```

Token behavior:
- raw token is shown once at creation
- only a hash is stored
- tokens are scope-limited
- tokens can be revoked/reactivated

Auth failure behavior:
- `401` for missing or invalid token
- `403` for inactive client or missing scope
- JSON errors only, no HTML redirects

## Scopes

Current scopes:
- `read:site`
- `read:purchases`
- `read:journey`
- `read:lots`
- `read:runs`
- `read:inventory`
- `read:dashboard`
- `read:aggregation`
- `read:search`
- `read:tools`
- `read:slack_imports`
- `read:exceptions`
- `read:scanner`
- `read:scales`
- `read:suppliers`
- `read:strains`

## Response Contract

Every response includes `meta`.

Common `meta` fields:
- `api_version`
- `site_code`
- `site_name`
- `site_timezone`
- `site_region`
- `site_environment`
- `generated_at`

List and search responses also include:
- `count`
- `limit`
- `offset`
- `sort`
- `filters`

Typical shape:

```json
{
  "meta": {
    "api_version": "v1",
    "site_code": "SAC",
    "site_name": "Gold Drop Sacramento",
    "site_timezone": "America/Los_Angeles",
    "site_region": "California",
    "site_environment": "production",
    "generated_at": "2026-04-14T16:00:00Z",
    "count": 25,
    "limit": 25,
    "offset": 0,
    "sort": "created_at_desc",
    "filters": {}
  },
  "data": []
}
```

## Discovery and Site Identity

### `GET /api/v1/site`
Scope:
- `read:site`

Purpose:
- Return site identity metadata for the current deployment.

### `GET /api/v1/capabilities`
Scope:
- `read:site`

Purpose:
- Machine-readable discovery of supported scopes and endpoints.

Recommended first call for new integrations.

### `GET /api/v1/sync/manifest`
Scope:
- `read:site`

Purpose:
- Return dataset counts and timestamps useful for pull-based aggregation and sync planning.

Includes dataset summaries for:
- purchases
- lots
- runs
- slack imports
- suppliers

## Search

### `GET /api/v1/search`
Scope:
- `read:search`

Purpose:
- Cross-entity search across supplier, purchase, lot, and run records.

Query params:
- `q` required
- `types` optional

Allowed `types` values:
- `suppliers`
- `purchases`
- `lots`
- `runs`

Example:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/search?q=farmlane&types=suppliers,purchases,lots"
```

## Core Operational Reads

### Purchases

#### `GET /api/v1/purchases`
Scope:
- `read:purchases`

Purpose:
- List purchases.

Supported query params:
- `status`
- `supplier_id`
- `approved`
- `start_date`
- `end_date`
- `limit`
- `offset`

#### `GET /api/v1/purchases/<purchase_id>`
Scope:
- `read:purchases`

Purpose:
- Purchase detail.

#### `GET /api/v1/purchases/<purchase_id>/journey`
Scope:
- `read:journey`

Purpose:
- Full purchase traceability payload.

Returns the journey from purchase to lots, allocations, runs, and downstream context.

### Lots

#### `GET /api/v1/lots`
Scope:
- `read:lots`

Purpose:
- List lots.

Supported query params:
- `purchase_id`
- `supplier_id`
- `strain`
- `tracking_id`
- `open_only`
- `include_archived`
- `limit`
- `offset`

#### `GET /api/v1/lots/<lot_id>`
Scope:
- `read:lots`

Purpose:
- Lot detail.

#### `GET /api/v1/lots/<lot_id>/journey`
Scope:
- `read:journey`

Purpose:
- Lot-level traceability payload.

Returns:
- upstream purchase context
- lot state
- run-input allocation edges
- downstream runs
- exception signals

### Runs

#### `GET /api/v1/runs`
Scope:
- `read:runs`

Purpose:
- List runs.

Supported query params:
- `start_date`
- `end_date`
- `reactor_number`
- `supplier_id`
- `strain`
- `slack_linked`
- `limit`
- `offset`

#### `GET /api/v1/runs/<run_id>`
Scope:
- `read:runs`

Purpose:
- Run detail.

#### `GET /api/v1/runs/<run_id>/journey`
Scope:
- `read:journey`

Purpose:
- Run-level backward traceability payload.

Returns:
- upstream purchase context
- source lots
- run-input allocation edges
- run summary
- exception signals

### Inventory

#### `GET /api/v1/inventory/on-hand`
Scope:
- `read:inventory`

Purpose:
- List open on-hand lots suitable for operational inventory reads.

Supported query params:
- `supplier_id`
- `strain`
- `limit`
- `offset`

#### `GET /api/v1/summary/inventory`
Scope:
- `read:inventory`

Purpose:
- Inventory summary payload.

Includes:
- open lot count
- total on-hand lbs
- days of supply
- partially allocated count
- fully allocated count
- low remaining count
- missing tracking count
- approval required count

## Supplier and Strain Analytics

### `GET /api/v1/suppliers`
Scope:
- `read:suppliers`

Purpose:
- List supplier performance rows.

Includes supplier analytics such as:
- all-time yield
- THCA yield
- HTE yield
- cost-per-gram
- run count
- pounds processed
- 90-day performance
- last batch performance
- profile completeness

### `GET /api/v1/suppliers/<supplier_id>`
Scope:
- `read:suppliers`

Purpose:
- Supplier detail and performance summary.

### `GET /api/v1/strains`
Scope:
- `read:strains`

Purpose:
- Strain performance rows grouped by strain and supplier.

Supported query params:
- `view=all|90`
- `supplier_id`
- `strain`
- `limit`
- `offset`

## Dashboard and Department Reads

### `GET /api/v1/summary/dashboard`
Scope:
- `read:dashboard`

Purpose:
- Site-level dashboard summary for analytics and summary apps.

Includes:
- selected period
- run totals
- lbs processed
- dry output
- biomass on hand
- week-to-date metrics
- weekly finance snapshot
- KPI card payloads

### `GET /api/v1/departments`
Scope:
- `read:dashboard`

Purpose:
- List department summary pages exposed by the site.

### `GET /api/v1/departments/<slug>`
Scope:
- `read:dashboard`

Purpose:
- Department-specific rollup payload.

Current department slugs:
- `operations`
- `purchasing`
- `quality`

## Slack, Reconciliation, and Exceptions

### Slack Imports

#### `GET /api/v1/slack-imports`
Scope:
- `read:slack_imports`

Purpose:
- Read imported Slack production/intake messages after parsing and triage.

Supported query params:
- `start_date`
- `end_date`
- `promotion`
- `coverage`
- `kind_filter`
- `text_filter`
- `text_op`
- `include_hidden`
- `channel_id`
- `limit`
- `offset`

#### `GET /api/v1/slack-imports/<msg_id>`
Scope:
- `read:slack_imports`

Purpose:
- Slack import detail including:
  - derived fields
  - preview mapping
  - coverage
  - linked runs
  - resolution signals

#### `GET /api/v1/summary/slack-imports`
Scope:
- `read:slack_imports`

Purpose:
- Slack inbox summary.

Includes:
- total messages
- bucket counts
- linked/unlinked counts
- coverage counts

### Exceptions

#### `GET /api/v1/exceptions`
Scope:
- `read:exceptions`

Purpose:
- Read operational exceptions drawn from purchase and inventory annotations.

Supported query params:
- `category=all|purchases|inventory`
- `limit`
- `offset`

#### `GET /api/v1/summary/exceptions`
Scope:
- `read:exceptions`

Purpose:
- Exception summary payload.

## Scanner and Smart-Scale Reads

### Scanner

#### `GET /api/v1/scan-events`
Scope:
- `read:scanner`

Purpose:
- Read scan-event activity.

Supported query params:
- `action`
- `tracking_id`
- `limit`
- `offset`

#### `GET /api/v1/lots/<lot_id>/scans`
Scope:
- `read:scanner`

Purpose:
- Read scan history for one lot.

#### `GET /api/v1/summary/scanner`
Scope:
- `read:scanner`

Purpose:
- Scanner summary payload.

Includes:
- total events
- distinct tracked lots
- action counts
- latest event timestamp

### Scales

#### `GET /api/v1/scale-devices`
Scope:
- `read:scales`

Purpose:
- Read configured scale devices.

#### `GET /api/v1/weight-captures`
Scope:
- `read:scales`

Purpose:
- Read weight-capture records.

Supported query params:
- `capture_type`
- `source_mode`
- `device_id`
- `limit`
- `offset`

#### `GET /api/v1/summary/scales`
Scope:
- `read:scales`

Purpose:
- Scale summary payload.

Includes:
- device count
- active device count
- capture count
- device capture count
- latest capture timestamp
- capture-type counts

## Aggregation Reads

These endpoints expose cached multi-site aggregation data when remote sites are configured.

### `GET /api/v1/aggregation/sites`
Scope:
- `read:aggregation`

Purpose:
- List remote sites with cached metadata.

### `GET /api/v1/aggregation/sites/<site_id>`
Scope:
- `read:aggregation`

Purpose:
- Cached detail for one remote site.

### `GET /api/v1/aggregation/summary`
Scope:
- `read:aggregation`

Purpose:
- Cross-site cached summary rollup.

### `GET /api/v1/aggregation/suppliers`
Scope:
- `read:aggregation`

Purpose:
- Cross-site cached supplier comparisons.

### `GET /api/v1/aggregation/strains`
Scope:
- `read:aggregation`

Purpose:
- Cross-site cached strain comparisons.

## Semantic Tool Endpoints

These are HTTP endpoints shaped for workflow and AI-style use cases.

### `GET /api/v1/tools/inventory-snapshot`
Scope:
- `read:tools`

Purpose:
- Compact inventory summary plus matching lots.

Supported query params:
- `supplier_id`
- `strain`
- `limit`

### `GET /api/v1/tools/open-lots`
Scope:
- `read:tools`

Purpose:
- Focused open-lot search for workflow clients.

Supported query params:
- `supplier_id`
- `strain`
- `min_remaining_lbs`
- `limit`

### `GET /api/v1/tools/journey-resolve`
Scope:
- `read:tools`

Purpose:
- Resolve and return a journey payload for a provided entity.

Supported query params:
- `entity_type=purchase|lot|run`
- `entity_id`

### `GET /api/v1/tools/reconciliation-overview`
Scope:
- `read:tools`

Purpose:
- Combined Slack-triage and exception rollup for workflow tools.

## Recommended Endpoints for New Integrations

For a supplier/trading integration, start with:
- `GET /api/v1/capabilities`
- `GET /api/v1/site`
- `GET /api/v1/suppliers`
- `GET /api/v1/purchases`
- `GET /api/v1/lots`
- `GET /api/v1/inventory/on-hand`
- `GET /api/v1/search`
- `GET /api/v1/purchases/<purchase_id>/journey`
- `GET /api/v1/lots/<lot_id>/journey`

That provides:
- supplier visibility
- purchase history
- lot identity and on-hand state
- traceability
- discovery of what the site supports

## Example Requests

Discovery:

```bash
curl -H "Authorization: Bearer TOKEN" http://HOST/api/v1/capabilities
```

Site identity:

```bash
curl -H "Authorization: Bearer TOKEN" http://HOST/api/v1/site
```

Search:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/search?q=farmlane&types=suppliers,purchases,lots"
```

Open lots:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/lots?open_only=1"
```

On-hand inventory:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/inventory/on-hand"
```

Purchase journey:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/purchases/PURCHASE_ID/journey"
```

Supplier analytics:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/suppliers"
```

Slack inbox summary:

```bash
curl -H "Authorization: Bearer TOKEN" "http://HOST/api/v1/summary/slack-imports"
```

## MCP Server

There is also a read-only MCP server for AI/tooling use:
- [scripts/mcp_server.py](scripts/mcp_server.py)

Primary MCP tool definitions:
- [services/mcp_tools.py](services/mcp_tools.py)

The MCP layer reuses the same site-local read model and exposes semantic tools such as:
- inventory snapshot
- open lots
- purchase, lot, and run journey
- reconciliation overview
- scanner summary
- lot scan history
- supplier and strain performance
- cross-site cached summaries

The HTTP API should be the starting point for non-MCP application integrations.

## Notes

- The current API is read-only.
- Cross-site UI visibility can be gated in Settings, but the aggregation API surface exists independently of the UI.
- Site identity is configured in `Settings -> Operational Parameters`.
- Remote-site pull and aggregation refresh are handled separately from the local site API.
