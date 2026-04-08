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

### Default Login Credentials

| Username | Password       | Role        |
|----------|----------------|-------------|
| admin    | golddrop2026   | Super Admin |
| ops      | golddrop2026   | User        |
| viewer   | golddrop2026   | Viewer      |

**Change these passwords immediately after first login via Settings.**

---

## Features

- **Dashboard** — KPI cards with configurable green/yellow/red traffic lights
- **Run Logging** — Log extraction runs with source lots, wet/dry HTE & THCA output; optional **HTE post-extraction pipeline** (lab staging, clean vs dirty, COA file attachments, terp-strip queue, terpenes + retail distillate grams after Prescott strip)
- **Departments** — Focused lenses (`/dept`, `/dept/<slug>`) on the same data: quick links, rollups, and filtered run lists (e.g. HTE pipeline stage) for finance, purchasing, intake, extraction, THCA/HTE/LD, terpenes, testing, bulk sales
- **Auto-Calculations** — Yield %, cost per gram, true-up amounts calculated automatically
- **Costs** — Enter solvent/personnel/overhead costs with date ranges; allocated into $/g
- **Cost Allocation Settings** — Choose THCA vs HTE allocation (uniform, 50/50, custom %)
- **Inventory** — Track biomass on hand, in transit, and days of supply
- **Purchases** — Record purchases with potency-based pricing and true-up tracking
- **Batch IDs** — Unique, readable batch IDs for all purchases (auto-generated if blank)
- **Biomass Pipeline** — Track farm availability from declared → testing → committed → delivered/cancelled (syncs to Purchases)
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
- **Slack Integration** — Outbound notifications; inbound slash commands, interactivity, and Events API URL (`/api/slack/events`); optional **channel history sync** for up to six channels with per-channel cursors (`conversations.history` → **Slack imports** triage UI); **Phase 2 manual Run apply** (prefilled new run from mappings, Run backlink + audit, **Slack Importer** user flag)
- **Supplier Performance** — All-time, 90-day, and last-batch analytics per farm
- **Strain Performance** — Compare yields and cost/gram across strains and suppliers
- **Data Quality Controls** — Flag runs missing $/lb; optionally exclude unpriced runs from analytics
- **CSV Import/Export** — Import from Google Sheets with deduplication; export any view
- **Role-Based Access** — Super Admin, User, and Viewer roles
- **Configurable KPIs** — Set targets and thresholds; change them as operations improve

---

## Project Structure

```
gold-drop/
├── app.py              # Flask application (routes, business logic)
├── models.py           # SQLAlchemy database models
├── requirements.txt    # Python dependencies
├── PRD.md              # Product requirements document
├── USER_MANUAL.md      # End-user / operator guide
├── FAQ.md              # Short frequently asked questions
├── ENGINEERING.md      # Implementation and schema notes for developers
├── static/
│   ├── css/
│   │   └── style.css       # Application styles
│   └── uploads/field/      # Field-submitted photos (created at runtime)
│   └── uploads/labs/       # Lab tests + supplier attachment files (created at runtime)
└── templates/
    ├── base.html           # Layout with sidebar navigation
    ├── login.html          # Login page
    ├── dashboard.html      # KPI dashboard
    ├── runs.html           # Run list view (optional HTE pipeline filter)
    ├── run_form.html       # New/edit run form (HTE lab & terp pipeline section)
    ├── dept_index.html     # Department hub tiles
    ├── dept_view.html      # Single department intro + stats + quick links
    ├── inventory.html      # Inventory position view
    ├── purchases.html      # Purchase list view
    ├── purchase_form.html  # New/edit purchase form
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
```

---

## Deploying to Production

After merging work into **`main`**, deploy by pulling on the server (`git fetch` / `git checkout main` / `git pull`) and **restarting the app process** (e.g. `systemctl restart …`) so Gunicorn reloads code. New database columns are applied on startup: SQLite via **`init_db()`** + **`_ensure_sqlite_schema()`**; PostgreSQL via **`init_db()`** + **`_ensure_postgres_run_hte_columns()`** (and `db.create_all()` for new tables).

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

---

## Importing Historical Data from Google Sheets

1. Open your Google Sheet
2. Go to each tab (Run Report, Kief Runs, LD Runs, Intakes)
3. File → Download → CSV
4. In the app, go to Import → Upload each CSV
5. Review the preview (header rows are auto-filtered)
6. Click "Confirm Import"

The system will:
- Strip repeated header rows
- Normalize date formats
- Auto-create suppliers from the Source column
- Skip duplicate records (matched on date + strain + source)

---

## Data Model

- **Suppliers** → **Purchases** → **Lots** (one-to-many chain)
- **Suppliers** → **Biomass Pipeline** (one-to-many)
- **Biomass Pipeline** → **Purchase** (one-to-one once committed/delivered/cancelled)
- **Field submissions** may include photo arrays stored as JSON paths to files in `static/uploads/field/`
- **Lab tests / supplier attachments** are stored as file references under `static/uploads/labs/`
- **Photo assets** are indexed in `photo_assets` for cross-screen search/filter and audit traceability
- **Cost Entries** are allocated across total dry grams in their date ranges
- **Lots** → **Run Inputs** → **Runs** (many-to-many through run_inputs)
- Lot `remaining_weight_lbs` is automatically decremented when used in a run
- Yield calculations and cost-per-gram are auto-computed on save
- **Runs** may store **HTE pipeline stage** (awaiting lab → lab clean / queued for strip → stripped), **lab/COA file paths** (JSON, under `static/uploads/labs/`), and **terpenes / retail distillate grams** after stripping
