# Gold Drop — Biomass Inventory & Extraction Tracking System

**Product requirements** live in `PRD.md` (Summary plus **Operational departments & shared data model**, **Users & Permissions**, **Potential pipeline records — Old Lots and soft deletion**).
**User guide** lives in `USER_MANUAL.md` (no credentials included).
**FAQ** lives in `FAQ.md`.
**Engineering notes** (implementation-oriented) live in `ENGINEERING.md` (see **PRD implementation notes — departments, approvals, aging** and **HTE post-extraction pipeline (runs)**).

## Quick Start (Local Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open **http://localhost:5050** in your browser (default dev port; **5000** is often busy on macOS because of AirPlay). To use another port: `PORT=5000 python app.py` or `PORT=8080 python app.py`.

## Where to test the implementation so far

After logging in as **admin**:

1. **Purchases list + Journey entrypoint**
   - Open: `http://localhost:5050/purchases`
   - Click **Journey** on any purchase row.
2. **Purchase form + Journey entrypoint**
   - Open a purchase edit page: `http://localhost:5050/purchases/<purchase_id>/edit`
   - Click **View Journey** in the header.
3. **Journey page (UI)**
   - Open: `http://localhost:5050/purchases/<purchase_id>/journey`
   - Validate stage cards, inventory lots, run allocations, tracking IDs, and drill links.
4. **Slack preview -> run allocation flow**
   - Open: `http://localhost:5050/settings/slack-imports`
   - Preview a synced message, review candidate lots, optionally split lot weights, then open **Create run from Slack**.
5. **Run form allocation summary**
   - Open: `http://localhost:5050/runs/new`
   - Validate the live allocation summary, projected remaining lot balances, and exact-match requirement against **Lbs in Reactor**.
6. **Scanner workflow**
   - Open a lot label or copy any lot tracking ID, then open: `http://localhost:5050/scan/lot/<tracking_id>`
   - Validate the scan landing page, **Open Charge Form**, **Confirm Movement**, **Confirm Testing**, and recent scan activity.
7. **Extraction charge workflow**
   - From a scanned lot or from **Purchases -> Edit -> Charge Lot**, record lbs, reactor, and charge time.
   - Confirm the app opens **New Run** with the saved charge already attached.
8. **Journey API (JSON)**
   - Open: `http://localhost:5050/api/purchases/<purchase_id>/journey`
   - Optional admin-only archived mode: `?include_archived=1`
9. **Journey exports**
   - JSON export: `http://localhost:5050/purchases/<purchase_id>/journey/export?format=json`
   - CSV export: `http://localhost:5050/purchases/<purchase_id>/journey/export?format=csv`

Tip: to quickly find a `purchase_id`, open DevTools on the Purchases page and copy it from the Journey/Edit link URL.

### Default Login Credentials

| Username | Password       | Role        |
|----------|----------------|-------------|
| admin    | golddrop2026   | Super Admin |
| ops      | golddrop2026   | User        |
| viewer   | golddrop2026   | Viewer      |

**Change these passwords immediately after first login via Settings.**

---

## Features

