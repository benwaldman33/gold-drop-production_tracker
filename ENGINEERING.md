# Gold Drop — Engineering notes

Developer-facing implementation details. Product behavior belongs in `PRD.md`; operator steps in `USER_MANUAL.md`.

Current documentation note: the standalone buying and standalone receiving surfaces should be treated as one shared mobile write platform. Keep endpoint, toggle, and audit notes aligned across both workflows.

## End-of-sprint closeout

Before closing a coding sprint:

- add or update tests that cover the shipped behavior
- run the relevant tests and make sure they pass
- review and update the core docs as needed:
  - `PRD.md`
  - `README.md`
  - `FAQ.md`
  - `ENGINEERING.md`
  - `CHANGELOG.md`
- review and update conditional docs when the change affects them:
  - `USER_MANUAL.md`
  - deployment / rollout runbooks
  - QA checklists
  - API reference docs such as `API_REFERENCE.md`
- commit the changes only after tests and docs are in sync
- push to Git after the commit when the branch/repo state is ready for deployment

This is a review checklist, not a rule to make no-op edits. Update only the documents that the shipped change actually affects.

## App package layout

- Runtime entrypoint is still **`app.py`**, but it now exposes **`create_app()`** and acts as a compatibility shim.
- Shared logic that used to live only in `app.py` is now split into **`gold_drop/`** modules:
  - **`gold_drop/auth.py`** - login manager wiring + access decorators
  - **`gold_drop/audit.py`** - `log_audit`
  - **`gold_drop/list_state.py`** - session filter persistence, timezone helpers, Slack channel labels
  - **`gold_drop/slack.py`** - Slack parsing, mapping, preview, and coverage helpers
  - **`gold_drop/purchases.py`** - weekly biomass budget / on-hand purchase helpers
- **`gold_drop/purchases_module.py`** - purchases list/form/approval route logic delegated from `app.py`; inline list approvals in Purchases and Biomass Pipeline post through this module and preserve `return_to`
  - purchase save now also persists shared pipeline/mobile fields such as `availability_date` and `testing_notes`
  - purchase routes now include lot splitting from the main purchase form (`POST /lots/<lot_id>/split`) for confirmed inventory adjustments
  - **`gold_drop/biomass_module.py`** - biomass pipeline list/form/archive route logic delegated from `app.py`
  - **`gold_drop/runs_module.py`** - run list/form/delete route logic delegated from `app.py`
  - **`gold_drop/dashboard_module.py`** - dashboard, department, and biomass purchasing dashboard routes delegated from `app.py`
  - **`gold_drop/field_intake_module.py`** - field/mobile intake and office purchase opportunity flows delegated from `app.py`
  - **`gold_drop/costs_module.py`** - cost entry list/form/delete routes delegated from `app.py`
  - **`gold_drop/inventory_module.py`** - inventory list/filter route delegated from `app.py`
  - **`gold_drop/batch_edit_module.py`** - batch edit route and return-url guard delegated from `app.py`
  - **`gold_drop/suppliers_module.py`** - suppliers, supplier attachments/lab tests, photos library routes, and super-admin supplier merge/correction UI delegated from `app.py`
  - **`gold_drop/purchase_import_module.py`** - purchase spreadsheet import staging/validation/commit flow delegated from `app.py`
  - **`gold_drop/strains_module.py`** - strain performance route delegated from `app.py`
  - **`gold_drop/bootstrap_module.py`** - startup database initialization and baseline seed logic delegated from `init_db()`; historical/demo seeding is now explicit, not automatic
  - **`gold_drop/settings_module.py`** - extracted settings/admin view logic called by the `/settings` route; also normalizes legacy field-token datetimes before render so Settings can compare token expiry against aware UTC safely
  - **`gold_drop/uploads.py`** - upload validation, save helpers, and JSON path normalization
  - **`services/lot_allocation.py`** - lot tracking backfill, lot candidate ranking, and run allocation apply / release logic
  - **`services/lot_labels.py`** - lot label payload generation plus Code 39 barcode rendering and QR image generation for print workflows
  - **`services/scale_ingest.py`** - future manual / device weight-capture service boundary
  - **`services/supplier_merge.py`** - supplier merge preview / execute service that preserves lineage and audits source-to-target remaps
  - **`gold_drop/api_v1_module.py`** - token-authenticated internal read-only API routes under `/api/v1`
  - **`gold_drop/mobile_module.py`** - user-authenticated mobile write API routes under `/api/mobile/v1`
  - **`services/mobile_write_api.py`** - shared standalone/mobile write helpers for workflow enablement, same-origin enforcement, capabilities, and audit metadata
  - **`gold_drop/floor_module.py`** - operator floor activity page for recent scans, recent scale captures, floor-state rollups, and extraction-readiness rollups
  - **`static/js/scan_camera.js`** - in-browser camera scanning client for `/scan`, with `BarcodeDetector` support plus manual/scanner fallback
  - **`services/api_auth.py`** - bearer-token generation, hashing, lookup, and scope enforcement
  - **`services/api_site.py`** - site identity + shared API response metadata
  - **`services/api_serializers.py`** - JSON serializers and response envelopes for API resources
  - **`services/api_queries.py`** - reusable filtered read queries for lots and on-hand inventory
- `app.py` still re-exports some extracted helpers, but the active dashboard, field intake, runs, purchases, biomass, costs, inventory, batch edit, suppliers/photos, purchase import, strains, settings, and Slack surfaces are now registered from package modules with `add_url_rule`, and startup init delegates through `gold_drop/bootstrap_module.py`.
- `gold_drop/dashboard_module.py` now also owns the gated cross-site UI routes:
  - `/cross-site`
  - `/cross-site/suppliers`
  - `/cross-site/strains`
  - `/cross-site/reconciliation`
- `tests/test_app_factory.py` provides a minimal factory + route-registration smoke check so future extractions are verified against a real app object, not just imports.

## Reset + seeding operations

- **Startup bootstrap (`gold_drop/bootstrap_module.init_db`)** now seeds only baseline rows:
  - default users (`admin`, `ops`, `viewer`)
  - system settings
  - KPI targets
  - Slack mapping defaults
- **Historical/demo data is no longer auto-seeded on startup.**
- **Explicit demo seed:** `python scripts/seed_demo_data.py --yes`
- **Operational reset:** `python scripts/reset_operational_data.py --yes`
  - keeps users/passwords, system settings, KPI targets, Slack sync config, scale devices, and cost entries
  - clears purchases/lots, runs/run inputs, Slack imports, field submissions/tokens, suppliers and related attachments/photos/tests, and audit/history rows
  - creates a SQLite backup automatically when a SQLite DB file is present
