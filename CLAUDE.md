# CLAUDE.md — Gold Drop Production Tracker

## Project Overview

Gold Drop is a **Biomass Inventory & Extraction Tracking System** built with Flask. It tracks biomass purchasing, inventory management, extraction runs, yield analytics, and operational costs for a cannabis extraction operation. The app is a monolithic single-file Flask application with a dark-themed UI.

## Tech Stack

- **Backend**: Flask 3.1.0, SQLAlchemy (Flask-SQLAlchemy 3.1.1), Flask-Login, Flask-WTF
- **Frontend**: Jinja2 templates, vanilla JavaScript, custom CSS (dark theme with gold accents)
- **Database**: SQLite (dev), PostgreSQL via `DATABASE_URL` (production)
- **Server**: Gunicorn 23.0.0 (production), Flask dev server (development)
- **Python**: 3.x (no pyproject.toml; dependencies in `requirements.txt`)

## Project Structure

```
gold-drop-production_tracker/
├── app.py              # All Flask routes and business logic (~1800 lines)
├── models.py           # SQLAlchemy models (~420 lines)
├── requirements.txt    # Python dependencies (7 packages)
├── README.md           # Quick start & deployment guide
├── USER_MANUAL.md      # End-user documentation
├── PRD.md              # Product requirements document
├── static/
│   └── css/
│       └── style.css   # Custom dark theme (~13 KB)
└── templates/          # 18 Jinja2 HTML templates
    ├── base.html       # Layout with sidebar navigation
    ├── dashboard.html  # KPI dashboard
    ├── runs.html / run_form.html
    ├── inventory.html
    ├── purchases.html / purchase_form.html
    ├── biomass.html / biomass_form.html
    ├── costs.html / cost_form.html
    ├── suppliers.html / supplier_form.html
    ├── strains.html
    ├── settings.html
    ├── login.html
    ├── import.html / import_review.html
```

All backend logic lives in two files: `app.py` (routes, helpers, init) and `models.py` (ORM models). There is no blueprint or module separation.

## Running the Application

```bash
# Install dependencies
pip install -r requirements.txt

# Development (debug mode, port 5000)
python app.py

# Production
gunicorn app:app --bind 0.0.0.0:8000
```

The database is auto-initialized on first startup via `init_db()` in `app.py`. It creates tables, seeds default users, KPI targets, system settings, and historical data.

### Default Login Credentials

| Username | Password       | Role        |
|----------|----------------|-------------|
| admin    | golddrop2026   | super_admin |
| ops      | golddrop2026   | user        |
| viewer   | golddrop2026   | viewer      |

## Environment Variables

| Variable       | Purpose                              | Default                                    |
|----------------|--------------------------------------|--------------------------------------------|
| `SECRET_KEY`   | Flask session signing key            | `gold-drop-dev-key-change-in-prod`         |
| `DATABASE_URL` | Database connection string           | `sqlite:///golddrop.db`                    |

No `.env` file is used. Set variables directly in the environment or deployment config.

## Testing & Linting

**No test suite or linting configuration exists.** There are no test files, pytest config, or linter configs. The `.gitignore` includes `.pytest_cache/`, `.mypy_cache/`, and `.ruff_cache/` entries suggesting these tools may be added in the future.

When adding tests:
- Use `pytest` as the test framework
- The app uses SQLite for development, so tests can use an in-memory SQLite database
- The `app` object is created at module level in `app.py` — use `app.test_client()` for integration tests

## Database Models (models.py)

11 models total, all using UUID v4 string primary keys (36 chars):

| Model               | Purpose                                              |
|----------------------|------------------------------------------------------|
| `User`               | Auth & authorization (roles: super_admin, user, viewer) |
| `Supplier`           | Source farms/vendors                                 |
| `BiomassAvailability`| Pipeline tracking: declared → testing → committed → delivered/cancelled |
| `Purchase`           | Batch-level receiving with auto-generated batch IDs  |
| `PurchaseLot`        | Inventory lots within a purchase (tracks remaining weight) |
| `Run`                | Extraction runs with yield and cost calculations     |
| `RunInput`           | Join table: lots consumed by a run                   |
| `CostEntry`          | Operational costs (solvent, personnel, overhead)     |
| `KpiTarget`          | Configurable KPI thresholds (green/yellow/red)       |
| `SystemSetting`      | Key-value configuration store                        |
| `AuditLog`           | Change tracking (create/update/delete actions)       |

### Key Relationships

- `Supplier` → `Purchase` (one-to-many)
- `Supplier` → `BiomassAvailability` (one-to-many)
- `Purchase` → `PurchaseLot` (one-to-many)
- `BiomassAvailability` → `Purchase` (optional one-to-one via `purchase_id`)
- `PurchaseLot` ↔ `Run` (many-to-many through `RunInput`)

### Important Model Methods

- `Run.calculate_yields()` — computes `grams_ran`, `overall_yield_pct`, `thca_yield_pct`, `hte_yield_pct`
- `Run.calculate_cost()` — computes biomass + operational cost per gram (respects `cost_allocation_method` setting)
- `Supplier.avg_yield(days=None)` — average yield from runs linked to supplier's lots

