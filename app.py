"""Gold Drop Biomass Inventory & Extraction Tracking System."""
import os
import csv
import io
import json
import hashlib
import secrets
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for, flash,
                   jsonify, Response, session)
from flask_login import (LoginManager, login_user, logout_user, login_required,
                         current_user)
from sqlalchemy import func, desc, and_, text, select, exists
from werkzeug.security import generate_password_hash

from models import (db, User, Supplier, Purchase, PurchaseLot, Run, RunInput,
                    KpiTarget, SystemSetting, AuditLog, BiomassAvailability, CostEntry,
                    FieldAccessToken, FieldPurchaseSubmission)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "gold-drop-dev-key-change-in-prod")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///golddrop.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, user_id)
    # If a user is deactivated, treat them as logged out
    if u and not getattr(u, "is_active_user", True):
        return None
    return u


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_super_admin:
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def editor_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_edit:
            flash("Edit access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)
    return decorated


def log_audit(action, entity_type, entity_id, details=None, user_id=None):
    entry = AuditLog(
        user_id=(user_id if user_id is not None else (current_user.id if current_user.is_authenticated else None)),
        action=action, entity_type=entity_type,
        entity_id=str(entity_id), details=details
    )
    db.session.add(entry)


def _hash_field_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _get_field_token_value() -> str | None:
    """Read token from querystring or form."""
    return (request.args.get("t") or request.form.get("t") or "").strip() or None


def _require_field_token():
    token = _get_field_token_value()
    if not token:
        return None, "Missing access token."
    token_hash = _hash_field_token(token)
    tok = FieldAccessToken.query.filter_by(token_hash=token_hash).first()
    if not tok:
        return None, "Invalid access token."
    if not tok.is_active:
        return None, "Access token is expired or revoked."
    # Touch last_used_at (best-effort)
    try:
        tok.last_used_at = datetime.utcnow()
        db.session.commit()
    except Exception:
        db.session.rollback()
    return tok, None


def field_token_required(view_fn):
    @wraps(view_fn)
    def wrapper(*args, **kwargs):
        tok, err = _require_field_token()
        if err:
            return render_template("field_error.html", message=err), 403
        return view_fn(tok, *args, **kwargs)
    return wrapper


def _exclude_unpriced_batches_enabled() -> bool:
    val = (SystemSetting.get("exclude_unpriced_batches", "0") or "0").strip().lower()
    return val in ("1", "true", "yes", "on")


def _priced_run_filter():
    """
    Keep only runs where:
    - at least one input lot linked, and
    - no input lot has a missing purchase $/lb.
    """
    inputs_exist = exists(
        select(1).select_from(RunInput).where(RunInput.run_id == Run.id).correlate(Run)
    )
    missing_price_exists = exists(
        select(1).select_from(RunInput).join(
            PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(
            Purchase, PurchaseLot.purchase_id == Purchase.id
        ).where(
            RunInput.run_id == Run.id,
            Purchase.price_per_lb.is_(None),
        ).correlate(Run)
    )
    return and_(inputs_exist, ~missing_price_exists)


def _pricing_status_for_run_ids(run_ids):
    """dict[run_id] -> priced|partial|unpriced|unlinked."""
    if not run_ids:
        return {}
    total_rows = db.session.query(
        RunInput.run_id, func.count(RunInput.id)
    ).filter(
        RunInput.run_id.in_(run_ids)
    ).group_by(RunInput.run_id).all()
    total_by_run = {rid: cnt for rid, cnt in total_rows}

    priced_rows = db.session.query(
        RunInput.run_id, func.count(RunInput.id)
    ).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
    ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
    ).filter(
        RunInput.run_id.in_(run_ids),
        Purchase.price_per_lb.isnot(None),
    ).group_by(RunInput.run_id).all()
    priced_by_run = {rid: cnt for rid, cnt in priced_rows}

    status = {}
    for rid in run_ids:
        total = int(total_by_run.get(rid, 0) or 0)
        priced = int(priced_by_run.get(rid, 0) or 0)
        if total == 0:
            status[rid] = "unlinked"
        elif priced == total:
            status[rid] = "priced"
        elif priced == 0:
            status[rid] = "unpriced"
        else:
            status[rid] = "partial"
    return status


def _supplier_prefix(name: str, length: int = 5) -> str:
    cleaned = "".join(ch for ch in (name or "").upper() if ch.isalnum())
    return (cleaned[:length] or "BATCH")


def _generate_batch_id(supplier_name: str, batch_date: date | None, weight_lbs: float | None) -> str:
    """
    Generate a descriptive, readable batch identifier.
    Example: FARML-15FEB26-200
    """
    d = batch_date or date.today()
    w = int(round(weight_lbs or 0))
    return f"{_supplier_prefix(supplier_name)}-{d.strftime('%d%b%y').upper()}-{w}"[:80]


def _ensure_unique_batch_id(candidate: str, exclude_purchase_id: str | None = None) -> str:
    """Ensure uniqueness by suffixing -2, -3... when needed."""
    base = (candidate or "").strip().upper()
    if not base:
        base = "BATCH"
    bid = base
    n = 2
    max_attempts = 100
    for _ in range(max_attempts):
        q = Purchase.query.filter(Purchase.batch_id == bid)
        if exclude_purchase_id:
            q = q.filter(Purchase.id != exclude_purchase_id)
        if not q.first():
            return bid
        bid = f"{base}-{n}"
        n += 1
    raise ValueError(f"Could not generate a unique batch ID for base '{base}' after {max_attempts} attempts.")


def _ensure_sqlite_schema():
    """Lightweight schema updates for existing SQLite DBs (no migrations)."""
    if db.engine.dialect.name != "sqlite":
        return

    def has_table(table_name: str) -> bool:
        row = db.session.execute(
            text("SELECT name FROM sqlite_master WHERE type='table' AND name=:t"),
            {"t": table_name},
        ).first()
        return bool(row)

    def column_names(table_name: str) -> set[str]:
        rows = db.session.execute(text(f"PRAGMA table_info({table_name})")).all()
        return {r[1] for r in rows}

    # Purchases: batch_id
    if has_table("purchases"):
        cols = column_names("purchases")
        if "batch_id" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN batch_id VARCHAR(80)"))

    # Biomass availabilities: purchase_id (if table already exists)
    if has_table("biomass_availabilities"):
        cols = column_names("biomass_availabilities")
        if "purchase_id" not in cols:
            db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN purchase_id VARCHAR(36)"))

    # Runs: cost_per_gram_thca / cost_per_gram_hte
    if has_table("runs"):
        cols = column_names("runs")
        if "cost_per_gram_thca" not in cols:
            db.session.execute(text("ALTER TABLE runs ADD COLUMN cost_per_gram_thca FLOAT"))
        if "cost_per_gram_hte" not in cols:
            db.session.execute(text("ALTER TABLE runs ADD COLUMN cost_per_gram_hte FLOAT"))

    db.session.commit()


# ── Auth Routes ──────────────────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(username=request.form.get("username", "").strip().lower()).first()
        if user and user.check_password(request.form.get("password", "")):
            if not user.is_active_user:
                flash("This account is disabled. Please contact an administrator.", "error")
                return render_template("login.html")
            login_user(user, remember=True)
            session.permanent = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        flash("Invalid username or password.", "error")
    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))


# ── Field (mobile) intake ────────────────────────────────────────────────────

@app.route("/field")
@field_token_required
def field_home(token):
    """Landing page for field/mobile data entry (no login, token required)."""
    return render_template("field_home.html", token_value=_get_field_token_value(), token=token)


@app.route("/field/biomass/new", methods=["GET", "POST"])
@field_token_required
def field_biomass_new(token):
    """
    Create a BiomassAvailability record from the field without requiring login.
    This is intended for early-stage pipeline entry (declared/testing).
    """
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    if request.method == "POST":
        try:
            supplier_id = (request.form.get("supplier_id") or "").strip()
            if not supplier_id:
                raise ValueError("Supplier is required.")
            sup = db.session.get(Supplier, supplier_id)
            if not sup:
                raise ValueError("Selected supplier was not found.")

            ad = (request.form.get("availability_date") or "").strip()
            if not ad:
                raise ValueError("Availability Date is required.")
            availability_date = datetime.strptime(ad, "%Y-%m-%d").date()

            stage = (request.form.get("stage") or "declared").strip()
            if stage not in ("declared", "testing"):
                raise ValueError("Stage must be Declared or Testing for field intake.")

            dw = (request.form.get("declared_weight_lbs") or "").strip()
            declared_weight = float(dw) if dw else 0.0
            if declared_weight < 0:
                raise ValueError("Declared Weight cannot be negative.")

            dpl = (request.form.get("declared_price_per_lb") or "").strip()
            declared_price = float(dpl) if dpl else None
            if declared_price is not None and declared_price < 0:
                raise ValueError("Declared $/lb cannot be negative.")

            ep = (request.form.get("estimated_potency_pct") or "").strip()
            estimated_potency = float(ep) if ep else None
            if estimated_potency is not None and not (0 <= estimated_potency <= 100):
                raise ValueError("Estimated Potency must be between 0 and 100.")

            b = BiomassAvailability(
                supplier_id=supplier_id,
                availability_date=availability_date,
                strain_name=(request.form.get("strain_name") or "").strip() or None,
                declared_weight_lbs=declared_weight,
                declared_price_per_lb=declared_price,
                estimated_potency_pct=estimated_potency,
                testing_timing=(request.form.get("testing_timing") or "before_delivery").strip() or "before_delivery",
                testing_status=(request.form.get("testing_status") or "pending").strip() or "pending",
                stage=stage,
                notes=((request.form.get("notes") or "").strip() or None),
            )
            db.session.add(b)
            db.session.flush()
            log_audit(
                "create",
                "biomass_availability",
                b.id,
                details=json.dumps({
                    "source": "field_intake",
                    "token_label": token.label,
                    "supplier": sup.name,
                }),
                user_id=None,
            )
            db.session.commit()
            return redirect(url_for("field_thanks", kind="biomass", t=_get_field_token_value()))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
        except Exception:
            db.session.rollback()
            app.logger.exception("Field biomass intake failed")
            flash("Could not submit. Please check your inputs and try again.", "error")

    return render_template(
        "field_biomass_form.html",
        token_value=_get_field_token_value(),
        suppliers=suppliers,
        today=date.today(),
    )