- **API client creation:** `python scripts/create_api_client.py --name "internal-bi" --scopes read:site,read:lots,read:inventory`
- **Settings UI:** Super Admin can also manage internal API clients in `Settings -> Internal API Clients`
  - create client + scoped token
  - token displayed once at creation
  - revoke/reactivate
  - delete revoked clients
  - inspect last used timestamp, scope, and endpoint
  - inspect the recent API request log (client, method, path, scope, status, timestamp)
- These scripts now prepend the repo root to `sys.path`, so they work from the project root without manual `PYTHONPATH` setup.
- **Cross-site UI flag:** `SystemSetting.cross_site_ops_enabled` controls whether cross-site operator/admin pages are visible. The cached aggregation API and remote-site settings remain available even when the sidebar/UI is hidden.

## Internal API (`/api/v1`)

Phase 1 internal API is read-only and site-local.

### Auth

- Header: `Authorization: Bearer <token>`
- Token auth is enforced only on `/api/v1/*`
- No redirect-based login responses on API routes
- JSON errors:
  - `401` for missing/invalid token
  - `403` for inactive client or missing scope

### Scopes

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

### Current endpoints

- `GET /api/v1/site`
- `GET /api/v1/capabilities`
- `GET /api/v1/sync/manifest`
- `GET /api/v1/aggregation/sites`
- `GET /api/v1/aggregation/sites/<site_id>`
- `GET /api/v1/aggregation/summary`
- `GET /api/v1/aggregation/suppliers`
- `GET /api/v1/aggregation/strains`
- `GET /api/v1/search`
- `GET /api/v1/tools/inventory-snapshot`
- `GET /api/v1/tools/open-lots`
- `GET /api/v1/tools/journey-resolve`
- `GET /api/v1/tools/reconciliation-overview`
- `GET /api/v1/summary/dashboard`
- `GET /api/v1/departments`
- `GET /api/v1/departments/<slug>`
- `GET /api/v1/purchases`
- `GET /api/v1/purchases/<purchase_id>`
- `GET /api/v1/purchases/<purchase_id>/journey`
- `GET /api/v1/lots`
- `GET /api/v1/lots/<lot_id>`
- `GET /api/v1/lots/<lot_id>/journey`
- `GET /api/v1/runs`
- `GET /api/v1/runs/<run_id>`
- `GET /api/v1/runs/<run_id>/journey`
- `GET /api/v1/suppliers`
- `GET /api/v1/suppliers/<supplier_id>`
- `GET /api/v1/strains`
- `GET /api/v1/slack-imports`
- `GET /api/v1/slack-imports/<msg_id>`
- `GET /api/v1/exceptions`
- `GET /api/v1/scale-devices`
- `GET /api/v1/weight-captures`
- `GET /api/v1/scan-events`
- `GET /api/v1/lots/<lot_id>/scans`
- `GET /api/v1/summary/inventory`
- `GET /api/v1/summary/slack-imports`
- `GET /api/v1/summary/exceptions`
- `GET /api/v1/summary/scales`
- `GET /api/v1/summary/scanner`
- `GET /api/v1/inventory/on-hand`

## Mobile Workflow API (`/api/mobile/v1`)

This surface is separate from `/api/v1`.

- User-authenticated session API for the standalone Purchasing Agent App
- Supports opportunity creation/editing, delivery entry, supplier creation, and photo uploads
- Enforces the opportunity -> delivery lifecycle boundary in the backend
- Reuses current read endpoints where practical instead of duplicating read models
- Local standalone frontend development uses a small proxying dev server so `/api/*` requests stay same-origin from the browser and can reuse Gold Drop session cookies cleanly

Mobile routes currently registered:
- `POST /api/mobile/v1/auth/login`
- `POST /api/mobile/v1/auth/logout`
- `GET /api/mobile/v1/auth/me`
- `GET /api/mobile/v1/capabilities`
- `GET /api/mobile/v1/suppliers`
- `GET /api/mobile/v1/suppliers/<supplier_id>`
- `POST /api/mobile/v1/opportunities`
- `GET /api/mobile/v1/opportunities/mine`
- `GET /api/mobile/v1/opportunities/<id>`
- `PATCH /api/mobile/v1/opportunities/<id>`
- `POST /api/mobile/v1/opportunities/<id>/delivery`
- `POST /api/mobile/v1/opportunities/<id>/photos`
- `POST /api/mobile/v1/suppliers`

Office intake note:
- The Biomass Purchasing `New opportunity` form now creates the same `Purchase` opportunity object as `/api/mobile/v1/opportunities`.
- External field-token intake still lands first as `FieldPurchaseSubmission` and is approved separately.
- `GET /api/mobile/v1/receiving/queue`
- `GET /api/mobile/v1/receiving/queue/<id>`
- `PATCH /api/mobile/v1/receiving/queue/<id>`
- `POST /api/mobile/v1/receiving/queue/<id>/receive`
- `POST /api/mobile/v1/receiving/queue/<id>/photos`

The standalone app now uses the mobile surface for:
- auth
- writes
- supplier reads

That avoids mixing a user-cookie mobile session with the bearer-token-only `/api/v1` read API.

Pilot-hardening additions:
- main-app purchase review now surfaces mobile-origin metadata and mobile-uploaded photos for approvers
- standalone app deployment/runbook and pilot QA docs live under `standalone-purchasing-agent-app/`, including a production rollout runbook and sample Nginx site config
- the receiving/intake companion app lives under `standalone-receiving-intake-app/` and reuses the same session-auth mobile surface with a receiving-specific queue and receive-confirm flow
- receiving can now correct an already confirmed receipt until downstream `RunInput` usage exists on one of that purchase's lots
- receiving edit metadata is derived from `audit_log` `receive_edit` events rather than a dedicated schema field
- controlled write-platform hardening now adds:
  - per-workflow site toggles for standalone buying and receiving
  - same-origin checks for unsafe mobile writes
  - mobile workflow audit entries in `audit_log`
  - delivery-photo upload limits
- the standalone purchasing app consumes mobile `capabilities` so production users see a clear unavailable state when standalone buying is disabled or the user lacks access
- the standalone receiving app also consumes mobile `capabilities` plus per-record `receiving_editable` / `locked_reason` fields so the UI can expose `Edit Receipt` only while no downstream lot usage exists