## Routes & Access Control

35 routes total. Access is controlled by three decorators:

| Decorator          | Who Can Access            |
|--------------------|---------------------------|
| `@login_required`  | Any authenticated user     |
| `@editor_required` | `super_admin` or `user`    |
| `@admin_required`  | `super_admin` only         |

### Route Groups

- `/` — Dashboard (KPIs, filterable by time period)
- `/runs/*` — Extraction run CRUD
- `/inventory` — Biomass on-hand and in-transit
- `/purchases/*` — Purchase CRUD with lot management
- `/biomass/*` — Biomass pipeline CRUD (syncs to purchases on stage transitions)
- `/costs/*` — Operational cost entry CRUD
- `/suppliers/*` — Supplier CRUD and performance analytics
- `/strains` — Strain performance analytics
- `/settings` — Admin config (KPIs, system settings, user management)
- `/import` — CSV import with preview/confirmation
- `/export/<entity>` — CSV export
- `/api/lots/available` — JSON endpoint for dynamic lot dropdowns

## Key Conventions

### ID Generation
- All primary keys are UUID v4 strings generated by `gen_uuid()` in `models.py`

### Batch ID Format
- Pattern: `PREFIX-DDMONYY-WEIGHT` (e.g., `FARML-15FEB26-200`)
- PREFIX = first 5 alphanumeric chars of supplier name (uppercased)
- Date = delivery or purchase date
- Weight = actual or stated weight in lbs
- Collisions resolved by appending `-2`, `-3`, etc.

### Audit Logging
- Every create/update/delete calls `log_audit(action, entity_type, entity_id, details)`
- Details are stored as JSON strings
- Always add audit logging when creating new CRUD operations

### Biomass Pipeline → Purchase Sync
- Stage transitions in `BiomassAvailability` automatically create or update linked `Purchase` records
- Key fields are kept synchronized: supplier, date, weight, potency, price, status
- Backward transitions (e.g., committed → testing) update the linked purchase accordingly

### Lot Weight Tracking
- `PurchaseLot.remaining_weight_lbs` decrements when lots are used as `RunInput`
- On run edit/delete, consumed weights are restored before recalculation

### Data Quality Controls
- The `exclude_unpriced_batches` system setting filters out runs without valid pricing from KPI analytics
- Runs are classified as: "unlinked", "unpriced", "partial", or "priced"

### Cost Allocation Methods
Three modes controlled by `cost_allocation_method` system setting:
- `per_gram_uniform` — THCA and HTE get the same $/g
- `split_50_50` — total cost split equally between products
- `custom_split` — configurable THCA/HTE percentage split via `cost_allocation_thca_pct`

## System Settings (seeded defaults)

| Key                        | Default              | Purpose                          |
|----------------------------|----------------------|----------------------------------|
| `potency_rate`             | `1.50`               | $/lb per potency %               |
| `num_reactors`             | `2`                  | Reactor count                    |
| `reactor_capacity`         | `100`                | lbs per reactor                  |
| `runs_per_day`             | `5`                  | Target runs/day                  |
| `operating_days`           | `7`                  | Days per week                    |
| `daily_throughput_target`  | `500`                | lbs/day target                   |
| `weekly_throughput_target` | `3500`               | lbs/week target                  |
| `exclude_unpriced_batches` | `0`                  | Boolean toggle                   |
| `cost_allocation_method`   | `per_gram_uniform`   | How cost splits between products |
| `cost_allocation_thca_pct` | `50`                 | THCA % for custom split          |

## CSS Theme

Dark theme with gold accents. Key colors:
- Primary Gold: `#C8963E`, Light: `#E5C882`, Dark: `#9A7230`
- Backgrounds: `#131520` (page), `#1B1D2E` (cards), `#252840` (hover)
- Status: Green `#34D399`, Yellow `#FBBF24`, Red `#F87171`
- Fixed 220px sidebar; responsive main content area

## Development Guidelines

1. **All backend logic goes in `app.py`** — no blueprint separation currently exists. Follow the existing patterns for adding new routes.
2. **All models go in `models.py`** — keep model methods (calculations, properties) on the model class.
3. **Templates extend `base.html`** — use the existing sidebar nav pattern and card-based layout.
4. **Always add audit logging** to new create/update/delete operations.
5. **Recalculate yields and costs** after modifying runs or cost entries by calling `run.calculate_yields()` and `run.calculate_cost()`.
6. **Restore lot weights** before modifying or deleting run inputs (see existing patterns in run edit/delete routes).
7. **Use `SystemSetting.get(key, default)`** for configuration values rather than hardcoding.
8. **Follow the UUID primary key convention** — use `gen_uuid` as the default for all new model `id` columns.
9. **No Docker or CI/CD** is configured. The app deploys directly via Gunicorn.
10. **Database migrations are manual** — schema changes for SQLite use `_ensure_sqlite_schema()` in `app.py`. For new columns, add `ALTER TABLE` logic there.