- **Docs update (Apr 2026)** — Journey endpoints now share one validation path for missing/archived purchases, and Journey export rejects unsupported formats with an explicit `400` JSON error (`{"error":"Unsupported export format","supported_formats":["csv","json"]}`) instead of silently defaulting.
- **Dashboard** — KPI cards with configurable green/yellow/red traffic lights (on-hand biomass and days-of-supply use **approved** purchases only; see **Purchases** below)
- **Biomass purchasing** — Landing page (`/biomass-purchasing`) for weekly buyer targets vs actuals, office-created purchase opportunities, field submission queues, and reviewed history (first sidebar item after **Extraction**)
- **Run Logging** — Log extraction runs with source lots, wet/dry HTE & THCA output, and live source-lot allocation status against **Lbs in Reactor**; optional **HTE post-extraction pipeline** (lab staging, clean vs dirty, COA file attachments, terp-strip queue, terpenes + retail distillate grams after Prescott strip)
- **Departments** — Focused lenses (`/dept`, `/dept/<slug>`) on the same data: quick links, rollups, and filtered run lists (e.g. HTE pipeline stage) for finance, purchasing, intake, extraction, THCA/HTE/LD, terpenes, testing, bulk sales
- **Auto-Calculations** — Yield %, cost per gram, true-up amounts calculated automatically
- **Costs** — Enter solvent/personnel/overhead costs with date ranges; allocated into $/g
- **Cost Allocation Settings** — Choose THCA vs HTE allocation (uniform, 50/50, custom %)
- **Inventory** — Track biomass on hand, in transit, and days of supply, with per-lot remaining pounds and lot tracking IDs tied into live label / scan workflows; on-hand rows now include direct `Edit`, `Charge`, and `Scan` actions for faster operator navigation, and `Edit` now opens a dedicated lot form so lot-level changes do not accidentally alter purchase-level inventory status
- **Purchases** — Record purchases with potency-based pricing and true-up tracking, including pipeline-side `availability_date`, testing notes, and post-confirmation lot management from the main purchase form
- **Batch Journey** — Per-purchase lifecycle timeline (UI + API + export): open from Purchases list (**Journey**) or Purchase edit (**View Journey**) to see derived stages (`declared`, `testing`, `committed`, `delivered`, `inventory`, `extraction`, `post_processing`, `sales`) plus explicit **inventory lots**, **run allocations**, tracking IDs, remaining pounds, and drill links.
- **Purchase spreadsheet import** — Upload **.csv**, **.xlsx**, or **.xlsm** via **Purchases → Import spreadsheet** (drag-and-drop or browse). Headers are mapped automatically (e.g. Vendor, Purchase Date, Invoice Weight, Actual Weight, Manifest, Amount, Paid Date, Payment Method, Week). Preview validates rows; commit creates **unapproved** purchases (on-hand statuses from the file are capped to **ordered** until **Approve purchase**). Optional auto-create suppliers. See `purchase_import.py` (header alias map) and `ENGINEERING.md` → **Purchase spreadsheet import**.
- **Batch edit (list screens)** — On Runs, Purchases, Inventory (on-hand lots and in-transit purchases), Biomass Pipeline, Suppliers, Costs, and Strain Performance, use row checkboxes plus **Select all** / **Select none**; with **two or more** rows selected, **Batch edit…** opens a screen to apply the same field changes to all selected records (permissions match single-record edit). Strain performance uses **Batch rename…** to retag matching purchase lots.
- **Batch IDs** — Unique, readable batch IDs for all purchases (auto-generated if blank)
- **Biomass Pipeline** — Same **`Purchase`** rows as **Purchases**: early statuses **`declared`** / **`in_testing`** (UI label *Testing*), then **`committed`**, **`delivered`**, **`cancelled`**, with pipeline fields on the purchase (`availability_date`, declared weight/price, testing metadata, field photos). No separate `BiomassAvailability` sync—one record end-to-end. **Super Admin** or **`is_purchase_approver`** must approve when moving **to or from Committed** on the pipeline form (stamps `purchase_approved_at`). Unapproved rows now also expose an inline **Approve** button directly in the Biomass Pipeline list for eligible approvers.
- **Purchase approval gate** — On-hand inventory, dashboard on-hand, run lot pickers, and saving runs that consume lots require **`purchase_approved_at`**. You cannot set on-hand statuses (**delivered**, **in_testing**, **available**, **processing**) on **Edit Purchase** until approved. Existing on-hand purchases are **backfilled** as approved on startup. Slack **biomass intake** creates purchases as **`ordered`** until reviewed/approved per your process. Eligible approvers can now approve directly from the **Purchases** list or **Biomass Pipeline** list without opening the record first.
- **Lot tracking IDs** — Purchase lots now receive machine-readable tracking fields (`tracking_id`, barcode payload, QR payload, label metadata) at creation or approval time, and printable labels now render both a Code 39 barcode and a QR code for floor execution.
- **Confirmed lot splitting** — Edit Purchase now includes **Split Existing Lot** so operators can break a confirmed lot's remaining inventory into a new child lot without leaving the purchase workflow; the original lot is reduced, the child lot gets fresh tracking fields, and the action is audited.
- **Extraction charge workflow** — A lot can now be charged into production from either the main purchase form (**Charge Lot**) or the scanned-lot workflow. The app records a persisted extraction-charge event with lbs, reactor, charge time, notes, and source mode before opening the run form.
- **Scanner workflows** — Scanned lot labels now open a dedicated lot workflow page with quick actions for **Open Charge Form**, **Confirm Movement**, **Confirm Testing**, **Print Label**, and recent scan activity history.
- **Guided floor execution** — The scanned-lot page now supports guided run-start modes (**blank**, **full remaining lot**, **partial amount**, **scale capture first**) plus standardized movement actions for **vault**, **reactor staging**, **quarantine**, **inventory return**, or a custom location.
- **Floor Ops** — A dedicated operator floor page surfaces recent scan activity, recent scale captures, open lot counts, active device counts, floor-state rollups, and extraction-readiness counts in one place, with a direct **Scan Center** launcher and a now-consistent card layout across summaries, queues, and recent activity sections.
- **Reactor charge queue** — `Floor Ops` now also shows pending extraction charges by reactor and recently applied charges that have already been linked to saved runs, giving extractors a simple queue view without opening each run record.
- **Tablet camera scanning** — `/scan` provides an in-browser camera scanning page for supported mobile browsers, with manual and Bluetooth-scanner fallback when camera barcode detection is unavailable.
- **Scanner intelligence** — Scan activity is also exposed through internal API scanner endpoints and MCP tools (`scanner_summary`, `lot_scan_history`) for future floor analytics and AI workflows.
- **Smart-scale live integration** — Admins can register scale devices, test raw payload ingestion in Settings, capture live allocation weights on the run form, and inspect scale data through internal API and MCP read layers.
- **Gated cross-site ops UI** — Cross-site dashboards remain hidden until a Super Admin enables **Cross-Site Ops UI** for the site in Settings. When enabled, the app exposes:
  - `/cross-site`
  - `/cross-site/suppliers`
  - `/cross-site/strains`
  - `/cross-site/reconciliation`
  backed by the existing cached aggregation layer rather than live multi-site fan-out.