### Shared mobile write-platform rules

- Workflow toggles are mapped in `services/mobile_write_api.py`:
  - `buying -> standalone_buying_enabled`
  - `receiving -> standalone_receiving_enabled`
- Unsafe mobile writes use same-origin enforcement in `services/mobile_write_api.py`; browser requests with a mismatched `Origin` are rejected before mutation.
- Mobile workflow audit metadata is normalized through `mobile_workflow_audit_payload(...)`, which stamps `source = "mobile_api"` and the workflow name into `audit_log`.
- Receiving editability is derived at read time in `gold_drop/mobile_module.py` rather than stored as a persistent boolean field.
- The main web purchase form reads those audit rows back so approvers can see receiving-origin metadata and the last receiving edit actor without a dedicated receiving table.

### Response contract

Every response uses a standard envelope:

```json
{
  "meta": {
    "api_version": "v1",
    "site_code": "DEFAULT",
    "site_name": "Gold Drop",
    "site_timezone": "America/Los_Angeles",
    "generated_at": "2026-04-14T12:00:00Z"
  },
  "data": {}
}
```

List responses also include:
- `count`
- `limit`
- `offset`
- `sort`
- `filters`

Contract notes:
- `sort` is the canonical applied ordering for the endpoint.
- `filters` echoes the normalized values the endpoint actually used after validation/defaulting.
- Search responses use the same list metadata and currently report `sort = "relevance"`.
- Internal consumers should depend on these `meta` fields rather than inferring order/filter behavior from request strings alone.

### Site identity

Site identity comes from `SystemSetting` values seeded by bootstrap and editable in `Settings -> Operational Parameters`:
- `site_code`
- `site_name`
- `site_timezone`
- `site_region`
- `site_environment`

This keeps each deployed facility self-identifying for future aggregation without forcing row-level `site_id` yet.

### Remote-site aggregation cache

- `RemoteSite` stores trusted remote site registrations, bearer token, cached site identity, and the latest cached manifest/summary payloads.
- Remote-site cache now also stores pulled supplier-analytics and strain-analytics payloads for cross-site comparisons.
- `RemoteSitePull` stores pull history with status and cached payload snapshots.
- `services/site_aggregation.py` owns:
  - base-URL normalization
  - remote JSON fetch
  - single-site pull + cache write
  - batch pull across all active remote sites
  - rollup serialization / cached summary helpers
- Admin control surfaces:
  - `Settings -> Remote Sites` for per-site create/update/pull/toggle/delete
  - `Settings -> Maintenance -> Pull all remote sites` for one-shot refresh of all active registrations
  - `Settings -> Operational Parameters -> Enable Cross-Site Ops UI` for site-level visibility of the cross-site dashboards
- CLI control surface:
- `python scripts/pull_remote_sites.py`

## MCP server

- `scripts/mcp_server.py` implements a minimal stdio JSON-RPC MCP server.
- `services/mcp_tools.py` is the read-only MCP tool registry and execution layer.
- The server currently supports:
  - `initialize`
  - `ping`
  - `tools/list`
  - `tools/call`
- Tool execution runs inside Flask app + request context so existing journey builders and serializers can be reused without a second business-rules path.

### Current MCP tools

- `site_identity`
- `inventory_snapshot`
- `open_lots`
- `journey_resolve`
- `purchase_journey`
- `lot_journey`
- `run_journey`
- `reconciliation_overview`
- `search_entities`
- `dashboard_summary`
- `supplier_performance`
- `strain_performance`
- `remote_sites`
- `cross_site_summary`
- `cross_site_supplier_compare`
- `cross_site_strain_compare`
- `scanner_summary`
- `lot_scan_history`
- `scale_devices`
- `weight_capture_summary`

### MCP design notes

- The MCP layer is read-only.
- It intentionally reuses the existing domain logic and aggregation cache rather than proxying through HTTP.
- It is suitable for local/internal AI tooling first; broader deployment can later point MCP clients at the same repo script on each site instance.

## Resume checkpoint

- **April 11, 2026:** Slack rebuild resumed after shell loss. Current integration entrypoint is **`gold_drop/slack_integration_module.py`** for Slack settings persistence, history sync, import/apply flows, and `/api/slack/*` handlers.
- **April 11, 2026:** Modular route extraction now also covers **`gold_drop/costs_module.py`**, **`gold_drop/inventory_module.py`**, **`gold_drop/batch_edit_module.py`**, and **`gold_drop/strains_module.py`**. If work is interrupted again, resume by checking **`app.py`** `_register_extracted_routes()` and **`tests/test_app_factory.py`** to see the current active module surface.
- `app.py` still contains some Slack compatibility wrappers and lower-level intake/resolution helpers, but Slack route bodies now delegate into the module. If work is interrupted again, resume by checking:
- **`gold_drop/slack_integration_module.py`** - active Slack integration surface
- **`gold_drop/settings_module.py`** - Settings POST delegates for `form_type=slack`
- **`tests/test_app_factory.py`** and **`tests/test_slack_mapping_logic.py`** - current smoke and Slack logic coverage

## Lot allocation integrity + lot identity

- **Models (`models.py`)**
  - `PurchaseLot` now carries `tracking_id`, `barcode_value`, `qr_value`, `label_generated_at`, and `label_version`.
  - `PurchaseLot` exposes `allocated_weight_lbs` and `remaining_pct` convenience properties for views and services.
  - `RunInput` now carries `allocation_source`, `allocation_confidence`, `allocation_notes`, and `slack_ingested_message_id`.
- **Generation / backfill**
  - New lots receive tracking / label fields on insert.
  - `services/bootstrap_helpers.py` extends SQLite schema compatibility for the new `purchase_lots` and `run_inputs` columns.
  - Purchase approval and inventory-lot maintenance backfill missing lot tracking fields so legacy rows are upgraded without a manual migration step.
- **Scanner execution flows**
  - `gold_drop/purchases_module.py` now owns the scanned-lot execution actions:
    - guided run-start modes: `blank`, `full_remaining`, `partial`, `scale_capture`
    - standardized movement codes: `vault`, `reactor_staging`, `quarantine`, `inventory_return`, `custom`
    - testing confirmation from the scanned-lot page
  - The scanned-lot run-start flow writes a richer session prefill payload (`SCAN_RUN_PREFILL_SESSION_KEY`) that can include:
    - `run_start_mode`
    - `planned_weight_lbs`
    - `scale_device_id`
    - `suggested_allocations`
  - `gold_drop/runs_module.py` consumes those fields so the new-run form can prefill reactor lbs, source allocations, and scanner guidance text.
  - `LotScanEvent.context_json` now carries richer floor context for movement labels, locations, run-start mode, and planned partial weight so activity history is auditable without parsing free-text notes.