@app.route("/field/purchase/new", methods=["GET", "POST"])
@field_token_required
def field_purchase_new(token):
    """Submit a potential purchase from the field (requires admin approval)."""
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    if request.method == "POST":
        try:
            supplier_id = (request.form.get("supplier_id") or "").strip()
            if not supplier_id:
                raise ValueError("Supplier is required.")
            sup = db.session.get(Supplier, supplier_id)
            if not sup:
                raise ValueError("Selected supplier was not found.")

            pd = (request.form.get("purchase_date") or "").strip()
            if not pd:
                raise ValueError("Purchase Date is required.")
            purchase_date = datetime.strptime(pd, "%Y-%m-%d").date()

            dd = (request.form.get("delivery_date") or "").strip()
            delivery_date = datetime.strptime(dd, "%Y-%m-%d").date() if dd else None

            ep = (request.form.get("estimated_potency_pct") or "").strip()
            estimated_potency = float(ep) if ep else None
            if estimated_potency is not None and not (0 <= estimated_potency <= 100):
                raise ValueError("Estimated Potency must be between 0 and 100.")

            ppl = (request.form.get("price_per_lb") or "").strip()
            price_per_lb = float(ppl) if ppl else None
            if price_per_lb is not None and price_per_lb < 0:
                raise ValueError("Price/lb cannot be negative.")

            # Lots (at least one)
            lot_strains = request.form.getlist("lot_strains[]")
            lot_weights = request.form.getlist("lot_weights[]")
            lots = []
            for strain, w in zip(lot_strains, lot_weights):
                strain = (strain or "").strip()
                w = (w or "").strip()
                if not strain and not w:
                    continue
                if not strain:
                    raise ValueError("Lot strain name is required.")
                try:
                    weight = float(w)
                except ValueError:
                    raise ValueError("Lot weight must be a number.")
                if weight <= 0:
                    raise ValueError("Lot weight must be greater than 0.")
                lots.append({"strain": strain, "weight_lbs": weight})
            if not lots:
                raise ValueError("Add at least one lot/strain with weight.")

            sub = FieldPurchaseSubmission(
                source_token_id=token.id,
                supplier_id=supplier_id,
                purchase_date=purchase_date,
                delivery_date=delivery_date,
                estimated_potency_pct=estimated_potency,
                price_per_lb=price_per_lb,
                notes=((request.form.get("notes") or "").strip() or None),
                lots_json=json.dumps(lots),
                status="pending",
            )
            db.session.add(sub)
            db.session.flush()
            log_audit(
                "create",
                "field_purchase_submission",
                sub.id,
                details=json.dumps({
                    "source": "field_intake",
                    "token_label": token.label,
                    "supplier": sup.name,
                    "lots_count": len(lots),
                }),
                user_id=None,
            )
            db.session.commit()
            return redirect(url_for("field_thanks", kind="purchase", t=_get_field_token_value()))
        except ValueError as e:
            db.session.rollback()
            flash(str(e), "error")
        except Exception:
            db.session.rollback()
            app.logger.exception("Field purchase intake failed")
            flash("Could not submit. Please check your inputs and try again.", "error")

    return render_template(
        "field_purchase_form.html",
        token_value=_get_field_token_value(),
        suppliers=suppliers,
        today=date.today(),
    )


@app.route("/field/thanks")
@field_token_required
def field_thanks(token):
    kind = (request.args.get("kind") or "").strip()
    return render_template("field_thanks.html", kind=kind, token_value=_get_field_token_value())


# ── Dashboard ────────────────────────────────────────────────────────────────

@app.route("/")
@login_required
def dashboard():
    # Time period
    period = request.args.get("period", "30")
    if period == "today":
        start_date = date.today()
    elif period == "7":
        start_date = date.today() - timedelta(days=7)
    elif period == "90":
        start_date = date.today() - timedelta(days=90)
    elif period == "all":
        start_date = date(2020, 1, 1)
    else:
        start_date = date.today() - timedelta(days=30)

    exclude_unpriced = _exclude_unpriced_batches_enabled()

    # Query runs in period
    runs_q = Run.query.filter(Run.run_date >= start_date)
    if exclude_unpriced:
        runs_q = runs_q.filter(_priced_run_filter())
    runs = runs_q.all()

    # Calculate KPI actuals
    kpi_actuals = {}
    if runs:
        yields = [r.overall_yield_pct for r in runs if r.overall_yield_pct]
        thca_yields = [r.thca_yield_pct for r in runs if r.thca_yield_pct]
        hte_yields = [r.hte_yield_pct for r in runs if r.hte_yield_pct]
        costs = [r.cost_per_gram_combined for r in runs if r.cost_per_gram_combined]
        costs_thca = [r.cost_per_gram_thca for r in runs if r.cost_per_gram_thca is not None]
        costs_hte = [r.cost_per_gram_hte for r in runs if r.cost_per_gram_hte is not None]
        total_lbs = sum(r.bio_in_reactor_lbs or 0 for r in runs)
        total_dry_thca = sum(r.dry_thca_g or 0 for r in runs)
        total_dry_hte = sum(r.dry_hte_g or 0 for r in runs)

        kpi_actuals["thca_yield_pct"] = sum(thca_yields) / len(thca_yields) if thca_yields else None
        kpi_actuals["hte_yield_pct"] = sum(hte_yields) / len(hte_yields) if hte_yields else None
        kpi_actuals["overall_yield_pct"] = sum(yields) / len(yields) if yields else None
        kpi_actuals["cost_per_gram_combined"] = sum(costs) / len(costs) if costs else None
        kpi_actuals["cost_per_gram_thca"] = sum(costs_thca) / len(costs_thca) if costs_thca else None
        kpi_actuals["cost_per_gram_hte"] = sum(costs_hte) / len(costs_hte) if costs_hte else None

        # Weekly throughput (average lbs/week in period)
        days_in_period = max((date.today() - start_date).days, 1)
        weeks = max(days_in_period / 7, 1)
        kpi_actuals["weekly_throughput"] = total_lbs / weeks

        # Days of supply
        daily_target = SystemSetting.get_float("daily_throughput_target", 500)
        on_hand_statuses = ("delivered", "in_testing", "available", "processing", "complete")
        on_hand = db.session.query(func.sum(PurchaseLot.remaining_weight_lbs)).join(Purchase).filter(
            PurchaseLot.remaining_weight_lbs > 0,
            Purchase.status.in_(on_hand_statuses)
        ).scalar() or 0
        kpi_actuals["days_of_supply"] = on_hand / daily_target if daily_target > 0 else 0

        # Cost per potency point - average across purchases in period
        # Tie potency-point KPI to the biomass actually *run* in the selected time period,
        # not only purchases created in that period (purchases may be older than the run window).
        purchase_ids = db.session.query(Purchase.id).join(
            PurchaseLot, PurchaseLot.purchase_id == Purchase.id
        ).join(
            RunInput, RunInput.lot_id == PurchaseLot.id
        ).join(
            Run, Run.id == RunInput.run_id
        ).filter(
            Run.run_date >= start_date
        ).distinct().all()
        purchase_ids = [pid for (pid,) in purchase_ids]
        purchases_in_period = Purchase.query.filter(Purchase.id.in_(purchase_ids)).all() if purchase_ids else []
        potency_costs = []
        for p in purchases_in_period:
            potency = p.tested_potency_pct or p.stated_potency_pct
            if p.price_per_lb and potency and potency > 0:
                potency_costs.append(p.price_per_lb / potency)
        kpi_actuals["cost_per_potency_point"] = sum(potency_costs) / len(potency_costs) if potency_costs else None

    # Get KPI targets
    kpis = KpiTarget.query.all()
    kpi_cards = []
    for kpi in kpis:
        actual = kpi_actuals.get(kpi.kpi_name)
        color = kpi.evaluate(actual)
        kpi_cards.append({
            "name": kpi.display_name,
            "target": kpi.target_value,
            "actual": actual,
            "color": color,
            "unit": kpi.unit or "",
            "direction": kpi.direction,
        })

    # Summary stats
    total_runs = len(runs)
    total_lbs = sum(r.bio_in_reactor_lbs or 0 for r in runs)
    total_dry_output = sum((r.dry_hte_g or 0) + (r.dry_thca_g or 0) for r in runs)
    on_hand = db.session.query(func.sum(PurchaseLot.remaining_weight_lbs)).join(Purchase).filter(
        PurchaseLot.remaining_weight_lbs > 0,
        Purchase.status.in_(("delivered", "in_testing", "available", "processing", "complete"))
    ).scalar() or 0

    return render_template("dashboard.html",
                           kpi_cards=kpi_cards, period=period,
                           total_runs=total_runs, total_lbs=total_lbs,
                           total_dry_output=total_dry_output, on_hand=on_hand,
                           exclude_unpriced=exclude_unpriced)


# ── Runs ─────────────────────────────────────────────────────────────────────

@app.route("/runs")
@login_required
def runs_list():
    page = request.args.get("page", 1, type=int)
    sort = request.args.get("sort", "run_date")
    order = request.args.get("order", "desc")
    search = request.args.get("search", "").strip()

    query = Run.query
    if search:
        query = query.join(RunInput, isouter=True).join(PurchaseLot, isouter=True).filter(
            db.or_(PurchaseLot.strain_name.ilike(f"%{search}%"),
                   Run.notes.ilike(f"%{search}%"))
        ).distinct()

    sort_col = getattr(Run, sort, Run.run_date)
    if order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    run_ids = [r.id for r in pagination.items]
    pricing_status = _pricing_status_for_run_ids(run_ids)
    return render_template("runs.html", runs=pagination.items, pagination=pagination,
                           sort=sort, order=order, search=search,
                           pricing_status=pricing_status)


@app.route("/runs/new", methods=["GET", "POST"])
@editor_required
def run_new():
    if request.method == "POST":
        return _save_run(None)

    lots = PurchaseLot.query.filter(PurchaseLot.remaining_weight_lbs > 0).all()
    return render_template("run_form.html", run=None, lots=lots, today=date.today())


@app.route("/runs/<run_id>/edit", methods=["GET", "POST"])
@editor_required
def run_edit(run_id):
    run = db.session.get(Run, run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("runs_list"))

    if request.method == "POST":
        return _save_run(run)

    lots = PurchaseLot.query.filter(
        db.or_(PurchaseLot.remaining_weight_lbs > 0,
               PurchaseLot.id.in_([i.lot_id for i in run.inputs]))
    ).all()
    return render_template("run_form.html", run=run, lots=lots, today=date.today())