- **Field Photo Uploads** — Field users can attach multiple photos to biomass and purchase submissions (JPG/JPEG/PNG/WEBP/HEIC/HEIF, max 50 MB each)
- **Field Purchase Intake Enhancements** — Harvest date, storage note, license info, queue placement, testing/COA status, and categorized photo uploads
- **Soft Delete + Admin Hard Delete** — Runs and purchases support safe delete plus super-admin permanent cleanup
- **Historical Lab Tracking** — Supplier-level lab test history and file attachments (including PDF lab docs)
- **Photo Library** — Central searchable media index with supplier/purchase/category/tag filters
- **Photo Audit Linkage** — Approved field photos are auto-linked to supplier docs (license) and purchase audit records (biomass/COA)
- **Advanced Exports** — Date range and criteria filters (supplier/status/potency/strain) across operational tabs
- **Saved list filters** — Runs, Purchases, Biomass Pipeline, Costs, Inventory, Strains, and **Slack imports** remember your filters, date ranges, sort order, and related query state in your **session** while you work, so you can navigate elsewhere and return without re-applying them; use **Remove filters** for a clean default view. Applying filters or changing status tabs resets **pagination** to page 1 so narrowed results are not hidden on a stale page.
- **Purchases list** — Optional **Hide complete & cancelled** on the filter row; **Export CSV** can follow the same option when active.
- **Purchase form** — **Save Purchase** at the top of the screen (same submit as the bottom) for long forms.
- **Windows / IANA timezones** — `tzdata` is listed in `requirements.txt` so `zoneinfo` (Slack message dates, display timezone) works on Windows; install dependencies with `pip install -r requirements.txt`.
- **Slack Integration** — Outbound notifications; inbound slash commands, interactivity, and Events API URL (`/api/slack/events`); optional **channel history sync** for up to six channels with per-channel cursors (`conversations.history` → **Slack imports** triage UI); **Run apply** now includes ranked candidate source lots, manual lot selection or split allocation on preview, prefilled run allocation rows, Run backlink + audit, and **Slack Importer** user flag
- **Supplier Performance** — All-time, 90-day, and last-batch analytics per farm
- **Supplier Merge / Correction** — Super Admins can preview and merge duplicate suppliers from the supplier record page; linked purchases, lots, lab tests, attachments, and photos are rehomed while lineage is preserved
- **Supplier duplicate warnings** — Main-app supplier creation and the standalone buyer flow now warn on typo-close supplier names before saving, while the existing merge workflow remains available for cleanup when duplicates already exist.
- **Strain Performance** — Compare yields and cost/gram across strains and suppliers
- **Data Quality Controls** — Flag runs missing $/lb; optionally exclude unpriced runs from analytics
- **CSV Import/Export** — **Runs** (and related operational history): Import from Google Sheets via **Import** with deduplication; export filtered views from list screens. **Purchases** use the dedicated **Import spreadsheet** flow (see above), not the legacy Import screen.
- **Role-Based Access** — Super Admin, User, and Viewer roles
- **Configurable KPIs** — Set targets and thresholds; change them as operations improve