- **Service boundary**
  - `services/lot_allocation.py`
    - `ensure_lot_tracking_fields`
    - `ensure_purchase_lot_tracking`
    - `collect_run_allocations_from_form`
    - `apply_run_allocations`
    - `release_run_allocations`
    - `rank_lot_candidates`
    - `choose_default_lot_allocation`
- **Active callers**
  - `gold_drop/purchases_module.py` uses the service to backfill tracking on approval and lot creation.
  - `gold_drop/runs_module.py` uses the service for allocation validation, decrement, and release instead of inline lot math.
- **Rule now enforced**
  - Run save fails unless selected lot allocations equal `bio_in_reactor_lbs` exactly.
- **Label / scan surfaces**
  - `GET /lots/<lot_id>/label`
  - `GET /purchases/<purchase_id>/labels`
  - `GET /scan/lot/<tracking_id>` -> dedicated scanned-lot workflow page
  - `POST /scan/lot/<tracking_id>/start-run` -> creates a run-form prefill from the scanned lot
  - `POST /scan/lot/<tracking_id>/confirm-movement` -> updates lot location and records a movement scan event
  - `POST /scan/lot/<tracking_id>/confirm-testing` -> updates purchase testing status and records a testing scan event
- **Scanner observability**
  - `LotScanEvent` stores scan-open, start-run, movement, and testing actions with user/context/timestamp.
  - `GET /api/v1/scan-events`, `GET /api/v1/lots/<lot_id>/scans`, and `GET /api/v1/summary/scanner` expose scanner activity to internal consumers.
- **Smart-scale live integration**
  - `Settings -> Smart Scales` supports device registration, device updates, raw-payload test ingestion, and recent capture review.
  - `POST /runs/scale-capture` creates a pending `WeightCapture`, prefills `bio_in_reactor_lbs`, and links the capture to the run on save.
  - `GET /api/v1/scale-devices`, `GET /api/v1/weight-captures`, and `GET /api/v1/summary/scales` expose configured devices and recorded captures to internal consumers.
- **Coverage**
  - `tests/test_lot_allocation.py` covers tracking-id generation, approval-time backfill, partial allocation / release, and over-allocation rejection.

## List view filter & sort persistence (`LIST_FILTERS_SESSION_KEY`)

- **Storage:** Flask `session` key `list_filters_v1` maps **endpoint id** → flat `dict` of query-parameter strings (e.g. `runs_list`, `purchases_list`, `biomass_list`, `costs_list`, `inventory`, `strains_list`, `settings_slack_imports`).
- **Merge:** `_list_filters_merge(endpoint, keys)` — if the request has **no** keys from `keys` in `request.args`, restore entirely from session; otherwise start from session and **overlay** any key present in `request.args` (so pagination links and sort links that pass full query strings keep behavior predictable).
- **Clear:** `_list_filters_clear_redirect(endpoint)` on `?clear_filters=1` pops that endpoint’s dict and redirects to the bare list URL.
- **Runs / Purchases pagination:** Filter and search forms submit **`page=1`**; **Purchases** status links use **`page=1`**. After `paginate()`, if `page > pagination.pages`, **clamp** `page`, re-paginate, and patch the session dict so stale high pages are not re-applied.
- **Purchases `hide_terminal`:** Merged like other keys; when `filter_form=1` on the GET form, `hide_terminal` is set explicitly from the checkbox (unchecked ⇒ cleared) so session does not stick “on” incorrectly.
- **Slack imports:** Custom branch logic (not `_list_filters_merge`): empty query string restores full saved state; `filter_form=1` snapshots the apply form (including `getlist("channel_id")` stored as sorted CSV); partial URLs merge onto prior state. **Date filtering:** rows with `_slack_ts_to_date_value(...) is None` are **not** excluded by start/end range only (compare when `ts_date is not None`).
- **UX elsewhere:** `static/css/style.css` — `input[type="date"]` calendar indicator uses a white masked icon for dark theme. `purchase_form.html` — top **Save** uses `form="purchase-main-form"`.
- **Windows:** `requirements.txt` includes **`tzdata`** so `zoneinfo` resolves IANA names (e.g. `America/Los_Angeles`); timezone resolution now lives in **`gold_drop/list_state.py`** and falls back to `timezone.utc` if no zone DB.

See **`USER_MANUAL.md` → Saved filters, sorts, and list state** for operator-facing wording.

## Refactor roadmap — clear domain modules (modular monolith)

Current behavior should stay in one deployable app with shared DB/rules, but code can be split into maintainable modules.

### Target structure

```
app/
  __init__.py                # app factory, extension init
  extensions.py              # db, login manager, shared ext instances
  config.py                  # env/config loading + validation
  auth/                      # login/logout/user session concerns
  dashboard/                 # home KPIs + shared cards
  purchases/                 # purchase + biomass pipeline + approval + import
  inventory/                 # lot availability + days-of-supply
  runs/                      # runs CRUD + inputs + yields/costs + HTE pipeline
  costs/                     # operational cost entries
  slack/                     # sync, mappings, imports, apply
  departments/               # dept lenses + rollups
  settings/                  # system settings + user admin
  services/                  # pure domain workflows and orchestration
  policies/                  # permissions + status transitions
  queries/                   # reusable read models / reporting queries
  schemas/                   # form parsing + validation helpers
```

### Migration sequence (safe, incremental)
1. Move route handlers into Flask Blueprints by domain with no behavior changes.
2. Extract shared business rules from routes into `services/`:
   - purchase approval + status gating
   - inventory eligibility
   - budget enforcement
   - run-cost recomputation triggers
3. Extract permission and transition checks into `policies/` (single source for allowed status moves).
4. Introduce app factory (`create_app`) and thin `wsgi.py` entrypoint for easier tests/CLI.
5. Keep SQLAlchemy models stable during first pass; defer schema redesign until tests are green.
6. Add integration tests per domain boundary before/while moving logic.

### Refactor guardrails
- No duplicate business rules across department pages.
- Utility transforms should not require Flask request/app context unless explicitly route-bound.
- Keep old endpoints and templates functioning while moving internals; deprecate in phases.

### First steps (recommended order)
If starting now, do these first:

1. **Stabilize test/app bootstrapping**
   - Add a minimal `pytest.ini` (or equivalent) so tests run without ad-hoc `PYTHONPATH` tweaks.
   - Introduce `create_app(test_config=...)` so tests can create app/context deterministically.
2. **Extract one vertical slice to prove the pattern**
   - Start with **Purchases + Biomass Pipeline** (highest cross-module coupling).
   - Move routes into a `purchases` Blueprint while keeping URLs and templates unchanged.
   - Move approval/status-transition logic into a single `services/purchases.py`.
3. **Create one shared policy module**
   - Centralize purchase status transition checks and approval gates in `policies/purchase_status.py`.
   - Replace route-level one-off checks with policy calls.
4. **Ship a thin Batch Journey API first (before full UI)**
   - Implement `GET /api/purchases/<id>/journey` returning derived stage events.
   - Validate with real batches and edge cases (partial consumption, archived rows, unapproved deliveries).
5. **Then build the visual stepper**
   - Add “View Journey” entry point from Purchases list/detail.
   - Render timeline from the API model; avoid duplicating business logic in templates/JS.

## PRD implementation notes — departments, approvals, aging

Product requirements live in **`PRD.md`** under **Operational departments & shared data model**, **Users & Permissions** (capabilities), **Potential pipeline records — Old Lots and soft deletion**. This section is the **engineering appendix** for that initiative.

### Capabilities vs composite roles

- **Today (`models.py`):** `User.role` is `super_admin` | `user` | `viewer`; **`is_slack_importer`** exists for Slack apply flows; **`is_purchase_approver`** backs pipeline commitment authorization.
- **`User.can_approve_purchase` (property):** `True` if `super_admin` **or** `is_purchase_approver`. Settings: per-user toggle **Approve $** / create-user checkbox; **`user_purchase_approver`** audit action.
- **Guards:** **`_save_biomass_purchase()`** (Biomass Pipeline form → `Purchase`) requires `can_approve_purchase` to move **to or from** **`committed`** (and enforces delivered only after committed). Entering **`committed`** stamps **`purchase_approved_at`** / **`purchase_approved_by_user_id`** and logs audit **`purchase_approval`** with `source: biomass_pipeline`. **`_save_purchase()`** blocks **`INVENTORY_ON_HAND_PURCHASE_STATUSES`** until **`purchase_approved_at`** is set; **`POST /purchases/<id>/approve`** sets approval for users with `can_approve_purchase`.

### Purchase approval → commitment

- **Biomass pipeline:** one **`Purchase`** row per pipeline batch; no linked `BiomassAvailability` sync (`_purchase_sync_biomass_pipeline` is a legacy no-op stub). Commitment is **`status == "committed"`** on that purchase, with approval stamped as above.
- **Weekly finance / commitments (`_weekly_finance_snapshot`):** **`weekly_dollar_budget`** (`SystemSetting`); **commitments** = non-deleted purchases with **`status` ∈ (`committed`, `delivered`)** and either (**`purchase_approved_at`** date in the calendar week) **or** (legacy: **`purchase_approved_at` null** and **`purchase_date`** in the week). **Purchases** slice = non-deleted rows with **`purchase_date`** in the week. Dollars via **`_purchase_obligation_dollars`**.

### Potential-lot aging job

- **Settings keys:** `potential_lot_days_to_old` (**N₁**, default 10), `potential_lot_days_to_soft_delete` (**N₂**, default 30). Saved under **Operational Parameters**; if **`N₂` < `N₁`**, **`N₂`** is raised to **`N₁`** with an info flash.
- **Clock:** **`created_at`** on **`Purchase`** (see PRD). Applies only to **`declared`** / **`in_testing`** pipeline rows (not committed/delivered/cancelled).
- **Execution:** **`_apply_biomass_potential_soft_delete()`** runs at the start of **`GET /biomass`** (idempotent; sets **`Purchase.deleted_at`** when age ≥ **N₂** for potential statuses). Safe to call frequently.
- **List buckets (`_biomass_bucket_filter`):** **Current** (default) — non-deleted; potential rows only if **`created_at` > now − N₁**; committed+ stages ignore age. **Old Lots** — potential rows with N₁ ≤ age < N₂. **All** — all non-deleted (no age filter). **Archived** — **`Purchase.deleted_at` not null** (Super Admin only). **restore** via **`POST /biomass/<id>/restore`** (`@admin_required`). Edits blocked until restored.
- **Migration:** **`_migrate_biomass_to_purchase()`** (startup) copies legacy **`BiomassAvailability`** rows into **`purchases`** / lots when needed; **`_backfill_purchase_approval()`** stamps **`purchase_approved_at`** on existing on-hand purchases missing it.

### Department UIs

- **Routes:** `GET /dept/` (`dept_index`) lists all department tiles; `GET /dept/<slug>` (`dept_view`) shows intro, **Quick links** (existing `url_for` targets + optional `#anchor`), and **`_department_stat_sections(slug)`** rollups (same DB as core screens).
- **Slugs:** `finance`, `biomass-purchasing`, `biomass-intake`, `biomass-extraction`, `thca-processing`, `hte-processing`, `liquid-diamonds`, `terpenes-distillation`, `testing`, `bulk-sales` — see `DEPARTMENT_PAGES` in `app.py`.
- **Quick links with query args:** e.g. `url_kwargs={"hte_stage": "awaiting_lab"}` → `GET /runs?hte_stage=awaiting_lab` (Flask `url_for` passes unknown keys as query parameters).
- **Testing / Terpenes rollups:** `_department_stat_sections("testing")` counts **Run** rows with `dry_hte_g > 0` by `hte_pipeline_stage` (plus supplier **`LabTest`** totals). `_department_stat_sections("terpenes-distillation")` reports strip-queue count, stripped count, and last-30-day sums of `hte_terpenes_recovered_g` / `hte_distillate_retail_g` on runs in stage **`terp_stripped`**.
- **Weekly finance snapshot:** `_weekly_finance_snapshot()` shared with Dashboard buyer budget card.
- **Data access:** reuse existing queries and models; no duplicate business rules.

### HTE post-extraction pipeline (runs)

Product behavior is summarized in **`PRD.md`** (Runs entity + material flow) and **`USER_MANUAL.md`** (operator steps).

