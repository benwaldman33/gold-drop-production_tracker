# Gold Drop — Biomass Inventory & Extraction Tracking System

**Product requirements** live in `PRD.md`.
**User guide** lives in `USER_MANUAL.md` (no credentials included).

## Quick Start (Local Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Run the app
python app.py
```

Open http://localhost:5000 in your browser.

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
- **Run Logging** — Log extraction runs with source lots, wet/dry HTE & THCA output
- **Auto-Calculations** — Yield %, cost per gram, true-up amounts calculated automatically
- **Costs** — Enter solvent/personnel/overhead costs with date ranges; allocated into $/g
- **Cost Allocation Settings** — Choose THCA vs HTE allocation (uniform, 50/50, custom %)
- **Inventory** — Track biomass on hand, in transit, and days of supply
- **Purchases** — Record purchases with potency-based pricing and true-up tracking
- **Batch IDs** — Unique, readable batch IDs for all purchases (auto-generated if blank)
- **Biomass Pipeline** — Track farm availability from declared → testing → committed → delivered/cancelled (syncs to Purchases)
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
├── static/
│   └── css/
│       └── style.css   # Application styles
└── templates/
    ├── base.html           # Layout with sidebar navigation
    ├── login.html          # Login page
    ├── dashboard.html      # KPI dashboard
    ├── runs.html           # Run list view
    ├── run_form.html       # New/edit run form
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
    ├── import.html         # CSV import upload
    └── import_review.html  # Import preview and confirmation
```

---

## Deploying to Production

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
- **Cost Entries** are allocated across total dry grams in their date ranges
- **Lots** → **Run Inputs** → **Runs** (many-to-many through run_inputs)
- Lot `remaining_weight_lbs` is automatically decremented when used in a run
- Yield calculations and cost-per-gram are auto-computed on save