---

## Project Structure

### Current UX / automation-ready additions

- Purchases and Inventory now emphasize allocation state, exceptions, remaining pounds, tracking readiness, and next actions.
- Slack imports now behaves more like an inbox, with triage buckets that distinguish auto-ready rows from rows needing confirmation, manual matching, or exception handling.
- Printable lot label pages now render both a scannable barcode and QR code and route into `/scan/lot/<tracking_id>` for direct floor execution.
- The scanned-lot page now records richer operator activity context, including guided run-start mode, planned partial weight, movement action, and location/testing confirmations.
- Tablet/mobile operators can also open `/scan` to use the browser camera and route directly into `/scan/lot/<tracking_id>` when barcode detection is supported.
- The data model now includes `ScaleDevice` and `WeightCapture` for future smart-scale integration work.
- Cross-site operator/admin UI is now feature-gated by a site-level setting so non-multi-site deployments do not see those surfaces by default.

The app still starts from `app.py`, but the active route surface now lives across focused package modules in `gold_drop/`. `app.py` remains the entrypoint, app-factory host, and compatibility layer while route registration and startup bootstrap delegate into extracted modules.

Current extracted route/bootstrap modules:
- `gold_drop/dashboard_module.py`
- `gold_drop/floor_module.py`
- `gold_drop/field_intake_module.py`
- `gold_drop/runs_module.py`
- `gold_drop/purchases_module.py`
- `gold_drop/biomass_module.py`
- `gold_drop/costs_module.py`
- `gold_drop/inventory_module.py`
- `gold_drop/batch_edit_module.py`
- `gold_drop/suppliers_module.py`
- `gold_drop/purchase_import_module.py`
- `gold_drop/strains_module.py`
- `gold_drop/settings_module.py`
- `gold_drop/slack_integration_module.py`
- `gold_drop/bootstrap_module.py`
- `services/lot_allocation.py`