- **Model (`models.py` — `Run`):**
  - `hte_pipeline_stage` — `NULL` / empty = not set; otherwise one of **`awaiting_lab`**, **`lab_clean`**, **`lab_dirty_queued_strip`**, **`terp_stripped`** (see `HTE_PIPELINE_ALLOWED` / `_hte_pipeline_options()` in `app.py`).
  - `hte_lab_result_paths_json` — JSON array of relative static paths (e.g. `uploads/labs/...`) for COA/lab PDFs or images.
  - `hte_terpenes_recovered_g`, `hte_distillate_retail_g` — floats; used when material is stripped and accounted.

- **Persistence:**
  - **SQLite:** `_ensure_sqlite_schema()` adds the four columns to **`runs`** if missing.
  - **PostgreSQL:** `_ensure_postgres_run_hte_columns()` runs from **`init_db()`** and issues `ALTER TABLE runs ADD COLUMN IF NOT EXISTS ...` (because `db.create_all()` does not migrate existing tables).

- **Write path:** `_save_run()` — after `flush()` so `run.id` exists, merges removals (`remove_hte_lab_paths[]`), appends **`_save_lab_files(..., prefix="hte-run-<id>")`**, stores JSON; parses optional terp/distillate floats from the form.

- **Read paths:** `runs_list` — optional **`hte_stage`** query filter; template gets `hte_label_map` / `hte_pipeline_options`. **`export_csv`** entity **`runs`** — extra CSV columns and the same filter when `hte_stage` is present.

### Slack remains authoritative for floor capture

- Ingestion/linking behavior continues to follow **Integrations — Slack** in `PRD.md` and the **Slack channel history sync** section below. Department pages should not assume web forms replace Slack until product changes **Operational input authority** in the PRD.

## `Timberly-Changes` (merged into `main`)

**`origin/Timberly-Changes`** was merged into **`main`** (commit message: merge Timberly-Changes). It adds the biomass purchasing dashboard, **`super_buyer`** role, field approvals, weekly purchasing targets, sidebar budget widget, field intake photo UX (`field_intake_photos.js`), supplier incomplete-profile modal/highlighting, and related docs. **Departments**, **HTE pipeline on runs**, and **`slack_ts_la`** were preserved during the merge.

## Slack channel history sync

### Data model

- **`SlackChannelSyncConfig`** (`slack_channel_sync_configs`): fixed slots `slot_index` 0–5, `channel_hint`, optional `resolved_channel_id`, optional `last_watermark_ts` (string Slack message `ts`, used as `conversations.history` `oldest` on incremental runs).
- **`SlackIngestedMessage`** (`slack_ingested_messages`): one row per ingested message; **unique** on `(channel_id, message_ts)` for deduplication.

SQLite adds the sync config table in `_ensure_sqlite_schema()`; other engines rely on `db.create_all()` plus any existing migration posture.

### Bootstrap

- `_ensure_slack_sync_configs()` ensures six rows exist. If the table was empty, **slot 0**’s `channel_hint` is copied from `SystemSetting` `slack_default_channel`.

### HTTP / UI

- **Save Slack + sync hints:** `POST /settings` with `form_type=slack`, including system settings fields and `sync_ch_0` … `sync_ch_5`. Hint change clears `resolved_channel_id` and `last_watermark_ts` for that row.
- **Run sync:** `POST /settings/slack_sync_channel` with `sync_days` (1–365). Resolves each non-empty hint via `conversations.list` (or passes through channel IDs), then pages `conversations.history` with helper `_slack_ingest_channel_history`.
- **Imports / triage / apply:** `GET /settings/slack-imports` — filtered list (date range, channels, promotion, coverage). `GET /settings/slack-imports/<msg_id>/preview` — Run preview. `GET /settings/slack-imports/<msg_id>/apply-run` — session prefill + redirect to `run_new`; optional `confirm=1` after duplicate interstitial. All three use **`slack_importer_required`** (`User.can_slack_import`: Super Admin or `is_slack_importer`).
- **User flag:** `POST /settings/users/<id>/toggle_slack_importer` (`@admin_required`), audit action `user_slack_importer`. Create-user form optional `new_slack_importer` (ignored for `super_admin` role).

### Sync semantics

- **No watermark:** `oldest = now - sync_days * 86400` (rolling window).
- **With watermark:** `oldest = last_watermark_ts`; after a successful page loop, watermark updates to the **maximum** `ts` observed in that run (or `time.time()` as a string when the channel had no qualifying messages and had no prior cursor).
- Audit log action `slack_channel_sync` uses entity id `multi` and JSON details summarizing per-channel counts and errors.

### Related code (indicative)

- `app.py`: Slack sync routes and bootstrap glue still live here (`SLACK_SYNC_CHANNEL_SLOTS`, `_ensure_slack_sync_configs`, `_slack_ingest_channel_history`, `settings_slack_sync_channel`, settings `form_type=slack` handler).
- `models.py`: `SlackChannelSyncConfig`, `SlackIngestedMessage`.
- `templates/settings.html`: Slack card (sync channel form), Maintenance (sync button).

### Slack apply / Run backlink (Phase 2)

- **Models (`models.py`):** `User.is_slack_importer`; `User.can_slack_import` property. `Run.slack_channel_id`, `Run.slack_message_ts`, `Run.slack_import_applied_at` (set on **new** run save when form includes Slack hidden fields).
- **SQLite:** `_ensure_sqlite_schema()` adds the new columns on existing DBs. **PostgreSQL / other:** ensure equivalent DDL via your migration process (`ALTER TABLE users …`, `ALTER TABLE runs …`).
- **Session prefill:** `SLACK_RUN_PREFILL_SESSION_KEY`; `_slack_run_prefill_put`, `_slack_filled_json_safe`, `_hydrate_run_from_slack_prefill` (ephemeral `Run` for template). Cleared after successful Slack-linked save.
- **Guards:** `slack_importer_required`; `run_new` is `@login_required` with branch logic: GET allows `can_slack_import` + session prefill without `can_edit`; POST and normal new-run GET still require `can_edit` except prefill viewer path.
- **Duplicate policy:** `_first_run_for_slack_message` before `db.session.add(run)`; interstitial template `slack_import_apply_confirm.html`. Hidden field `slack_apply_allow_duplicate`. Confirm path logs `slack_duplicate_apply_confirm` on `slack_ingested_message`.
- **Triage helpers:** `_slack_linked_run_ids_index`, `_slack_coverage_label(preview)` (full / partial / none aligned with PRD heuristic).
- **Audit:** Run `create` with JSON `details` when saved from Slack (`slack_import`, ids, `duplicate_apply`, `prefill_keys`).
- **Templates:** `slack_imports.html`, `slack_import_preview.html`, `slack_import_apply_confirm.html`, `run_form.html` (hidden Slack fields + `can_save_run`). `base.html` sidebar link when `current_user.can_slack_import`.
- **Lot-resolution additions (current):**
  - Slack preview loads ranked candidate lots through `services/lot_allocation.py`.
  - `templates/slack_import_preview.html` allows manual or split lot-weight entry and serializes the selection into `slack_selected_allocations_json`.
  - `services/slack_workflow.py` validates `slack_selected_allocations_json` and preserves it through duplicate-confirm passthrough.
  - `gold_drop/runs_module.py` hydrates those selected lot rows into the Run form.
  - `templates/run_form.html` shows live allocation totals, target vs delta, and projected remaining balances per lot row. Client-side summary is advisory; server-side validation remains authoritative.
  - `templates/slack_imports.html` now groups rows into inbox buckets (`auto_ready`, `needs_confirmation`, `needs_manual_match`, `blocked`, `processed`) while still showing promotion and coverage dimensions.