def _save_run(existing_run):
    try:
        if existing_run:
            run = existing_run
            # Restore lot weights from previous inputs before recalculating
            for inp in run.inputs:
                lot = db.session.get(PurchaseLot, inp.lot_id)
                if lot:
                    lot.remaining_weight_lbs += inp.weight_lbs
            RunInput.query.filter_by(run_id=run.id).delete()
        else:
            run = Run()

        run.run_date = datetime.strptime(request.form["run_date"], "%Y-%m-%d").date()
        run.reactor_number = int(request.form["reactor_number"])
        run.is_rollover = "is_rollover" in request.form
        run.bio_in_reactor_lbs = float(request.form.get("bio_in_reactor_lbs") or 0)
        run.bio_in_house_lbs = float(request.form.get("bio_in_house_lbs") or 0) or None
        run.butane_in_house_lbs = float(request.form.get("butane_in_house_lbs") or 0) or None
        run.solvent_ratio = float(request.form.get("solvent_ratio") or 0) or None
        run.system_temp = float(request.form.get("system_temp") or 0) or None
        run.wet_hte_g = float(request.form.get("wet_hte_g") or 0) or None
        run.wet_thca_g = float(request.form.get("wet_thca_g") or 0) or None
        run.dry_hte_g = float(request.form.get("dry_hte_g") or 0) or None
        run.dry_thca_g = float(request.form.get("dry_thca_g") or 0) or None
        run.decarb_sample_done = "decarb_sample_done" in request.form
        run.fuel_consumption = float(request.form.get("fuel_consumption") or 0) or None
        run.notes = request.form.get("notes", "").strip() or None
        run.run_type = request.form.get("run_type", "standard")

        if not existing_run:
            run.created_by = current_user.id

        run.calculate_yields()

        if not existing_run:
            db.session.add(run)
        db.session.flush()

        # Process lot inputs
        lot_ids = request.form.getlist("lot_ids[]")
        lot_weights = request.form.getlist("lot_weights[]")
        for lid, lw in zip(lot_ids, lot_weights):
            if lid and lw:
                weight = float(lw)
                if weight > 0:
                    inp = RunInput(run_id=run.id, lot_id=lid, weight_lbs=weight)
                    db.session.add(inp)
                    lot = db.session.get(PurchaseLot, lid)
                    if lot:
                        lot.remaining_weight_lbs = max(0, lot.remaining_weight_lbs - weight)

        run.calculate_cost()
        log_audit("update" if existing_run else "create", "run", run.id)
        db.session.commit()
        flash("Run saved successfully.", "success")
        return redirect(url_for("runs_list"))

    except Exception as e:
        db.session.rollback()
        flash(f"Error saving run: {str(e)}", "error")
        lots = PurchaseLot.query.filter(PurchaseLot.remaining_weight_lbs > 0).all()
        return render_template("run_form.html", run=existing_run, lots=lots, today=date.today())


@app.route("/runs/<run_id>/delete", methods=["POST"])
@editor_required
def run_delete(run_id):
    run = db.session.get(Run, run_id)
    if run:
        # Restore lot weights
        for inp in run.inputs:
            lot = db.session.get(PurchaseLot, inp.lot_id)
            if lot:
                lot.remaining_weight_lbs += inp.weight_lbs
        log_audit("delete", "run", run.id)
        db.session.delete(run)
        db.session.commit()
        flash("Run deleted.", "success")
    return redirect(url_for("runs_list"))


# ── Cost Entries ─────────────────────────────────────────────────────────────

@app.route("/costs")
@login_required
def costs_list():
    """View operational cost entries."""
    cost_type = request.args.get("type", "")
    query = CostEntry.query
    if cost_type:
        query = query.filter_by(cost_type=cost_type)
    entries = query.order_by(CostEntry.start_date.desc()).all()

    solvent_total = sum(e.total_cost for e in CostEntry.query.filter_by(cost_type="solvent").all())
    personnel_total = sum(e.total_cost for e in CostEntry.query.filter_by(cost_type="personnel").all())
    overhead_total = sum(e.total_cost for e in CostEntry.query.filter_by(cost_type="overhead").all())

    return render_template("costs.html", entries=entries, cost_type=cost_type,
                           solvent_total=solvent_total, personnel_total=personnel_total,
                           overhead_total=overhead_total)


@app.route("/costs/new", methods=["GET", "POST"])
@editor_required
def cost_new():
    if request.method == "POST":
        try:
            entry = CostEntry(
                cost_type=request.form["cost_type"],
                name=request.form["name"].strip(),
                unit_cost=float(request.form.get("unit_cost") or 0) or None,
                unit=request.form.get("unit", "").strip() or None,
                quantity=float(request.form.get("quantity") or 0) or None,
                total_cost=float(request.form["total_cost"]),
                start_date=datetime.strptime(request.form["start_date"], "%Y-%m-%d").date(),
                end_date=datetime.strptime(request.form["end_date"], "%Y-%m-%d").date(),
                notes=request.form.get("notes", "").strip() or None,
                created_by=current_user.id,
            )
            db.session.add(entry)
            log_audit("create", "cost_entry", entry.id)
            db.session.commit()
            flash("Cost entry added.", "success")
            return redirect(url_for("costs_list"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "error")
    return render_template("cost_form.html", entry=None, today=date.today())


@app.route("/costs/<entry_id>/edit", methods=["GET", "POST"])
@editor_required
def cost_edit(entry_id):
    entry = db.session.get(CostEntry, entry_id)
    if not entry:
        flash("Cost entry not found.", "error")
        return redirect(url_for("costs_list"))
    if request.method == "POST":
        try:
            entry.cost_type = request.form["cost_type"]
            entry.name = request.form["name"].strip()
            entry.unit_cost = float(request.form.get("unit_cost") or 0) or None
            entry.unit = request.form.get("unit", "").strip() or None
            entry.quantity = float(request.form.get("quantity") or 0) or None
            entry.total_cost = float(request.form["total_cost"])
            entry.start_date = datetime.strptime(request.form["start_date"], "%Y-%m-%d").date()
            entry.end_date = datetime.strptime(request.form["end_date"], "%Y-%m-%d").date()
            entry.notes = request.form.get("notes", "").strip() or None
            log_audit("update", "cost_entry", entry.id)
            db.session.commit()
            flash("Cost entry updated.", "success")
            return redirect(url_for("costs_list"))
        except Exception as e:
            db.session.rollback()
            flash(f"Error: {str(e)}", "error")
    return render_template("cost_form.html", entry=entry, today=date.today())


@app.route("/costs/<entry_id>/delete", methods=["POST"])
@editor_required
def cost_delete(entry_id):
    entry = db.session.get(CostEntry, entry_id)
    if entry:
        log_audit("delete", "cost_entry", entry.id)
        db.session.delete(entry)
        db.session.commit()
        flash("Cost entry deleted.", "success")
    return redirect(url_for("costs_list"))


# ── Inventory ────────────────────────────────────────────────────────────────

@app.route("/inventory")
@login_required
def inventory():
    # On-hand lots: only from purchases that have actually arrived
    on_hand_statuses = ("delivered", "in_testing", "available", "processing", "complete")
    on_hand = PurchaseLot.query.join(Purchase).filter(
        PurchaseLot.remaining_weight_lbs > 0,
        Purchase.status.in_(on_hand_statuses)
    ).all()

    # In-transit purchases
    in_transit = Purchase.query.filter(Purchase.status.in_(["committed", "ordered", "in_transit"])).all()

    # Summary
    total_on_hand = sum(l.remaining_weight_lbs for l in on_hand)
    total_in_transit = sum(p.stated_weight_lbs for p in in_transit)
    daily_target = SystemSetting.get_float("daily_throughput_target", 500)
    days_supply = total_on_hand / daily_target if daily_target > 0 else 0

    return render_template("inventory.html", on_hand=on_hand, in_transit=in_transit,
                           total_on_hand=total_on_hand, total_in_transit=total_in_transit,
                           days_supply=days_supply)


# ── Purchases ────────────────────────────────────────────────────────────────

@app.route("/purchases")
@login_required
def purchases_list():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    query = Purchase.query
    if status_filter:
        query = query.filter_by(status=status_filter)
    pagination = query.order_by(Purchase.purchase_date.desc()).paginate(page=page, per_page=25)
    return render_template("purchases.html", purchases=pagination.items, pagination=pagination,
                           status_filter=status_filter)


@app.route("/purchases/new", methods=["GET", "POST"])
@editor_required
def purchase_new():
    if request.method == "POST":
        return _save_purchase(None)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    rate = SystemSetting.get_float("potency_rate", 1.50)
    return render_template("purchase_form.html", purchase=None, suppliers=suppliers,
                           rate=rate, today=date.today())


@app.route("/purchases/<purchase_id>/edit", methods=["GET", "POST"])
@editor_required
def purchase_edit(purchase_id):
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        flash("Purchase not found.", "error")
        return redirect(url_for("purchases_list"))
    if request.method == "POST":
        return _save_purchase(purchase)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    rate = SystemSetting.get_float("potency_rate", 1.50)
    return render_template("purchase_form.html", purchase=purchase, suppliers=suppliers,
                           rate=rate, today=date.today())


def _save_purchase(existing):
    try:
        p = existing or Purchase()
        p.supplier_id = request.form["supplier_id"]
        p.purchase_date = datetime.strptime(request.form["purchase_date"], "%Y-%m-%d").date()
        dd = request.form.get("delivery_date", "").strip()
        p.delivery_date = datetime.strptime(dd, "%Y-%m-%d").date() if dd else None
        p.status = request.form.get("status", "ordered")
        p.stated_weight_lbs = float(request.form.get("stated_weight_lbs") or 0)
        aw = request.form.get("actual_weight_lbs", "").strip()
        p.actual_weight_lbs = float(aw) if aw else None
        sp = request.form.get("stated_potency_pct", "").strip()
        p.stated_potency_pct = float(sp) if sp else None
        tp = request.form.get("tested_potency_pct", "").strip()
        p.tested_potency_pct = float(tp) if tp else None
        ppl = request.form.get("price_per_lb", "").strip()
        p.price_per_lb = float(ppl) if ppl else None
        p.clean_or_dirty = request.form.get("clean_or_dirty") or None
        p.indoor_outdoor = request.form.get("indoor_outdoor") or None
        hd = request.form.get("harvest_date", "").strip()
        p.harvest_date = datetime.strptime(hd, "%Y-%m-%d").date() if hd else None
        p.notes = request.form.get("notes", "").strip() or None

        # Auto-calculate price if potency provided and price empty
        if p.stated_potency_pct and not p.price_per_lb:
            rate = SystemSetting.get_float("potency_rate", 1.50)
            p.price_per_lb = rate * p.stated_potency_pct

        # Calculate total cost
        weight = p.actual_weight_lbs or p.stated_weight_lbs
        if weight and p.price_per_lb:
            p.total_cost = weight * p.price_per_lb

        # True-up
        if p.tested_potency_pct and p.stated_potency_pct and p.actual_weight_lbs:
            rate = SystemSetting.get_float("potency_rate", 1.50)
            p.true_up_amount = (p.tested_potency_pct - p.stated_potency_pct) * rate * p.actual_weight_lbs
            if not p.true_up_status:
                p.true_up_status = "pending"

        if not existing:
            db.session.add(p)
        db.session.flush()

        # Batch identifier (unique per purchase batch)
        batch_in = (request.form.get("batch_id") or "").strip()
        if batch_in:
            candidate = batch_in.upper()
            conflict = Purchase.query.filter(Purchase.batch_id == candidate, Purchase.id != p.id).first()
            if conflict:
                raise ValueError(f"Batch ID '{candidate}' already exists. Please choose a unique Batch ID.")
            p.batch_id = candidate
        else:
            sup = db.session.get(Supplier, p.supplier_id)
            supplier_name = sup.name if sup else "BATCH"
            d = p.delivery_date or p.purchase_date
            w = p.actual_weight_lbs or p.stated_weight_lbs
            p.batch_id = _ensure_unique_batch_id(_generate_batch_id(supplier_name, d, w), exclude_purchase_id=p.id)

        # If this purchase is linked to a biomass pipeline record, keep stage in sync
        linked = BiomassAvailability.query.filter(BiomassAvailability.purchase_id == p.id).first()
        if linked:
            status = (p.status or "").strip()
            if status in ("ordered", "in_transit", "committed"):
                linked.stage = "committed"
            elif status in ("in_testing", "available"):
                linked.stage = "testing"
            elif status in ("delivered", "processing", "complete"):
                linked.stage = "delivered"
            elif status == "cancelled":
                linked.stage = "cancelled"
            else:
                # Keep sync for early/manual statuses when present
                linked.stage = status if status in ("declared", "testing") else "delivered"
            linked.committed_on = p.purchase_date
            linked.committed_delivery_date = p.delivery_date
            linked.committed_weight_lbs = p.actual_weight_lbs or p.stated_weight_lbs
            linked.committed_price_per_lb = p.price_per_lb

        # Process lots
        if not existing:
            lot_strains = request.form.getlist("lot_strains[]")
            lot_weights = request.form.getlist("lot_weights[]")
            for strain, weight in zip(lot_strains, lot_weights):
                if strain and weight:
                    lot = PurchaseLot(
                        purchase_id=p.id, strain_name=strain.strip(),
                        weight_lbs=float(weight), remaining_weight_lbs=float(weight)
                    )
                    db.session.add(lot)

        log_audit("update" if existing else "create", "purchase", p.id)
        db.session.commit()
        flash("Purchase saved.", "success")
        return redirect(url_for("purchases_list"))
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        rate = SystemSetting.get_float("potency_rate", 1.50)
        return render_template("purchase_form.html", purchase=existing, suppliers=suppliers,
                               rate=rate, today=date.today())
    except Exception:
        db.session.rollback()
        app.logger.exception("Error saving purchase")
        flash("Error saving purchase. Please check your inputs and try again.", "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        rate = SystemSetting.get_float("potency_rate", 1.50)
        return render_template("purchase_form.html", purchase=existing, suppliers=suppliers,
                               rate=rate, today=date.today())


# ── Suppliers ────────────────────────────────────────────────────────────────

@app.route("/suppliers")
@login_required
def suppliers_list():
    suppliers = Supplier.query.order_by(Supplier.name).all()
    exclude_unpriced = _exclude_unpriced_batches_enabled()

    # Enrich with performance stats
    supplier_stats = []
    for s in suppliers:
        # All-time stats
        runs_q = db.session.query(
            func.avg(Run.overall_yield_pct),
            func.avg(Run.thca_yield_pct),
            func.avg(Run.hte_yield_pct),
            func.avg(Run.cost_per_gram_combined),
            func.count(Run.id),
            func.sum(Run.bio_in_reactor_lbs),
            func.sum(Run.dry_thca_g),
            func.sum(Run.dry_hte_g),
        ).join(RunInput, Run.id == RunInput.run_id
        ).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
        ).filter(Purchase.supplier_id == s.id, Run.is_rollover == False)
        if exclude_unpriced:
            runs_q = runs_q.filter(_priced_run_filter())

        all_time = runs_q.first()

        # 90-day stats
        cutoff_90 = date.today() - timedelta(days=90)
        ninety = runs_q.filter(Run.run_date >= cutoff_90).first()

        # Last batch
        last_run = db.session.query(Run).join(
            RunInput, Run.id == RunInput.run_id
        ).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
        ).filter(Purchase.supplier_id == s.id, Run.is_rollover == False
        )
        if exclude_unpriced:
            last_run = last_run.filter(_priced_run_filter())
        last_run = last_run.order_by(Run.run_date.desc()).first()

        supplier_stats.append({
            "supplier": s,
            "all_time": {
                "yield": all_time[0], "thca": all_time[1], "hte": all_time[2],
                "cpg": all_time[3], "runs": all_time[4], "lbs": all_time[5] or 0,
                "total_thca": all_time[6] or 0, "total_hte": all_time[7] or 0,
            },
            "ninety_day": {
                "yield": ninety[0], "thca": ninety[1], "hte": ninety[2],
                "cpg": ninety[3], "runs": ninety[4],
            },
            "last_batch": {
                "yield": last_run.overall_yield_pct if last_run else None,
                "thca": last_run.thca_yield_pct if last_run else None,
                "hte": last_run.hte_yield_pct if last_run else None,
                "cpg": last_run.cost_per_gram_combined if last_run else None,
                "date": last_run.run_date if last_run else None,
            },
        })

    # Get KPI targets for color coding
    yield_kpi = KpiTarget.query.filter_by(kpi_name="overall_yield_pct").first()
    thca_kpi = KpiTarget.query.filter_by(kpi_name="thca_yield_pct").first()

    return render_template("suppliers.html", supplier_stats=supplier_stats,
                           yield_kpi=yield_kpi, thca_kpi=thca_kpi)