```
gold-drop/
├── app.py              # Entrypoint shim + Flask app factory (`create_app`)
├── models.py           # SQLAlchemy database models
├── purchase_import.py  # Purchase spreadsheet parsing + header alias map (CSV / Excel)
├── batch_edit.py       # Batch update helpers (runs, purchases, biomass, suppliers, costs, lots, strain rename)
├── gold_drop/
│   ├── __init__.py     # Package entrypoint exposing `create_app`
│   ├── auth.py         # Login manager + access decorators
│   ├── audit.py        # Audit log helper
│   ├── list_state.py   # Session-backed list filters + timezone/channel helpers
│   ├── purchases.py    # Purchase budget / on-hand helper logic
│   ├── settings_module.py # Settings/admin flow extracted behind app route delegates
│   ├── slack.py        # Slack parsing, mapping, preview, and triage helpers
│   └── uploads.py      # Upload validation + file persistence helpers
├── requirements.txt    # Python dependencies
├── PRD.md              # Product requirements document
├── USER_MANUAL.md      # End-user / operator guide
├── FAQ.md              # Short frequently asked questions
├── ENGINEERING.md      # Implementation and schema notes for developers
├── static/
│   ├── css/
│   │   └── style.css       # Application styles
│   ├── js/
│   │   └── batch_select.js # List checkboxes: select all/none, navigate to batch edit
│   └── uploads/            # field/, labs/, purchases/, library/ (created at runtime)
└── templates/
    ├── base.html           # Layout with sidebar navigation
    ├── login.html          # Login page
    ├── dashboard.html      # KPI dashboard
    ├── runs.html           # Run list view (optional HTE pipeline filter)
    ├── run_form.html       # New/edit run form (HTE lab & terp pipeline section)
    ├── dept_index.html     # Department hub tiles
    ├── dept_view.html      # Single department intro + stats + quick links
    ├── inventory.html      # Inventory position view
    ├── purchases.html      # Purchase list view (batch selection + link to import)
    ├── purchase_form.html  # New/edit purchase form
    ├── purchase_import.html        # Purchase spreadsheet upload (drag-and-drop)
    ├── purchase_import_preview.html # Parsed rows + validation before commit
    ├── batch_edit.html     # Batch apply form (entity-specific fields)
    ├── biomass.html        # Biomass pipeline list view
    ├── biomass_form.html   # New/edit biomass pipeline record
    ├── costs.html          # Operational cost entries list view
    ├── cost_form.html      # New/edit cost entry form
    ├── suppliers.html      # Supplier performance view
    ├── supplier_form.html  # New/edit supplier form
    ├── strains.html        # Strain performance view
    ├── settings.html       # Admin settings (KPIs, system config, users)
    ├── slack_imports.html  # Slack channel imports list + filters + apply
    ├── slack_import_preview.html
    ├── slack_import_apply_confirm.html
    ├── slack_run_mappings.html
    ├── import.html         # CSV import upload
    └── import_review.html  # Import preview and confirmation
├── tests/
│   ├── test_app_factory.py # App factory + route registration smoke test
│   ├── test_slack_mapping_logic.py
│   └── test_slack_run_mappings_render.py
├── flowchart.html          # Standalone Mermaid flow reference (open in browser; not a Flask route)
```

---

## Deploying to Production

Testing note: `pytest.ini` disables pytest's cache provider (`-p no:cacheprovider`) because `.pytest_cache` is not reliable in this environment.

Current deployment note: the Flask app is still created through `create_app()` in `app.py`, but active route registration now fans out through the extracted `gold_drop/*_module.py` files and startup bootstrap delegates through `gold_drop/bootstrap_module.py`.

After merging work into **`main`**, deploy by pulling on the server (`git fetch` / `git checkout main` / `git pull`) and **restarting the app process** (e.g. `systemctl restart …`) so Gunicorn reloads code. The Flask app is created through `create_app()` in `app.py`, and database bootstrap still runs during startup. New database columns are applied on startup: SQLite via **`init_db()`** + **`_ensure_sqlite_schema()`**; PostgreSQL via **`init_db()`** + **`_ensure_postgres_run_hte_columns()`** (and `db.create_all()` for new tables).