## Scale-readiness

- **Models (`models.py`)**
  - `ScaleDevice` - connection / protocol metadata for future connected scales
  - `WeightCapture` - accepted weight evidence linked to purchase, lot, run, and optional device
- **Service boundary**
  - `services/scale_ingest.py`
    - `parse_ascii_scale_payload`
    - `create_weight_capture`
- **Current scope**
  - No live hardware polling yet.
  - The model is ready for manual vs device-captured weights and stores raw payload, source mode, stability flag, and linked operational object ids.

## Time handling and test runner notes

- App/runtime timestamps now use timezone-aware UTC (`datetime.now(timezone.utc)` or model-level `utc_now()` helpers) instead of `datetime.utcnow()`.
- `models.py` includes `coerce_utc()` so older naive `expires_at` values can still be compared safely.
- `pytest.ini` disables pytest cache provider (`-p no:cacheprovider`) because `.pytest_cache` is unreliable in this environment; normal local test runs should no longer emit cache warnings.

### Slack → field mappings (Phase 1)

- **Storage:** `SystemSetting` key `slack_run_field_mappings`, JSON `{"rules": [ ... ]}`. Seeded in `init_db()` when missing.
- **Rule shape:** `source_key`, `target_field`, `message_kinds`, `transform`; optional **`destination`** (`run` default). Allowed destinations: `run`, `biomass`, `purchase`, `inventory`, `photo_library`, `supplier`, `strain`, `cost`. For `run`, `target_field` must be in `SLACK_MAPPING_ALLOWED_TARGET_FIELDS`; for others, a **snake_case** placeholder string (`SLACK_NON_RUN_TARGET_FIELD_RE`) until that module ships an allowlist.
- **Editor:** `GET/POST /settings/slack-run-mappings` — grid: destination, Slack source, target (Run = select; other = text), message-kind scope, transform + arg. Initial row count is `_slack_mapping_grid_row_count(rules)`; client script grows/shrinks trailing blank rows. Hints update live. POST scans `rule_destination_i`, `rule_target_select_i` / `rule_target_text_i`, etc. **Save mappings** / **Reset** / **Save JSON** as before.
- **Preview:** `GET /settings/slack-imports/<msg_id>/preview` — `_preview_slack_to_run_fields` applies only rules with `destination` **`run`** (or omitted); keys consumed by other destinations are still marked consumed for **unmapped** derivation. Preview is also used for **apply** prefill; persistence to `runs` happens only via the Run form save path.
- **Helpers:** `_apply_slack_mapping_transform`, `_validate_slack_run_field_rules`, `_preview_slack_to_run_fields`, coverage helpers, and parser helpers now live in **`gold_drop/slack.py`**. Rule loading / persistence still happens from the settings flow in `app.py`.

### Gunicorn / multi-worker startup

`init_db()` still runs during startup from `app.py`. With multiple sync workers, `db.create_all()` can race and one worker may see “table already exists” / duplicate relation. `init_db()` ignores those specific errors and continues; you can also set **`--preload`** on Gunicorn so the app loads once before workers fork (see `golddrop.service` `ExecStart`).

## Purchase spreadsheet import

- **Module:** `purchase_import.py` — `PURCHASE_IMPORT_HEADER_ALIASES` / `_aliases_groups` map normalized headers (lowercase, spaces → underscores) to canonical purchase fields; `parse_purchase_spreadsheet_upload(filename, raw_bytes)` returns rows as `dict` plus `_sheet_row` for display. Supports **CSV** (UTF-8-SIG) and **Excel** via **openpyxl** `load_workbook(..., read_only=True, data_only=True)` on the active sheet.
- **Detection:** Scans the first **50** grid rows for a header line with **≥2** mapped columns; requires a **supplier** column. Max **2000** data rows.
- **Routes (Flask):** `GET/POST /purchases/import` (`purchase_import`, `@purchase_editor_required`), `GET /purchases/import/preview`, `POST /purchases/import/commit`, `GET /purchases/import/sample.csv`. Upload writes a staging JSON file under `tempfile.gettempdir()` named `gdp_purchimp_<token>.json`; only a random token is stored in `session["purchase_import_token"]`.
- **Validation / commit:** `gold_drop/purchase_import_module.py` — `_purchase_import_validate_row`, `_purchase_import_commit_norm`; reuses `_maintain_purchase_inventory_lots`, purchase budget helpers from **`gold_drop/purchases.py`**, and `log_audit`. Imported rows do **not** set **`purchase_approved_at`**; if parsed **`status`** ∈ **`INVENTORY_ON_HAND_PURCHASE_STATUSES`**, commit forces **`ordered`** instead. Optional **Amount** → `total_cost`; **Paid date** / **Week** / **Payment method** folded into **notes**; **invoice** weight can fall back to **actual** weight; **purchase date** can fall back to **paid date** when purchase date is blank.
- **Templates:** `purchase_import.html`, `purchase_import_preview.html`. Client uses `DataTransfer` so drag-and-drop assigns `input.files` in modern browsers.
- **Dependency:** `openpyxl>=3.1.0` in `requirements.txt`.

## Batch list editing