@app.route("/suppliers/new", methods=["GET", "POST"])
@editor_required
def supplier_new():
    if request.method == "POST":
        s = Supplier(
            name=request.form["name"].strip(),
            contact_name=request.form.get("contact_name", "").strip() or None,
            contact_phone=request.form.get("contact_phone", "").strip() or None,
            contact_email=request.form.get("contact_email", "").strip() or None,
            location=request.form.get("location", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(s)
        log_audit("create", "supplier", s.id)
        db.session.commit()
        flash("Supplier added.", "success")
        return redirect(url_for("suppliers_list"))
    return render_template("supplier_form.html", supplier=None)


@app.route("/suppliers/<sid>/edit", methods=["GET", "POST"])
@editor_required
def supplier_edit(sid):
    s = db.session.get(Supplier, sid)
    if not s:
        flash("Supplier not found.", "error")
        return redirect(url_for("suppliers_list"))
    if request.method == "POST":
        s.name = request.form["name"].strip()
        s.contact_name = request.form.get("contact_name", "").strip() or None
        s.contact_phone = request.form.get("contact_phone", "").strip() or None
        s.contact_email = request.form.get("contact_email", "").strip() or None
        s.location = request.form.get("location", "").strip() or None
        s.notes = request.form.get("notes", "").strip() or None
        s.is_active = "is_active" in request.form
        log_audit("update", "supplier", s.id)
        db.session.commit()
        flash("Supplier updated.", "success")
        return redirect(url_for("suppliers_list"))
    return render_template("supplier_form.html", supplier=s)


# ── Strain Performance ───────────────────────────────────────────────────────

@app.route("/strains")
@login_required
def strains_list():
    """Strain performance view grouped by strain name."""
    view = request.args.get("view", "all")

    query = db.session.query(
        PurchaseLot.strain_name,
        Supplier.name.label("supplier_name"),
        func.avg(Run.overall_yield_pct).label("avg_yield"),
        func.avg(Run.thca_yield_pct).label("avg_thca"),
        func.avg(Run.hte_yield_pct).label("avg_hte"),
        func.avg(Run.cost_per_gram_combined).label("avg_cpg"),
        func.count(Run.id).label("run_count"),
        func.sum(Run.bio_in_reactor_lbs).label("total_lbs"),
        func.sum(Run.dry_thca_g).label("total_thca_g"),
        func.sum(Run.dry_hte_g).label("total_hte_g"),
    ).join(RunInput, PurchaseLot.id == RunInput.lot_id
    ).join(Run, RunInput.run_id == Run.id
    ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
    ).join(Supplier, Purchase.supplier_id == Supplier.id
    ).filter(Run.is_rollover == False)
    if _exclude_unpriced_batches_enabled():
        query = query.filter(_priced_run_filter())

    if view == "90":
        query = query.filter(Run.run_date >= date.today() - timedelta(days=90))

    results = query.group_by(PurchaseLot.strain_name, Supplier.name
    ).order_by(desc("avg_yield")).all()

    yield_kpi = KpiTarget.query.filter_by(kpi_name="overall_yield_pct").first()
    thca_kpi = KpiTarget.query.filter_by(kpi_name="thca_yield_pct").first()

    return render_template("strains.html", results=results, view=view,
                           yield_kpi=yield_kpi, thca_kpi=thca_kpi)


# ── Settings (Admin) ─────────────────────────────────────────────────────────

@app.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    if request.method == "POST":
        form_type = request.form.get("form_type")

        if form_type == "system":
            settings_map = {
                "potency_rate": "Potency Rate ($/lb/%pt)",
                "num_reactors": "Number of Reactors",
                "reactor_capacity": "Reactor Capacity (lbs)",
                "runs_per_day": "Runs Per Day Target",
                "operating_days": "Operating Days Per Week",
                "daily_throughput_target": "Daily Throughput Target (lbs)",
                "weekly_throughput_target": "Weekly Throughput Target (lbs)",
            }
            for key, desc in settings_map.items():
                val = request.form.get(key, "").strip()
                if val:
                    existing = db.session.get(SystemSetting, key)
                    if existing:
                        existing.value = val
                    else:
                        db.session.add(SystemSetting(key=key, value=val, description=desc))

            # Cost allocation method (impacts THCA vs HTE $/g calculations)
            method = (request.form.get("cost_allocation_method") or "per_gram_uniform").strip()
            if method not in ("per_gram_uniform", "split_50_50", "custom_split"):
                method = "per_gram_uniform"
            existing = db.session.get(SystemSetting, "cost_allocation_method")
            if existing:
                existing.value = method
            else:
                db.session.add(SystemSetting(
                    key="cost_allocation_method",
                    value=method,
                    description="Cost allocation method for THCA vs HTE cost/gram",
                ))

            # Custom split: % of total run dollars allocated to THCA (0-100)
            pct_raw = (request.form.get("cost_allocation_thca_pct") or "").strip()
            try:
                pct = float(pct_raw) if pct_raw else 50.0
            except ValueError:
                pct = 50.0
            pct = max(0.0, min(100.0, pct))
            existing = db.session.get(SystemSetting, "cost_allocation_thca_pct")
            if existing:
                existing.value = str(pct)
            else:
                db.session.add(SystemSetting(
                    key="cost_allocation_thca_pct",
                    value=str(pct),
                    description="Custom cost allocation: percent of total run cost allocated to THCA",
                ))

            # Analytics toggle: exclude unpriced/unlinked runs from yield + cost calculations
            exclude_val = "1" if request.form.get("exclude_unpriced_batches") else "0"
            existing = db.session.get(SystemSetting, "exclude_unpriced_batches")
            if existing:
                existing.value = exclude_val
            else:
                db.session.add(SystemSetting(
                    key="exclude_unpriced_batches",
                    value=exclude_val,
                    description="Exclude unpriced/unlinked runs from yield and cost analytics",
                ))
            db.session.commit()
            flash("System settings updated.", "success")

        elif form_type == "kpi":
            kpi_ids = request.form.getlist("kpi_ids[]")
            for kid in kpi_ids:
                kpi = db.session.get(KpiTarget, kid)
                if kpi:
                    kpi.target_value = float(request.form.get(f"target_{kid}", kpi.target_value))
                    kpi.green_threshold = float(request.form.get(f"green_{kid}", kpi.green_threshold))
                    kpi.yellow_threshold = float(request.form.get(f"yellow_{kid}", kpi.yellow_threshold))
                    kpi.updated_by = current_user.id
            db.session.commit()
            flash("KPI targets updated.", "success")

        elif form_type == "user":
            username = request.form.get("new_username", "").strip().lower()
            password = request.form.get("new_password", "").strip()
            display = request.form.get("new_display", "").strip()
            role = request.form.get("new_role", "viewer")
            if username and password and display:
                if User.query.filter_by(username=username).first():
                    flash("Username already exists.", "error")
                else:
                    if len(password) < 8:
                        flash("Password must be at least 8 characters.", "error")
                        return redirect(url_for("settings"))
                    u = User(username=username, display_name=display, role=role)
                    u.set_password(password)
                    db.session.add(u)
                    db.session.commit()
                    flash(f"User '{display}' created.", "success")

        elif form_type == "password_self":
            current_pw = request.form.get("current_password", "")
            new_pw = request.form.get("new_password", "").strip()
            confirm_pw = request.form.get("confirm_password", "").strip()

            if not current_user.check_password(current_pw):
                flash("Current password is incorrect.", "error")
                return redirect(url_for("settings"))
            if len(new_pw) < 8:
                flash("New password must be at least 8 characters.", "error")
                return redirect(url_for("settings"))
            if new_pw != confirm_pw:
                flash("New password and confirmation do not match.", "error")
                return redirect(url_for("settings"))

            current_user.set_password(new_pw)
            log_audit("password_change", "user", current_user.id, details=json.dumps({"username": current_user.username}))
            db.session.commit()
            flash("Password updated.", "success")

        elif form_type == "password_user":
            user_id = (request.form.get("user_id") or "").strip()
            new_pw = request.form.get("new_password", "").strip()
            confirm_pw = request.form.get("confirm_password", "").strip()
            u = db.session.get(User, user_id) if user_id else None
            if not u:
                flash("User not found.", "error")
                return redirect(url_for("settings"))
            if len(new_pw) < 8:
                flash("New password must be at least 8 characters.", "error")
                return redirect(url_for("settings"))
            if new_pw != confirm_pw:
                flash("New password and confirmation do not match.", "error")
                return redirect(url_for("settings"))

            u.set_password(new_pw)
            log_audit("password_reset", "user", u.id, details=json.dumps({"username": u.username}))
            db.session.commit()
            flash(f"Password updated for '{u.display_name}'.", "success")

        return redirect(url_for("settings"))

    system_settings = {s.key: s.value for s in SystemSetting.query.all()}
    kpis = KpiTarget.query.all()
    users = User.query.order_by(User.created_at.asc()).all()
    field_tokens = FieldAccessToken.query.order_by(FieldAccessToken.created_at.desc()).all()
    field_submissions = FieldPurchaseSubmission.query.order_by(FieldPurchaseSubmission.submitted_at.desc()).all()
    for s in field_submissions:
        try:
            s.lots_count = len(json.loads(s.lots_json or "[]"))
        except Exception:
            s.lots_count = 0

    # One-time display after creating a field link (POST-redirect-GET)
    last_field_link = session.pop("last_field_link", None)
    last_field_sms = session.pop("last_field_sms", None)
    last_field_email_subject = session.pop("last_field_email_subject", None)
    last_field_email_body = session.pop("last_field_email_body", None)

    return render_template(
        "settings.html",
        system_settings=system_settings,
        kpis=kpis,
        users=users,
        field_tokens=field_tokens,
        field_submissions=field_submissions,
        server_now=datetime.utcnow(),
        last_field_link=last_field_link,
        last_field_sms=last_field_sms,
        last_field_email_subject=last_field_email_subject,
        last_field_email_body=last_field_email_body,
    )


@app.route("/settings/users/<user_id>/toggle_active", methods=["POST"])
@admin_required
def user_toggle_active(user_id):
    """
    "Delete" users safely by deactivating them (keeps audit history intact).
    Super Admin can deactivate/reactivate users.
    """
    u = db.session.get(User, user_id)
    if not u:
        flash("User not found.", "error")
        return redirect(url_for("settings"))

    # Prevent self-disable (avoid locking yourself out)
    if current_user.id == u.id:
        flash("You cannot disable your own account.", "error")
        return redirect(url_for("settings"))

    # Prevent disabling the last active super admin
    if u.role == "super_admin" and u.is_active_user:
        active_admins = User.query.filter_by(role="super_admin", is_active_user=True).count()
        if active_admins <= 1:
            flash("You cannot disable the last active Super Admin.", "error")
            return redirect(url_for("settings"))

    u.is_active_user = not bool(u.is_active_user)
    log_audit(
        "activate" if u.is_active_user else "deactivate",
        "user",
        u.id,
        details=json.dumps({"username": u.username, "role": u.role}),
    )
    db.session.commit()
    flash(f"User {'activated' if u.is_active_user else 'disabled'}.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/field_tokens/new", methods=["POST"])
@admin_required
def field_token_create():
    label = (request.form.get("label") or "").strip()
    if not label:
        flash("Token label is required.", "error")
        return redirect(url_for("settings"))

    days_raw = (request.form.get("expires_days") or "").strip()
    try:
        expires_days = int(days_raw) if days_raw else 30
    except ValueError:
        expires_days = 30
    expires_days = max(1, min(365, expires_days))

    token_plain = secrets.token_urlsafe(32)
    tok = FieldAccessToken(
        label=label,
        token_hash=_hash_field_token(token_plain),
        created_by=current_user.id,
        expires_at=datetime.utcnow() + timedelta(days=expires_days),
    )
    db.session.add(tok)
    log_audit("create", "field_access_token", tok.id, details=json.dumps({"label": label, "expires_days": expires_days}))
    db.session.commit()

    link = url_for("field_home", t=token_plain, _external=True)
    # Store in session so Settings can render a copy/share UI once.
    session["last_field_link"] = link
    session["last_field_sms"] = f"Gold Drop field intake link: {link}"
    session["last_field_email_subject"] = "Gold Drop — Field Intake Link"
    session["last_field_email_body"] = (
        "Here is your Gold Drop field intake link (no login required):\n\n"
        f"{link}\n\n"
        "Use it to submit biomass availability or potential purchases from the field."
    )
    flash("Field link created. Scroll down to copy/share it.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/field_tokens/<token_id>/revoke", methods=["POST"])
@admin_required
def field_token_revoke(token_id):
    tok = db.session.get(FieldAccessToken, token_id)
    if not tok:
        flash("Token not found.", "error")
        return redirect(url_for("settings"))
    tok.revoked_at = datetime.utcnow()
    log_audit("revoke", "field_access_token", tok.id, details=json.dumps({"label": tok.label}))
    db.session.commit()
    flash("Token revoked.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/field_submissions/<submission_id>/approve", methods=["POST"])
@admin_required
def field_submission_approve(submission_id):
    sub = db.session.get(FieldPurchaseSubmission, submission_id)
    if not sub:
        flash("Submission not found.", "error")
        return redirect(url_for("settings"))
    if sub.status != "pending":
        flash("Submission has already been reviewed.", "error")
        return redirect(url_for("settings"))

    try:
        lots = json.loads(sub.lots_json or "[]")
    except Exception:
        lots = []
    if not lots:
        flash("Submission has no lot lines.", "error")
        return redirect(url_for("settings"))

    total_weight = sum(float(l.get("weight_lbs") or 0) for l in lots)
    if total_weight <= 0:
        flash("Submission lot weights are invalid.", "error")
        return redirect(url_for("settings"))

    purchase = Purchase(
        supplier_id=sub.supplier_id,
        purchase_date=sub.purchase_date,
        delivery_date=sub.delivery_date,
        status="committed",
        stated_weight_lbs=total_weight,
        stated_potency_pct=sub.estimated_potency_pct,
        price_per_lb=sub.price_per_lb,
        notes=(sub.notes or "") + (f"\n\nApproved from field submission {sub.id}" if sub.notes else f"Approved from field submission {sub.id}"),
    )
    db.session.add(purchase)
    db.session.flush()

    # Create lots
    for l in lots:
        strain = (l.get("strain") or "").strip()
        w = float(l.get("weight_lbs") or 0)
        if not strain or w <= 0:
            continue
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name=strain,
            weight_lbs=w,
            remaining_weight_lbs=w,
        )
        db.session.add(lot)

    # Generate batch id
    sup = db.session.get(Supplier, purchase.supplier_id)
    supplier_name = sup.name if sup else "BATCH"
    d = purchase.delivery_date or purchase.purchase_date
    purchase.batch_id = _ensure_unique_batch_id(_generate_batch_id(supplier_name, d, total_weight), exclude_purchase_id=purchase.id)

    # Total cost if possible
    if purchase.price_per_lb:
        purchase.total_cost = purchase.stated_weight_lbs * purchase.price_per_lb

    # Mark submission approved
    sub.status = "approved"
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by = current_user.id
    sub.review_notes = (request.form.get("review_notes") or "").strip() or None
    sub.approved_purchase_id = purchase.id

    log_audit("approve", "field_purchase_submission", sub.id, details=json.dumps({"purchase_id": purchase.id}))
    log_audit("create", "purchase", purchase.id, details=json.dumps({"source": "field_submission", "submission_id": sub.id}))
    db.session.commit()
    flash("Submission approved and converted to a Purchase.", "success")
    return redirect(url_for("purchase_edit", purchase_id=purchase.id))


@app.route("/settings/field_submissions/<submission_id>/reject", methods=["POST"])
@admin_required
def field_submission_reject(submission_id):
    sub = db.session.get(FieldPurchaseSubmission, submission_id)
    if not sub:
        flash("Submission not found.", "error")
        return redirect(url_for("settings"))
    if sub.status != "pending":
        flash("Submission has already been reviewed.", "error")
        return redirect(url_for("settings"))
    sub.status = "rejected"
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by = current_user.id
    sub.review_notes = (request.form.get("review_notes") or "").strip() or None
    log_audit("reject", "field_purchase_submission", sub.id, details=json.dumps({"notes": sub.review_notes}))
    db.session.commit()
    flash("Submission rejected.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/recalculate_costs", methods=["POST"])
@admin_required
def settings_recalculate_costs():
    """Recalculate cost-per-gram fields for all runs using current allocation logic."""
    try:
        runs = Run.query.order_by(Run.run_date.asc()).all()
        updated = 0
        for r in runs:
            r.calculate_cost()
            updated += 1
        db.session.commit()
        flash(f"Recalculated costs for {updated} runs.", "success")
    except Exception as e:
        db.session.rollback()
        flash(f"Cost recalculation failed: {e}", "error")
    return redirect(url_for("settings"))


# ── CSV Import/Export ────────────────────────────────────────────────────────

@app.route("/export/<entity>")
@login_required
def export_csv(entity):
    """Export data as CSV."""
    si = io.StringIO()
    writer = csv.writer(si)

    if entity == "runs":
        writer.writerow(["Date", "Reactor", "Rollover", "Source", "Lbs Ran", "Grams Ran",
                         "Wet HTE", "Wet THCA", "Dry HTE", "Dry THCA", "Overall Yield %",
                         "THCA Yield %", "HTE Yield %", "Cost/Gram", "Notes"])
        for r in Run.query.order_by(Run.run_date.desc()).all():
            writer.writerow([r.run_date, r.reactor_number, r.is_rollover, r.source_display,
                             r.bio_in_reactor_lbs, r.grams_ran, r.wet_hte_g, r.wet_thca_g,
                             r.dry_hte_g, r.dry_thca_g,
                             f"{r.overall_yield_pct:.2f}" if r.overall_yield_pct else "",
                             f"{r.thca_yield_pct:.2f}" if r.thca_yield_pct else "",
                             f"{r.hte_yield_pct:.2f}" if r.hte_yield_pct else "",
                             f"{r.cost_per_gram_combined:.2f}" if r.cost_per_gram_combined else "",
                             r.notes or ""])
    elif entity == "purchases":
        writer.writerow(["Date", "Batch ID", "Supplier", "Status", "Stated Lbs", "Actual Lbs",
                         "Stated Potency", "Tested Potency", "Price/Lb", "Total Cost",
                         "True-Up", "Strains"])
        for p in Purchase.query.order_by(Purchase.purchase_date.desc()).all():
            strains = ", ".join([l.strain_name for l in p.lots])
            writer.writerow([p.purchase_date, p.batch_id, p.supplier_name, p.status,
                             p.stated_weight_lbs, p.actual_weight_lbs,
                             p.stated_potency_pct, p.tested_potency_pct,
                             p.price_per_lb, p.total_cost, p.true_up_amount, strains])
    elif entity == "inventory":
        writer.writerow(["Strain", "Supplier", "Weight (lbs)", "Remaining (lbs)",
                         "Potency %", "Milled", "Location"])
        for l in PurchaseLot.query.filter(PurchaseLot.remaining_weight_lbs > 0).all():
            writer.writerow([l.strain_name, l.supplier_name, l.weight_lbs,
                             l.remaining_weight_lbs, l.potency_pct, l.milled, l.location])
    elif entity == "biomass":
        writer.writerow([
            "Stage", "Supplier", "Strain",
            "Availability Date", "Declared Lbs", "Declared $/lb", "Est Potency %",
            "Testing Timing", "Testing Status", "Testing Date", "Tested Potency %",
            "Committed On", "Delivery Date", "Committed Lbs", "Committed $/lb",
            "Batch ID", "Purchase Status",
            "Notes",
        ])
        q = BiomassAvailability.query.join(Supplier).order_by(
            BiomassAvailability.availability_date.desc(),
            Supplier.name.asc(),
        ).all()
        for b in q:
            writer.writerow([
                b.stage,
                b.supplier_name,
                b.strain_name or "",
                b.availability_date,
                b.declared_weight_lbs,
                b.declared_price_per_lb,
                b.estimated_potency_pct,
                b.testing_timing,
                b.testing_status,
                b.testing_date,
                b.tested_potency_pct,
                b.committed_on,
                b.committed_delivery_date,
                b.committed_weight_lbs,
                b.committed_price_per_lb,
                b.purchase.batch_id if b.purchase else "",
                b.purchase.status if b.purchase else "",
                b.notes or "",
            ])
    else:
        return "Unknown entity", 404

    output = si.getvalue()
    return Response(output, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={entity}_{date.today()}.csv"})


@app.route("/import", methods=["GET", "POST"])
@editor_required
def import_csv():
    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename.endswith(".csv"):
            flash("Please upload a CSV file.", "error")
            return redirect(url_for("import_csv"))

        content = file.stream.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        rows = list(reader)

        # Filter out header-like rows (from the repeating header pattern in the Google Sheet)
        data_rows = [r for r in rows if not any(
            v and v.strip().lower() in ("date", "bio in house", "lbs ran")
            for v in r.values()
        )]

        # Store in session for dedup review
        session["import_data"] = json.dumps(data_rows[:500])  # Limit to 500 rows
        session["import_columns"] = list(rows[0].keys()) if rows else []

        flash(f"Loaded {len(data_rows)} data rows (filtered {len(rows) - len(data_rows)} header rows). Review below.", "info")
        return render_template("import_review.html", rows=data_rows[:50],
                               columns=session["import_columns"],
                               total=len(data_rows))

    return render_template("import.html")


@app.route("/import/confirm", methods=["POST"])
@editor_required
def import_confirm():
    """Process confirmed import."""
    data = json.loads(session.get("import_data", "[]"))
    if not data:
        flash("No data to import.", "error")
        return redirect(url_for("import_csv"))

    imported = 0
    skipped = 0
    errors = 0

    # Build supplier lookup
    suppliers = {s.name.lower(): s for s in Supplier.query.all()}

    for row in data:
        try:
            # Map columns from Google Sheet format
            source = (row.get("Source") or row.get("source") or "").strip()
            strain = (row.get("Strain") or row.get("strain") or "").strip()
            run_date_str = (row.get("Date") or row.get("date") or "").strip()

            if not run_date_str or not strain:
                skipped += 1
                continue

            # Parse date (handle various formats)
            run_date = _parse_date(run_date_str)
            if not run_date:
                skipped += 1
                continue

            # Check for duplicate
            existing = Run.query.join(RunInput).join(PurchaseLot).filter(
                Run.run_date == run_date,
                PurchaseLot.strain_name == strain,
            ).first()
            if existing:
                skipped += 1
                continue

            # Get or create supplier
            supplier = suppliers.get(source.lower())
            if not supplier and source:
                supplier = Supplier(name=source)
                db.session.add(supplier)
                db.session.flush()
                suppliers[source.lower()] = supplier

            # Get or create purchase/lot
            if supplier:
                purchase = Purchase.query.filter_by(
                    supplier_id=supplier.id
                ).order_by(Purchase.purchase_date.desc()).first()

                if not purchase:
                    purchase = Purchase(
                        supplier_id=supplier.id,
                        purchase_date=run_date,
                        status="complete",
                        stated_weight_lbs=0,
                    )
                    price = row.get("Price") or row.get("price") or ""
                    price = price.replace("$", "").replace(",", "").strip()
                    if price:
                        try:
                            purchase.price_per_lb = float(price)
                        except ValueError:
                            pass
                    db.session.add(purchase)
                    db.session.flush()

                lot = PurchaseLot.query.filter_by(
                    purchase_id=purchase.id,
                    strain_name=strain,
                ).first()
                if not lot:
                    lot = PurchaseLot(
                        purchase_id=purchase.id,
                        strain_name=strain,
                        weight_lbs=0,
                        remaining_weight_lbs=0,
                    )
                    db.session.add(lot)
                    db.session.flush()

            # Create run
            lbs_ran = _parse_float(row.get("LBS Ran") or row.get("lbs_ran") or "")
            grams_ran = _parse_float(row.get("Grams Ran") or row.get("grams_ran") or "")

            run = Run(
                run_date=run_date,
                reactor_number=1,
                is_rollover=False,
                bio_in_house_lbs=_parse_float(row.get("Bio in house") or ""),
                bio_in_reactor_lbs=lbs_ran,
                grams_ran=grams_ran or (lbs_ran * 454 if lbs_ran else None),
                butane_in_house_lbs=_parse_float(row.get("Butane IN HOUSE") or ""),
                solvent_ratio=_parse_float(row.get("Solvent Ratio") or ""),
                wet_hte_g=_parse_float(row.get("Wet HTE") or ""),
                wet_thca_g=_parse_float(row.get("Wet THCa") or ""),
                dry_hte_g=_parse_float(row.get("DRY THCA") or row.get("Dry HTE") or ""),
                dry_thca_g=_parse_float(row.get("DRY THCA") or ""),
                run_type="standard",
            )

            # Fix: map columns correctly
            dry_hte = _parse_float(row.get("Dry HTE") or row.get("DRY HTE") or "")
            dry_thca = _parse_float(row.get("DRY THCA") or row.get("Dry THCA") or "")
            run.dry_hte_g = dry_hte
            run.dry_thca_g = dry_thca

            run.calculate_yields()
            db.session.add(run)
            db.session.flush()

            # Link run to lot
            if supplier and lot and lbs_ran:
                inp = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=lbs_ran)
                db.session.add(inp)
                lot.weight_lbs += lbs_ran
                run.calculate_cost()

            imported += 1

        except Exception as e:
            errors += 1
            continue

    db.session.commit()
    session.pop("import_data", None)
    session.pop("import_columns", None)
    flash(f"Import complete: {imported} imported, {skipped} skipped, {errors} errors.", "success")
    return redirect(url_for("runs_list"))


def _parse_date(s):
    """Parse various date formats from the Google Sheet."""
    s = s.strip().replace("_", "/")
    for fmt in ("%m/%d", "%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            d = datetime.strptime(s, fmt).date()
            if d.year == 1900:  # Default year for mm/dd format
                d = d.replace(year=2025)
            return d
        except ValueError:
            continue
    return None


def _parse_float(s):
    """Safely parse a float from string."""
    if not s:
        return None
    s = str(s).replace(",", "").replace("$", "").replace("%", "").strip()
    try:
        val = float(s)
        return val if val != 0 else None
    except (ValueError, TypeError):
        return None


# ── Lots management ──────────────────────────────────────────────────────────

@app.route("/purchases/<purchase_id>/lots/new", methods=["POST"])
@editor_required
def lot_new(purchase_id):
    purchase = db.session.get(Purchase, purchase_id)
    if not purchase:
        flash("Purchase not found.", "error")
        return redirect(url_for("purchases_list"))

    lot = PurchaseLot(
        purchase_id=purchase_id,
        strain_name=request.form["strain_name"].strip(),
        weight_lbs=float(request.form["weight_lbs"]),
        remaining_weight_lbs=float(request.form["weight_lbs"]),
        potency_pct=float(request.form.get("potency_pct") or 0) or None,
        milled="milled" in request.form,
        location=request.form.get("location", "").strip() or None,
    )
    db.session.add(lot)
    log_audit("create", "lot", lot.id)
    db.session.commit()
    flash("Lot added.", "success")
    return redirect(url_for("purchase_edit", purchase_id=purchase_id))


# ── Biomass Availability Pipeline ─────────────────────────────────────────────

@app.route("/biomass")
@login_required
def biomass_list():
    stage = request.args.get("stage", "").strip()
    query = BiomassAvailability.query.join(Supplier)
    if stage:
        query = query.filter(BiomassAvailability.stage == stage)
    items = query.order_by(BiomassAvailability.availability_date.desc(), Supplier.name.asc()).all()
    return render_template("biomass.html", items=items, stage_filter=stage)


@app.route("/biomass/new", methods=["GET", "POST"])
@editor_required
def biomass_new():
    if request.method == "POST":
        return _save_biomass(None)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template("biomass_form.html", item=None, suppliers=suppliers, today=date.today())


@app.route("/biomass/<item_id>/edit", methods=["GET", "POST"])
@editor_required
def biomass_edit(item_id):
    item = db.session.get(BiomassAvailability, item_id)
    if not item:
        flash("Biomass availability record not found.", "error")
        return redirect(url_for("biomass_list"))
    if request.method == "POST":
        return _save_biomass(item)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template("biomass_form.html", item=item, suppliers=suppliers, today=date.today())


def _save_biomass(existing):
    try:
        b = existing or BiomassAvailability()
        supplier_id = (request.form.get("supplier_id") or "").strip()
        if not supplier_id:
            raise ValueError("Supplier is required.")
        supplier = db.session.get(Supplier, supplier_id)
        if not supplier:
            raise ValueError("Selected supplier was not found.")
        b.supplier_id = supplier_id

        ad = request.form.get("availability_date", "").strip()
        if not ad:
            raise ValueError("Availability Date is required.")
        try:
            b.availability_date = datetime.strptime(ad, "%Y-%m-%d").date()
        except ValueError:
            raise ValueError("Availability Date must be a valid date.")

        b.strain_name = request.form.get("strain_name", "").strip() or None

        dw = request.form.get("declared_weight_lbs", "").strip()
        try:
            b.declared_weight_lbs = float(dw) if dw else 0.0
        except ValueError:
            raise ValueError("Declared Weight must be a number.")
        if b.declared_weight_lbs < 0:
            raise ValueError("Declared Weight cannot be negative.")

        dpl = request.form.get("declared_price_per_lb", "").strip()
        try:
            b.declared_price_per_lb = float(dpl) if dpl else None
        except ValueError:
            raise ValueError("Declared $/lb must be a number.")
        if b.declared_price_per_lb is not None and b.declared_price_per_lb < 0:
            raise ValueError("Declared $/lb cannot be negative.")

        ep = request.form.get("estimated_potency_pct", "").strip()
        try:
            b.estimated_potency_pct = float(ep) if ep else None
        except ValueError:
            raise ValueError("Estimated Potency must be a number.")
        if b.estimated_potency_pct is not None and not (0 <= b.estimated_potency_pct <= 100):
            raise ValueError("Estimated Potency must be between 0 and 100.")

        testing_timing = (request.form.get("testing_timing") or "before_delivery").strip()
        if testing_timing not in ("before_delivery", "after_delivery"):
            raise ValueError("Testing Timing is invalid.")
        b.testing_timing = testing_timing

        testing_status = (request.form.get("testing_status") or "pending").strip()
        if testing_status not in ("pending", "completed", "not_needed"):
            raise ValueError("Testing Status is invalid.")
        b.testing_status = testing_status

        td = request.form.get("testing_date", "").strip()
        if td:
            try:
                b.testing_date = datetime.strptime(td, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Testing Date must be a valid date.")
        else:
            b.testing_date = None

        tpp = request.form.get("tested_potency_pct", "").strip()
        try:
            b.tested_potency_pct = float(tpp) if tpp else None
        except ValueError:
            raise ValueError("Tested Potency must be a number.")
        if b.tested_potency_pct is not None and not (0 <= b.tested_potency_pct <= 100):
            raise ValueError("Tested Potency must be between 0 and 100.")

        co = request.form.get("committed_on", "").strip()
        if co:
            try:
                b.committed_on = datetime.strptime(co, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Committed On must be a valid date.")
        else:
            b.committed_on = None

        cdd = request.form.get("committed_delivery_date", "").strip()
        if cdd:
            try:
                b.committed_delivery_date = datetime.strptime(cdd, "%Y-%m-%d").date()
            except ValueError:
                raise ValueError("Delivery Date must be a valid date.")
        else:
            b.committed_delivery_date = None

        cw = request.form.get("committed_weight_lbs", "").strip()
        try:
            b.committed_weight_lbs = float(cw) if cw else None
        except ValueError:
            raise ValueError("Committed Weight must be a number.")
        if b.committed_weight_lbs is not None and b.committed_weight_lbs < 0:
            raise ValueError("Committed Weight cannot be negative.")

        cpl = request.form.get("committed_price_per_lb", "").strip()
        try:
            b.committed_price_per_lb = float(cpl) if cpl else None
        except ValueError:
            raise ValueError("Committed $/lb must be a number.")
        if b.committed_price_per_lb is not None and b.committed_price_per_lb < 0:
            raise ValueError("Committed $/lb cannot be negative.")

        stage = (request.form.get("stage") or "declared").strip()
        allowed_stages = ("declared", "testing", "committed", "delivered", "cancelled")
        if stage not in allowed_stages:
            raise ValueError("Stage is invalid.")
        b.stage = stage
        b.notes = request.form.get("notes", "").strip() or None

        if not existing:
            db.session.add(b)
        db.session.flush()

        # Keep linked Purchase in sync (create on commitment, but always sync if already linked)
        stage_to_status = {
            "declared": "declared",
            "testing": "in_testing",
            "committed": "committed",
            "delivered": "delivered",
            "cancelled": "cancelled",
        }
        if b.stage in stage_to_status:
            purchase = db.session.get(Purchase, b.purchase_id) if b.purchase_id else None
            purchase_was_new = False

            # Create a purchase record only once the batch becomes committed/delivered
            if not purchase and b.stage in ("committed", "delivered"):
                purchase = Purchase(
                    supplier_id=b.supplier_id,
                    purchase_date=b.committed_on or b.availability_date,
                    delivery_date=b.committed_delivery_date,
                    status=stage_to_status[b.stage],
                    stated_weight_lbs=float(b.committed_weight_lbs or b.declared_weight_lbs or 0),
                    stated_potency_pct=b.estimated_potency_pct,
                    tested_potency_pct=b.tested_potency_pct,
                    price_per_lb=b.committed_price_per_lb or b.declared_price_per_lb,
                    notes=f"Created from Biomass Pipeline ({b.id})",
                )
                db.session.add(purchase)
                db.session.flush()
                b.purchase_id = purchase.id
                purchase_was_new = True

            if purchase:
                purchase.supplier_id = b.supplier_id
                purchase.purchase_date = b.committed_on or b.availability_date
                purchase.delivery_date = b.committed_delivery_date
                purchase.status = stage_to_status[b.stage]
                purchase.stated_weight_lbs = float(b.committed_weight_lbs or b.declared_weight_lbs or 0)
                purchase.stated_potency_pct = b.estimated_potency_pct
                purchase.tested_potency_pct = b.tested_potency_pct
                purchase.price_per_lb = b.committed_price_per_lb or b.declared_price_per_lb

                # Total cost
                w = purchase.actual_weight_lbs or purchase.stated_weight_lbs
                if w and purchase.price_per_lb:
                    purchase.total_cost = w * purchase.price_per_lb

                # Batch ID
                if not purchase.batch_id:
                    sup = db.session.get(Supplier, purchase.supplier_id)
                    supplier_name = sup.name if sup else "BATCH"
                    d = purchase.delivery_date or purchase.purchase_date
                    purchase.batch_id = _ensure_unique_batch_id(
                        _generate_batch_id(supplier_name, d, w),
                        exclude_purchase_id=purchase.id,
                    )

                # Purchase audit log (so biomass-driven changes are reconstructable)
                log_audit(
                    "create" if purchase_was_new else "update",
                    "purchase",
                    purchase.id,
                    details=json.dumps({
                        "source": "biomass_pipeline",
                        "biomass_id": b.id,
                        "stage": b.stage,
                        "status": purchase.status,
                    }),
                )

        log_audit("update" if existing else "create", "biomass_availability", b.id)
        db.session.commit()
        flash("Biomass availability saved.", "success")
        return redirect(url_for("biomass_list"))
    except ValueError as e:
        db.session.rollback()
        flash(str(e), "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        return render_template("biomass_form.html", item=existing, suppliers=suppliers, today=date.today())
    except Exception:
        db.session.rollback()
        app.logger.exception("Error saving biomass availability")
        flash("Error saving biomass availability. Please check your inputs and try again.", "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        return render_template("biomass_form.html", item=existing, suppliers=suppliers, today=date.today())


@app.route("/biomass/<item_id>/delete", methods=["POST"])
@editor_required
def biomass_delete(item_id):
    item = db.session.get(BiomassAvailability, item_id)
    if item:
        log_audit("delete", "biomass_availability", item.id)
        db.session.delete(item)
        db.session.commit()
        flash("Biomass availability deleted.", "success")
    return redirect(url_for("biomass_list"))


# ── API endpoints for AJAX ───────────────────────────────────────────────────

@app.route("/api/lots/available")
@login_required
def api_lots_available():
    lots = PurchaseLot.query.filter(PurchaseLot.remaining_weight_lbs > 0).all()
    return jsonify([{
        "id": l.id,
        "strain": l.strain_name,
        "supplier": l.supplier_name,
        "remaining": l.remaining_weight_lbs,
        "label": l.display_label,
    } for l in lots])


# ── Initialize ───────────────────────────────────────────────────────────────

def init_db():
    """Create tables and seed initial data."""
    db.create_all()
    _ensure_sqlite_schema()

    # Create default admin if none exists
    if not User.query.first():
        admin = User(username="admin", display_name="Admin", role="super_admin")
        admin.set_password("golddrop2026")
        db.session.add(admin)

        user = User(username="ops", display_name="VP Operations", role="user")
        user.set_password("golddrop2026")
        db.session.add(user)

        viewer = User(username="viewer", display_name="Team Viewer", role="viewer")
        viewer.set_password("golddrop2026")
        db.session.add(viewer)

    # Seed system settings
    defaults = {
        "potency_rate": ("1.50", "Potency Rate ($/lb/%pt)"),
        "num_reactors": ("2", "Number of Reactors"),
        "reactor_capacity": ("100", "Reactor Capacity (lbs)"),
        "runs_per_day": ("5", "Runs Per Day Target"),
        "operating_days": ("7", "Operating Days Per Week"),
        "daily_throughput_target": ("500", "Daily Throughput Target (lbs)"),
        "weekly_throughput_target": ("3500", "Weekly Throughput Target (lbs)"),
        "exclude_unpriced_batches": ("0", "Exclude unpriced/unlinked runs from yield and cost analytics"),
        "cost_allocation_method": ("per_gram_uniform", "Cost allocation method for THCA vs HTE cost/gram"),
        "cost_allocation_thca_pct": ("50", "Custom cost allocation: percent of total run cost allocated to THCA"),
    }
    for key, (val, desc) in defaults.items():
        if not db.session.get(SystemSetting, key):
            db.session.add(SystemSetting(key=key, value=val, description=desc))

    # Seed KPI targets
    kpi_defaults = [
        ("thca_yield_pct", "THCA Yield %", 7.0, 7.0, 6.0, "higher_is_better", "%"),
        ("hte_yield_pct", "HTE Yield %", 5.0, 5.0, 4.0, "higher_is_better", "%"),
        ("overall_yield_pct", "Overall Yield %", 12.0, 12.0, 10.0, "higher_is_better", "%"),
        ("cost_per_potency_point", "Cost per Potency Point", 1.50, 1.35, 1.65, "lower_is_better", "$/lb/%pt"),
        ("cost_per_gram_combined", "Cost per Gram", 5.0, 4.0, 6.0, "lower_is_better", "$/g"),
        ("cost_per_gram_thca", "Cost per Gram (THCA)", 5.0, 4.0, 6.0, "lower_is_better", "$/g"),
        ("cost_per_gram_hte", "Cost per Gram (HTE)", 5.0, 4.0, 6.0, "lower_is_better", "$/g"),
        ("weekly_throughput", "Weekly Throughput", 3500, 3500, 3000, "higher_is_better", "lbs"),
    ]
    for name, display, target, green, yellow, direction, unit in kpi_defaults:
        if not KpiTarget.query.filter_by(kpi_name=name).first():
            db.session.add(KpiTarget(
                kpi_name=name, display_name=display, target_value=target,
                green_threshold=green, yellow_threshold=yellow,
                direction=direction, unit=unit
            ))

    db.session.commit()

    # Seed historical run data if database is empty
    if Run.query.count() == 0:
        _seed_historical_data()

    # Backfill batch IDs for any existing purchases (including seeded purchases)
    missing = Purchase.query.filter(db.or_(Purchase.batch_id.is_(None), Purchase.batch_id == "")).all()
    for p in missing:
        supplier_name = p.supplier_name
        d = p.delivery_date or p.purchase_date
        w = p.actual_weight_lbs or p.stated_weight_lbs
        p.batch_id = _ensure_unique_batch_id(_generate_batch_id(supplier_name, d, w), exclude_purchase_id=p.id)
    if missing:
        db.session.commit()


def _seed_historical_data():
    """Import 43 runs from Gold Drop's Google Sheet (Jan 13 – Feb 6, 2026)."""
    from datetime import datetime as dt

    print("Seeding historical run data from Google Sheet...")

    RAW = [
        ("2/6","315","16","10.1","rockets x Humbolt 1 & 2","Farmlane","23.00","200","90800","3762","7627","","5710"),
        ("2/5","400","20","10.1","Bubble Gum Gushers/ Rollover","Honey Pot/ Rollover","","200","90800","3224","9557","","7110"),
        ("2/5","","","10.1","Coffee Creamer 1 & 2","Verde","","200","90800","5288","9007","","7550"),
        ("2/5","386","10","10.1","ADL #1","Canndescent","","100","45400","4454","4637","","3810"),
        ("2/4","","","10.1","Rockets x Humbolt","Farmlane/Rollover","","200","90800","4362","8107","","6490"),
        ("2/4","809","14","10.1","Rockets x Humbolt","Farmlane","","200","90800","5062","11797","","9240"),
        ("2/3","","","10.1","Rockets x Humbolt","Farmlane","","200","90800","4088","12857","","8670"),
        ("2/3","955","18","","Rockets x Humbolt","Farmlane","","200","90800","4478","11857","4120","8330"),
        ("2/2","","","","Rockets x Humbolt","Farmlane","","200","90800","5320","9777","4890","7870"),
        ("2/2","1326","8","","Rockets x Humbolt","Farmlane","","200","90800","3676","8927","3240","7210"),
        ("1/30","","","","Dosi Gelonade 4","7 Leaves","","100","45400","12772","0","",""),
        ("1/30","","","","ACME 1","ACME","","100","45400","9220","0","",""),
        ("1/30","","","","Dosi Gelonade 2&3","7 Leaves","","200","90800","4626","11067","4120","8400"),
        ("1/30","","","","Oakland Runtz x Dosi Gelonade","Clock Tower x 7 Leaves","","200","90800","2392","9327","1980","7830"),
        ("1/29","","16","","Oakland Runtz 1&2","Clock Tower","","200","90800","5262","12757","4030","9520"),
        ("1/29","2328","16","","K-Train 4&5","SmGreenTech","","200","90800","4192","6587","3780","5540"),
        ("1/28","","9","","K-Train 2&3","SmGreenTech","","200","90800","4884","7830","3726","6400"),
        ("1/28","1017","15","","Spent 4 x K-Train 1","SmGreenTech/COT","","200","90800","4436","4070","3000","3620"),
        ("1/27","","15","","Spent 2&3 COT","City of Trees","","200","90800","1816","1560","744","1430"),
        ("1/27","","15","","K-Train 4 x Spent COT","SmGreenTech/COT","","200","90800","4716","6830","2912","5080"),
        ("1/27","","15","","K-Train 2&3","SmGreenTech","","200","90800","6122","11520","5654","8380"),
        ("1/26","","","","Gello x K-Train","SmGreenTech","","200","90800","4976","10060","4266","7880"),
        ("1/26","","10","","Gello 3&4","SmGreenTech","","200","90800","6386","8270","6090","7330"),
        ("1/23","","","","Gello 1&2","SmGreenTech","","200","90800","5194","10980","4830","7820"),
        ("1/23","886","","","K-Whip 3&4","SmGreenTech","","200","90800","4512","10420","4002","7200"),
        ("1/23","","","","K-Whip 1&2","SmGreenTech","","200","90800","5278","10370","4914","8200"),
        ("1/23","1288","","","BJxHFCS 3&4","Canndescent","","200","90800","5084","8550","4942","6770"),
        ("1/22","","","","BJxHFCS 1&2","Canndescent","","200","90800","2984","8600","2724","7290"),
        ("1/22","1588","","","Citrus Project/Rollover","Rollover","","200","90800","6200","10870","5980","7090"),
        ("1/21","691","11","","Apple Strudle x Mango Mintality","ACME","","200","90800","6010","8180","5870","6480"),
        ("1/20","548","16","","Rollover","Rollover","","200","90800","4886","11790","4660","8290"),
        ("1/19","","","","Purple Punch","City of Trees/Rollover","","200","90800","4424","13820","4220","11350"),
        ("1/19","1050","","","Frosted Blue Runtz","Founding Fathers","","200","90800","5404","8960","5304","7330"),
        ("1/17","1050","","","K Whip x Pinyatti 8&9","SmGreenTech","","200","90800","5714","12510","5208","8920"),
        ("1/16","","","","K Whip x Pinyatti 7(pot pour)","SmGreenTech","","100","45400","6326","0","2621","2775"),
        ("1/16","","","","K Whip x Pinyatti 5&6","SmGreenTech","","200","90800","5420","10030","4978","7540"),
        ("1/16","1584","","","K Whip x Pinyatti 3&4","SmGreenTech","","200","90800","5230","10280","4888","8210"),
        ("1/15","","","","K Whip x Pinyatti 1&2","SmGreenTech","","200","90800","5784","10630","5520","8390"),
        ("1/15","1998","","","Cookies x Pink Gator 3&4","Farmlane","","200","90800","3654","9170","3354","7960"),
        ("1/14","","","","Cookies x Pink Gator 1&2","Farmlane","","200","90800","4494","10240","4190","7510"),
        ("1/14","2392","","","Pink Runtz X Gello 11&12","Canndescent","","200","90800","4210","9480","3870","7920"),
        ("1/13","1244","","","Pink Runtz X Gello 9&10","Canndescent","","200","90800","3510","10670","3290","8410"),
        ("1/13","1243","","","Pink Runtz X Gello 7&8","Canndescent","","200","90800","3160","9960","2650","7970"),
    ]

    SRC_MAP = {
        "Farmlane": "Farmlane", "Farmlane/Rollover": "Farmlane",
        "SmGreenTech": "SmGreenTech", "SmGreenTech/COT": "SmGreenTech",
        "Canndescent": "Canndescent", "7 Leaves": "7 Leaves",
        "ACME": "ACME", "Clock Tower": "Clock Tower",
        "Clock Tower x 7 Leaves": "Clock Tower",
        "City of Trees": "City of Trees", "City of Trees/Rollover": "City of Trees",
        "Verde": "Verde", "Honey Pot/ Rollover": "Honey Pot",
        "Founding Fathers": "Founding Fathers",
        "Rollover": "Rollover (Blends)",
    }

    def pf(s):
        if not s:
            return None
        try:
            v = float(s.replace(",", ""))
            return v if v != 0 else None
        except (ValueError, TypeError):
            return None

    def pdate(s):
        s = s.replace("-", "/")
        try:
            return dt.strptime(s, "%m/%d").date().replace(year=2026)
        except ValueError:
            return None

    sup_objs = {}
    for norm_name in set(SRC_MAP.values()):
        s = Supplier(name=norm_name)
        if norm_name == "Rollover (Blends)":
            s.notes = "Auto-created for unattributed rollover runs"
        db.session.add(s)
        db.session.flush()
        sup_objs[norm_name] = s

    purch_objs = {}
    for name, sup in sup_objs.items():
        p = Purchase(supplier_id=sup.id, purchase_date=date(2026, 1, 13),
                     status="complete", stated_weight_lbs=0)
        db.session.add(p)
        db.session.flush()
        purch_objs[name] = p

    lot_cache = {}
    count = 0
    for (dt_s, bio_house, butane, solvent, strain, source, price,
         lbs_s, grams_s, w_hte, w_thca, d_hte, d_thca) in RAW:

        run_date = pdate(dt_s)
        lbs = pf(lbs_s)
        if not run_date or not lbs:
            continue

        sup_name = SRC_MAP.get(source, "Rollover (Blends)")
        is_rollover = "Rollover" in source or "Rollover" in strain

        cache_key = (sup_name, strain)
        if cache_key not in lot_cache:
            lot = PurchaseLot(purchase_id=purch_objs[sup_name].id,
                              strain_name=strain, weight_lbs=0, remaining_weight_lbs=0)
            db.session.add(lot)
            db.session.flush()
            lot_cache[cache_key] = lot
        lot = lot_cache[cache_key]
        lot.weight_lbs += lbs
        purch_objs[sup_name].stated_weight_lbs += lbs

        grams = pf(grams_s) or (lbs * 454)
        dry_hte = pf(d_hte)
        dry_thca = pf(d_thca)
        dry_total = (dry_hte or 0) + (dry_thca or 0)

        run = Run(
            run_date=run_date, reactor_number=1, is_rollover=is_rollover,
            bio_in_house_lbs=pf(bio_house), bio_in_reactor_lbs=lbs,
            grams_ran=grams, butane_in_house_lbs=pf(butane),
            solvent_ratio=pf(solvent),
            wet_hte_g=pf(w_hte), wet_thca_g=pf(w_thca),
            dry_hte_g=dry_hte, dry_thca_g=dry_thca,
            overall_yield_pct=(dry_total / grams * 100) if grams and dry_total else None,
            thca_yield_pct=(dry_thca / grams * 100) if grams and dry_thca else None,
            hte_yield_pct=(dry_hte / grams * 100) if grams and dry_hte else None,
            run_type="standard",
            notes=f"Imported from Google Sheet. Source: {source}",
        )
        db.session.add(run)
        db.session.flush()

        inp = RunInput(run_id=run.id, lot_id=lot.id, weight_lbs=lbs)
        db.session.add(inp)

        p_val = pf(price)
        if p_val and not purch_objs[sup_name].price_per_lb:
            purch_objs[sup_name].price_per_lb = p_val

        run.calculate_cost()
        count += 1

    db.session.commit()
    print(f"  Seeded {count} historical runs across {len(sup_objs)} suppliers.")


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