**Important:** restart from the project root (the directory that contains `app.py`, `models.py`, `templates/`, and `requirements.txt`).
- Normal startup now seeds only baseline users, settings, KPI targets, and Slack mapping defaults. Historical/demo records are loaded only when you run the explicit demo seed script.
- In this repo/environment that directory is: `/workspace/gold-drop-production_tracker`
- In the VPS example below it is: `/opt/gold-drop`

### Update + restart commands (current directory)

If you are already in `/workspace/gold-drop-production_tracker`, run:

```bash
git fetch origin
git checkout codex_review   # or main, depending on your deploy branch
git pull --ff-only

# If using systemd + gunicorn service
sudo systemctl restart golddrop
sudo systemctl status golddrop --no-pager -l
```

If you are running directly (no systemd), restart the dev server in this same directory:

```bash
pkill -f "python app.py" || true
python app.py
```

### If `git checkout codex_review` fails with `pathspec ... did not match`

That means the branch does not exist in **your** repository clone yet.

Try:

```bash
git fetch --all --prune
git branch -a
git checkout -b codex_review   # create local branch from current HEAD
```

If you expected a remote branch named `codex_review`, use:

```bash
git fetch origin codex_review
git checkout -t origin/codex_review
```

### Option 1: DigitalOcean / Render / Railway

1. Push this directory to a Git repository
2. Connect to your hosting platform
3. Set environment variables:
   - `SECRET_KEY` — a random string (e.g., `python -c "import secrets; print(secrets.token_hex(32))"`)
   - `DATABASE_URL` — PostgreSQL connection string (for production; SQLite works for small deployments)
4. Run with: `gunicorn app:app --bind 0.0.0.0:8000`

### Option 2: VPS (Ubuntu)

```bash
# On your server
sudo apt update && sudo apt install python3-pip python3-venv nginx

# Set up app
git clone <your-repo> /opt/gold-drop
cd /opt/gold-drop
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Create systemd service
sudo tee /etc/systemd/system/golddrop.service << EOF
[Unit]
Description=Gold Drop Biomass Tracker
After=network.target

[Service]
User=www-data
WorkingDirectory=/opt/gold-drop
Environment=SECRET_KEY=your-secret-key-here
ExecStart=/opt/gold-drop/venv/bin/gunicorn app:app --bind 127.0.0.1:8000
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable golddrop
sudo systemctl start golddrop
```

### Fresh operational reset

Use the reset script when you want a clean working database without losing the ability to log in.

What it keeps:
- users and passwords
- system settings and KPI targets
- Slack sync configuration
- cost entries
- scale-device configuration

What it clears:
- purchases and lots
- runs and run inputs
- Slack imported rows
- field submissions and intake tokens
- suppliers, attachments, lab tests, and photo assets
- audit/history rows

It creates a SQLite backup automatically when a SQLite DB file is present.

```bash
cd /opt/gold-drop
source venv/bin/activate
python scripts/reset_operational_data.py --yes
sudo systemctl restart golddrop
```

If you intentionally want the old demo/historical dataset in a fresh environment, seed it explicitly:

```bash
cd /opt/gold-drop
source venv/bin/activate
python scripts/seed_demo_data.py --yes
sudo systemctl restart golddrop
```

## Internal API

This app now exposes a read-only internal API under `/api/v1` for trusted internal consumers.

Formal reference:
- [API_REFERENCE.md](API_REFERENCE.md)