- **Module:** `batch_edit.py` — pure apply helpers: `parse_uuid_ids`, `apply_batch_runs`, `apply_batch_purchases` (returns `touched` purchases for hooks), `apply_batch_biomass`, `apply_batch_suppliers`, `apply_batch_costs`, `apply_batch_inventory_lots`, `apply_batch_strain_rename`. Max **200** UUIDs per batch. Strain rename uses `STRAIN_PAIR_SEP` (`\\x1f`) between strain name and supplier name in checkbox values / query params.
- **Route:** `GET/POST /batch-edit/<entity>` (`batch_edit` in `gold_drop/batch_edit_module.py`, `@login_required`). Entities: `runs`, `purchases`, `biomass`, `suppliers`, `costs`, `inventory_lots`, `strains`. Permission: `can_edit` for runs/biomass/costs/suppliers/strains; `can_edit_purchases` for purchases and inventory lots. **`return_to`** query/body param must be a safe relative path (`safe_batch_return_url`).
- **Purchases batch:** After `apply_batch_purchases`, for each touched purchase: `_maintain_purchase_inventory_lots`, budget enforcement (`_biomass_budget_snapshot_for_purchase`, `_enforce_weekly_biomass_purchase_limits`). **`ValueError`** from budget rules rolls back the whole batch commit attempt.
- **Biomass batch:** `apply_batch_biomass` updates **`Purchase`** rows (pipeline list IDs are purchase UUIDs); audit action **`purchase_batch_biomass`**.
- **Runs batch:** Optional fields only; `run_type`, `hte_pipeline_stage` (form uses `__nochange__` sentinel vs cleared stage), rollover/decarb tri-state, optional load source + checkbox, `notes_append`; `calculate_yields` + `calculate_cost` per changed run.
- **Audit:** Single `log_audit("update", "<entity>_batch", gen_uuid(), details=count)` (or strain rename) per successful batch, not per row.
- **Client:** `static/js/batch_select.js` — `[data-batch-toolbar]` wires **Select all** / **Select none** / **Batch edit**; scopes checkboxes via `data-table-selector` or `data-batch-scope` (suppliers cards). Minimum selection **2** (`data-batch-min` default).
- **Template:** `templates/batch_edit.html` — entity-specific form sections; strains POST repeats `pair` hidden fields from GET query `pair=...` list.

## Inventory (`GET /inventory`)

- **Route:** `inventory()` in `gold_drop/inventory_module.py`; template `templates/inventory.html`.
- **On-hand lots:** `PurchaseLot` joined to `Purchase` where `remaining_weight_lbs > 0`, both not soft-deleted, `Purchase.status` ∈ `INVENTORY_ON_HAND_PURCHASE_STATUSES` (**`delivered`**, **`in_testing`**, **`available`**, **`processing`** — note **`complete`** is not in this tuple), and **`Purchase.purchase_approved_at` IS NOT NULL**. Optional `supplier_id` and case-insensitive `strain` substring on `PurchaseLot.strain_name`. Same approval filter on **dashboard** on-hand / days-of-supply, **`GET /api/lots/available`**, and **run form** lot query.
- **In transit:** `Purchase` not deleted, `status` ∈ `("committed", "ordered", "in_transit")`. Optional `supplier_id` only—**no strain filter**, so summary **Total** can mix strain-filtered on-hand with full in-transit for that supplier.
- **Summary:**
  - `total_on_hand` = sum of `remaining_weight_lbs` over filtered on-hand lots.
  - `total_in_transit` = sum of `stated_weight_lbs` over filtered in-transit purchases.
  - `days_supply` = `total_on_hand / daily_target` where `daily_target = SystemSetting.get_float("daily_throughput_target", 500)`; if `daily_target <= 0`, `days_supply = 0`. **In-transit weight is not in the numerator.**
- **UI labels:** summary tile **Total** = `total_on_hand + total_in_transit` (not labeled “available”).
- **Dashboard KPIs:** a separate `days_of_supply` in the dashboard KPI block uses the same on-hand aggregate (unfiltered) ÷ same setting; see `kpi_actuals["days_of_supply"]` in `app.py` when runs exist in the selected period.

## Batch Journey Progress Tracker (engineering status + outline)

Implemented baseline: clickable journey page + JSON API + JSON/CSV export for a purchase batch.

### Data strategy (v1)
- **Derived timeline** from existing tables (`Purchase`, `PurchaseLot`, `RunInput`, `Run`, plus future sales records) keyed by `purchase_id`.
- No new canonical “stage history” table required for v1; compute milestones from timestamps/status fields already present.

### Endpoint shape (implemented)
- `GET /purchases/<id>/journey` (HTML timeline page)
- `GET /api/purchases/<id>/journey` (JSON event model for UI/export)
- `GET /purchases/<id>/journey/export?format=json|csv` (download)
- Routes are now served from `blueprints/purchases.py`; payload generation lives in `services/purchases_journey.py` (no lazy runtime import of `app`).

### Event model (current payload)
- `stage_key`: declared | testing | committed | delivered | inventory | extraction | post_processing | sales
- `state`: done | in_progress | blocked | not_started | not_applicable
- `started_at`, `completed_at`
- `metrics`: lbs/g/$ summary at that stage
- `links`: list of source record URLs/ids
- `lots`: purchase-lot payloads including tracking id, original / allocated / remaining lbs, potency, testing state, and clean / dirty state
- `allocations`: explicit `RunInput` edges from lot to run
- `runs`: downstream run nodes used by the HTML timeline and API consumers

### UI notes
- Render as stepper/timeline with status colors and tooltips.
- Show partial completion (e.g., some lots consumed in runs, others still on-hand).
- Include “last updated” and “include archived” toggles for audit contexts.
- Include direct **Export JSON** / **Export CSV** actions on the journey page.
- `templates/purchase_journey.html` now includes dedicated **Inventory Lots** and **Run Allocations** sections rather than only stage summaries.

## Purchase form parity + lot splitting

- `templates/purchase_form.html` now surfaces `availability_date` and `testing_notes` on the main purchase form so mobile opportunity edits round-trip through the same `Purchase` row.
- `gold_drop/purchases_module.py` purchase save logic persists those shared fields from the main form instead of leaving them mobile-only.
- Confirmed-lot splitting is handled by `lot_split_view(...)` plus `POST /lots/<lot_id>/split`.
- Split rules:
  - source lot must exist and have remaining inventory
  - split weight must be greater than zero
  - split weight must be strictly less than current remaining inventory
  - original lot weight and remaining weight are reduced
  - new child lot copies base metadata, can accept form overrides for strain/location/potency/notes, and receives fresh tracking fields through `ensure_lot_tracking_fields(...)`
  - audit writes action `split` with child-lot details so later review can trace lineage