Current endpoints:
- `/api/v1/site`
- `/api/v1/capabilities`
- `/api/v1/sync/manifest`
- `/api/v1/aggregation/sites`
- `/api/v1/aggregation/sites/<site_id>`
- `/api/v1/aggregation/summary`
- `/api/v1/aggregation/suppliers`
- `/api/v1/aggregation/strains`
- `/api/v1/search`
- `/api/v1/tools/inventory-snapshot`
- `/api/v1/tools/open-lots`
- `/api/v1/tools/journey-resolve`
- `/api/v1/tools/reconciliation-overview`
- `/api/v1/summary/dashboard`
- `/api/v1/departments`
- `/api/v1/departments/<slug>`
- `/api/v1/purchases`
- `/api/v1/purchases/<purchase_id>`
- `/api/v1/purchases/<purchase_id>/journey`
- `/api/v1/lots`
- `/api/v1/lots/<lot_id>`
- `/api/v1/lots/<lot_id>/journey`
- `/api/v1/runs`
- `/api/v1/runs/<run_id>`
- `/api/v1/runs/<run_id>/journey`
- `/api/v1/suppliers`
- `/api/v1/suppliers/<supplier_id>`
- `/api/v1/strains`
- `/api/v1/slack-imports`
- `/api/v1/slack-imports/<msg_id>`
- `/api/v1/exceptions`
- `/api/v1/summary/inventory`
- `/api/v1/summary/slack-imports`
- `/api/v1/summary/exceptions`
- `/api/v1/inventory/on-hand`

Authentication:
- bearer token only
- no session-cookie fallback
- JSON `401` / `403` responses on auth failure

Create an internal API token:

```bash
cd /opt/gold-drop
source venv/bin/activate
python scripts/create_api_client.py --name "internal-bi" --scopes read:site,read:lots,read:inventory,read:journey
```

Super Admins can also create, revoke, reactivate, and delete internal API clients directly in:

- `Settings -> Internal API Clients`
- `Settings -> Remote Sites`

New bearer tokens are shown only once at creation time.

Useful read scopes now include:
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
- `read:suppliers`
- `read:strains`

Example request:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" http://127.0.0.1:5050/api/v1/site
```

Search example:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN_HERE" "http://127.0.0.1:5050/api/v1/search?q=farmlane&types=suppliers,purchases,lots"
```

Aggregation cache refresh:

```bash
cd /opt/gold-drop
source venv/bin/activate
python scripts/pull_remote_sites.py
```

Every `/api/v1` response includes:
- `site_code`
- `site_name`
- `site_timezone`
- `site_region`
- `site_environment`
- `generated_at`
- `api_version`

List and search responses also now expose normalized contract metadata:
- `count`
- `limit`
- `offset`
- `sort`
- `filters`

`sort` reports the applied default ordering for the endpoint, and `filters` echoes the normalized filter values the API actually used after validation/defaulting. Internal consumers should prefer these values over inferring behavior from request strings.

The site identity values come from `SystemSetting` and can be edited in:

- `Settings -> Operational Parameters`

The API-facing site identity fields are:
- `site_code`
- `site_name`
- `site_timezone`
- `site_region`
- `site_environment`

## MCP server

This repo now also includes a read-only stdio MCP server that wraps the internal domain logic directly for local/internal AI and automation workflows.

Run it from the project root:

```bash
cd /opt/gold-drop
source venv/bin/activate
python scripts/mcp_server.py
```

Current MCP tools include:
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

The MCP layer is intentionally:
- read-only
- local/site-scoped by default
- built on the same business logic as the internal API
- aggregation-aware through cached remote-site payloads

---

## Standalone Purchasing App

The separate mobile-first buyer app lives in:

- [standalone-purchasing-agent-app](standalone-purchasing-agent-app)
- [standalone-receiving-intake-app](standalone-receiving-intake-app)

For local development:

1. Start the main Gold Drop app on `http://127.0.0.1:5050`
2. Start the standalone app dev server from `standalone-purchasing-agent-app`

The standalone dev server proxies `/api/*` to the Gold Drop backend by default so login and other session-based mobile endpoints work without browser CORS or cookie issues.

System Settings can now enable or disable the standalone buying and receiving workflows independently, and recent mobile workflow activity is visible in `Settings`.

Current mobile write-platform behavior:

- both standalone apps use the shared session-auth `/api/mobile/v1` surface
- standalone receiving works against existing approved or committed purchases rather than creating a second receiving object
- receiving can confirm receipt, upload delivery photos, and then edit the receipt until downstream lot usage exists
- once a lot is consumed by a run, receipt edits are locked and the API reports the lock reason
- buying and receiving UIs now use clearer "ready to record delivery" language for approved or committed opportunities
- unsafe browser writes enforce same-origin checks, and mobile-origin mutations are tagged in `audit_log`

Standalone app pilot docs:

- [standalone-purchasing-agent-app/DEPLOYMENT.md](standalone-purchasing-agent-app/DEPLOYMENT.md)
- [standalone-purchasing-agent-app/PILOT_QA_CHECKLIST.md](standalone-purchasing-agent-app/PILOT_QA_CHECKLIST.md)
- [standalone-purchasing-agent-app/PRODUCTION_ROLLOUT.md](standalone-purchasing-agent-app/PRODUCTION_ROLLOUT.md)
- [standalone-purchasing-agent-app/deploy/nginx-site.conf](standalone-purchasing-agent-app/deploy/nginx-site.conf)
- [standalone-receiving-intake-app/DEPLOYMENT.md](standalone-receiving-intake-app/DEPLOYMENT.md)
- [standalone-receiving-intake-app/PILOT_QA_CHECKLIST.md](standalone-receiving-intake-app/PILOT_QA_CHECKLIST.md)

## Importing Historical Data from Google Sheets

### Runs and run-style reports (legacy Import screen)

1. Open your Google Sheet
2. Go to each tab (Run Report, Kief Runs, LD Runs, Intakes)
3. File → Download → CSV
4. In the app, go to **Import** → Upload each CSV
5. Review the preview (header rows are auto-filtered)
6. Click **Confirm Import**

The system will:
- Strip repeated header rows
- Normalize date formats
- Auto-create suppliers from the Source column
- Skip duplicate records (matched on date + strain + source)

### Purchases (accounting / procurement spreadsheets)

Use **Purchases → Import spreadsheet** (not the **Import** menu used for runs). Supports **.csv**, **.xlsx**, and **.xlsm**; drag a file onto the drop zone or browse. After upload you get a **preview** of parsed rows; commit imports selected valid rows. A **sample CSV** is available from the import page. Requires **`openpyxl`** (see `requirements.txt`) for Excel files.

---

## Data Model

- **Suppliers** → **Purchases** → **Lots** (one-to-many chain)
- **Suppliers** → **Biomass Pipeline** (one-to-many)
- **Biomass Pipeline** → **Purchase** (one-to-one once committed/delivered/cancelled)
- **Field submissions** may include photo arrays stored as JSON paths to files in `static/uploads/field/`
- **Lab tests / supplier attachments** are stored as file references under `static/uploads/labs/`
- **Photo assets** are indexed in `photo_assets` for cross-screen search/filter and audit traceability
- **Cost Entries** are allocated across total dry grams in their date ranges
- **Lots** → **Run Inputs** → **Runs** (many-to-many through run_inputs; `RunInput` is the explicit lot allocation record)
- Purchase lots now carry `tracking_id`, barcode payload, QR payload, and label metadata for future scan / label workflows
- Lot `remaining_weight_lbs` is automatically decremented when used in a run, and run saves require selected lot allocations to match `bio_in_reactor_lbs`
- Slack run preview can rank candidate lots and prefill one-lot or split-lot allocations before the run form opens
- Yield calculations and cost-per-gram are auto-computed on save
- **Runs** may store **HTE pipeline stage** (awaiting lab → lab clean / queued for strip → stripped), **lab/COA file paths** (JSON, under `static/uploads/labs/`), and **terpenes / retail distillate grams** after stripping
