"""Database models for Gold Drop Biomass Tracking System."""
import json
import uuid
from datetime import datetime, date, timezone
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from sqlalchemy import event
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def utc_now():
    return datetime.now(timezone.utc)


def coerce_utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def gen_uuid():
    return str(uuid.uuid4())


def gen_tracking_id(prefix: str = "LOT") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="viewer")  # super_admin, user, super_buyer, viewer
    is_active_user = db.Column(db.Boolean, default=True)
    is_slack_importer = db.Column(db.Boolean, default=False)
    is_purchase_approver = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=utc_now)

    def set_password(self, password):
        # pbkdf2 works on all Python builds; Werkzeug's default (scrypt) needs hashlib.scrypt (OpenSSL).
        self.password_hash = generate_password_hash(password, method="pbkdf2:sha256")

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return self.id

    @property
    def is_active(self):
        """Flask-Login integration: disabled users cannot be authenticated."""
        return bool(self.is_active_user)

    @property
    def is_super_admin(self):
        return self.role == "super_admin"

    @property
    def is_super_buyer(self):
        return self.role == "super_buyer"

    @property
    def can_edit(self):
        return self.role in ("super_admin", "user")

    @property
    def can_edit_purchases(self):
        """Create/edit purchases, lots, and field approvals without full app edit access."""
        return self.can_edit or self.is_super_buyer

    @property
    def can_approve_field_purchases(self):
        return self.is_super_admin or self.is_super_buyer

    @property
    def can_slack_import(self):
        return self.is_super_admin or bool(self.is_slack_importer)

    @property
    def can_approve_purchase(self):
        """Super Admin always; otherwise explicit is_purchase_approver flag (PRD: Super-Buyer, COO, etc.)."""
        return self.is_super_admin or bool(getattr(self, "is_purchase_approver", False))


class ApiClient(db.Model):
    __tablename__ = "api_clients"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False)
    token_hash = db.Column(db.String(128), nullable=False, unique=True, index=True)
    scopes_json = db.Column(db.Text, nullable=False, default="[]")
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    last_used_at = db.Column(db.DateTime)
    last_used_scope = db.Column(db.String(64))
    last_used_endpoint = db.Column(db.String(255))

    @property
    def scopes(self):
        try:
            value = json.loads(self.scopes_json or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        return value if isinstance(value, list) else []

    def set_scopes(self, scopes):
        normalized = sorted({str(scope).strip() for scope in (scopes or []) if str(scope).strip()})
        self.scopes_json = json.dumps(normalized)


class ApiClientRequestLog(db.Model):
    __tablename__ = "api_client_request_logs"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    api_client_id = db.Column(db.String(36), db.ForeignKey("api_clients.id"), nullable=False, index=True)
    request_path = db.Column(db.String(255), nullable=False)
    request_method = db.Column(db.String(16), nullable=False, default="GET")
    scope_used = db.Column(db.String(64), nullable=False)
    status_code = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    api_client = db.relationship("ApiClient", backref=db.backref("request_logs", lazy="dynamic", cascade="all, delete-orphan"))


class RemoteSite(db.Model):
    __tablename__ = "remote_sites"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False)
    base_url = db.Column(db.String(255), nullable=False, unique=True)
    api_token = db.Column(db.Text)
    site_code = db.Column(db.String(24))
    site_name = db.Column(db.String(120))
    site_region = db.Column(db.String(80))
    site_environment = db.Column(db.String(32))
    is_active = db.Column(db.Boolean, nullable=False, default=True)
    notes = db.Column(db.Text)
    last_pull_started_at = db.Column(db.DateTime)
    last_pull_finished_at = db.Column(db.DateTime)
    last_pull_status = db.Column(db.String(32))
    last_pull_error = db.Column(db.Text)
    last_site_payload_json = db.Column(db.Text)
    last_manifest_payload_json = db.Column(db.Text)
    last_dashboard_payload_json = db.Column(db.Text)
    last_inventory_payload_json = db.Column(db.Text)
    last_exceptions_payload_json = db.Column(db.Text)
    last_slack_payload_json = db.Column(db.Text)
    last_suppliers_payload_json = db.Column(db.Text)
    last_strains_payload_json = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now, nullable=False)

    pulls = db.relationship(
        "RemoteSitePull",
        backref="remote_site",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    def payload(self, attr_name: str):
        raw_value = getattr(self, attr_name, None)
        if not raw_value:
            return None
        try:
            return json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def set_payload(self, attr_name: str, value):
        setattr(self, attr_name, json.dumps(value or {}))

    @property
    def masked_token(self) -> str:
        token = (self.api_token or "").strip()
        if not token:
            return ""
        if len(token) <= 8:
            return "*" * len(token)
        return f"{token[:4]}...{token[-4:]}"


class RemoteSitePull(db.Model):
    __tablename__ = "remote_site_pulls"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    remote_site_id = db.Column(db.String(36), db.ForeignKey("remote_sites.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    finished_at = db.Column(db.DateTime)
    status = db.Column(db.String(32), nullable=False, default="started")
    error_message = db.Column(db.Text)
    site_payload_json = db.Column(db.Text)
    manifest_payload_json = db.Column(db.Text)
    dashboard_payload_json = db.Column(db.Text)
    inventory_payload_json = db.Column(db.Text)
    exceptions_payload_json = db.Column(db.Text)
    slack_payload_json = db.Column(db.Text)
    suppliers_payload_json = db.Column(db.Text)
    strains_payload_json = db.Column(db.Text)

    def payload(self, attr_name: str):
        raw_value = getattr(self, attr_name, None)
        if not raw_value:
            return None
        try:
            return json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return None

    def set_payload(self, attr_name: str, value):
        setattr(self, attr_name, json.dumps(value or {}))


class Supplier(db.Model):
    __tablename__ = "suppliers"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(200), nullable=False)
    contact_name = db.Column(db.String(200))
    contact_phone = db.Column(db.String(50))
    contact_email = db.Column(db.String(200))
    location = db.Column(db.String(200))
    notes = db.Column(db.Text)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    merged_into_supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"))
    merged_at = db.Column(db.DateTime)
    merged_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    merge_notes = db.Column(db.Text)

    purchases = db.relationship("Purchase", backref="supplier", lazy="dynamic")
    biomass_availabilities = db.relationship(
        "BiomassAvailability",
        backref="supplier",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    merged_into_supplier = db.relationship(
        "Supplier",
        remote_side=[id],
        foreign_keys=[merged_into_supplier_id],
        post_update=True,
    )
    merged_by_user = db.relationship("User", foreign_keys=[merged_by_user_id])

    def avg_yield(self, days=None):
        """Calculate average overall yield for this supplier."""
        from sqlalchemy import func
        query = db.session.query(func.avg(Run.overall_yield_pct)).join(
            RunInput, Run.id == RunInput.run_id
        ).join(
            PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(
            Purchase, PurchaseLot.purchase_id == Purchase.id
        ).filter(
            Purchase.supplier_id == self.id,
            Run.is_rollover == False,
            Run.overall_yield_pct.isnot(None)
        )
        if days:
            cutoff = utc_now().date() - __import__("datetime").timedelta(days=days)
            query = query.filter(Run.run_date >= cutoff)
        result = query.scalar()
        return result if result else 0


class Purchase(db.Model):
    __tablename__ = "purchases"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    batch_id = db.Column(db.String(80), unique=True, index=True)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
    created_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    delivery_recorded_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    purchase_date = db.Column(db.Date, nullable=False)
    delivery_date = db.Column(db.Date)
    status = db.Column(db.String(20), nullable=False, default="ordered")
    stated_weight_lbs = db.Column(db.Float, nullable=False)
    actual_weight_lbs = db.Column(db.Float)
    stated_potency_pct = db.Column(db.Float)
    tested_potency_pct = db.Column(db.Float)
    price_per_lb = db.Column(db.Float)
    total_cost = db.Column(db.Float)
    true_up_amount = db.Column(db.Float)
    true_up_status = db.Column(db.String(20))
    harvest_date = db.Column(db.Date)
    storage_note = db.Column(db.Text)
    license_info = db.Column(db.Text)
    queue_placement = db.Column(db.String(20))  # aggregate, indoor, outdoor
    coa_status_text = db.Column(db.Text)
    clean_or_dirty = db.Column(db.String(10))
    indoor_outdoor = db.Column(db.String(20))
    notes = db.Column(db.Text)
    testing_notes = db.Column(db.Text)
    delivery_notes = db.Column(db.Text)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    # Purchase approval gate: material must not be consumed until approved
    purchase_approved_at = db.Column(db.DateTime)
    purchase_approved_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    purchase_approved_by = db.relationship("User", foreign_keys=[purchase_approved_by_user_id])
    created_by_user = db.relationship("User", foreign_keys=[created_by_user_id])
    delivery_recorded_by = db.relationship("User", foreign_keys=[delivery_recorded_by_user_id])

    # Biomass pipeline fields (merged from BiomassAvailability)
    availability_date = db.Column(db.Date)  # when biomass first became available from supplier
    declared_weight_lbs = db.Column(db.Float)  # initial supplier declaration of weight
    declared_price_per_lb = db.Column(db.Float)  # initial price quote
    testing_timing = db.Column(db.String(20))  # before_delivery, after_delivery
    testing_status = db.Column(db.String(20))  # pending, completed, not_needed
    testing_date = db.Column(db.Date)
    field_photo_paths_json = db.Column(db.Text)  # JSON array of field intake photos

    lots = db.relationship("PurchaseLot", backref="purchase", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def is_approved(self):
        return self.purchase_approved_at is not None

    @property
    def supplier_name(self):
        return self.supplier.name if self.supplier else "Unknown"

    @property
    def is_merged(self):
        return self.merged_into_supplier_id is not None


class BiomassAvailability(db.Model):
    """
    Tracks supplier biomass availability through a simple pipeline:
    declared -> testing -> committed -> delivered (or cancelled).
    """
    __tablename__ = "biomass_availabilities"

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
    # One-to-one link to a Purchase (when batch is committed/delivered/cancelled)
    purchase_id = db.Column(db.String(36), db.ForeignKey("purchases.id"), unique=True)
    purchase = db.relationship(
        "Purchase",
        backref=db.backref("biomass_availability", uselist=False),
        foreign_keys=[purchase_id],
    )

    # Step 1: Declaration of availability
    availability_date = db.Column(db.Date, nullable=False)
    strain_name = db.Column(db.String(200))
    declared_weight_lbs = db.Column(db.Float, nullable=False, default=0.0)
    declared_price_per_lb = db.Column(db.Float)
    estimated_potency_pct = db.Column(db.Float)

    # Step 2: Testing (sometimes before delivery, sometimes after)
    testing_timing = db.Column(db.String(20), default="before_delivery")  # before_delivery, after_delivery
    testing_status = db.Column(db.String(20), default="pending")  # pending, completed, not_needed
    testing_date = db.Column(db.Date)
    tested_potency_pct = db.Column(db.Float)

    # Step 3: Commitment to purchase
    committed_on = db.Column(db.Date)
    committed_delivery_date = db.Column(db.Date)
    committed_weight_lbs = db.Column(db.Float)
    committed_price_per_lb = db.Column(db.Float)

    # Overall stage
    stage = db.Column(db.String(20), nullable=False, default="declared")  # declared, testing, committed, delivered, cancelled

    # Optional field-intake photo paths (JSON array of relative static paths)
    field_photo_paths_json = db.Column(db.Text)

    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    purchase_approved_at = db.Column(db.DateTime)
    purchase_approved_by_user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    purchase_approved_by = db.relationship(
        "User",
        foreign_keys=[purchase_approved_by_user_id],
    )

    deleted_at = db.Column(db.DateTime)

    @property
    def supplier_name(self):
        return self.supplier.name if self.supplier else "Unknown"


class PurchaseLot(db.Model):
    __tablename__ = "purchase_lots"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    purchase_id = db.Column(db.String(36), db.ForeignKey("purchases.id"), nullable=False)
    strain_name = db.Column(db.String(200), nullable=False)
    weight_lbs = db.Column(db.Float, nullable=False)
    remaining_weight_lbs = db.Column(db.Float, nullable=False)
    tracking_id = db.Column(db.String(24))
    barcode_value = db.Column(db.String(120))
    qr_value = db.Column(db.String(255))
    label_generated_at = db.Column(db.DateTime)
    label_version = db.Column(db.Integer)
    potency_pct = db.Column(db.Float)
    micro_pot_test = db.Column(db.String(100))
    milled = db.Column(db.Boolean, default=False)
    floor_state = db.Column(db.String(40), default="inventory")
    location = db.Column(db.String(200))
    notes = db.Column(db.Text)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.String(36), db.ForeignKey("users.id"))

    run_inputs = db.relationship("RunInput", backref="lot", lazy="dynamic")
    scan_events = db.relationship("LotScanEvent", backref="lot", lazy="dynamic", cascade="all, delete-orphan")
    extraction_charges = db.relationship("ExtractionCharge", backref="lot", lazy="dynamic")

    @property
    def supplier_name(self):
        return self.purchase.supplier_name if self.purchase else "Unknown"

    @property
    def allocated_weight_lbs(self):
        return max(0.0, float(self.weight_lbs or 0) - float(self.remaining_weight_lbs or 0))

    @property
    def remaining_pct(self):
        total = float(self.weight_lbs or 0)
        if total <= 0:
            return 0.0
        return max(0.0, min(100.0, (float(self.remaining_weight_lbs or 0) / total) * 100.0))

    @property
    def display_label(self):
        return f"{self.strain_name} ({self.supplier_name}) - {self.remaining_weight_lbs:.0f} lbs remaining"


class Run(db.Model):
    __tablename__ = "runs"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    run_date = db.Column(db.Date, nullable=False)
    reactor_number = db.Column(db.Integer, nullable=False)
    # Which upstream load reactor(s) this biomass came from (e.g. A, B, A+B); not the processing vessel # above.
    load_source_reactors = db.Column(db.String(120))
    is_rollover = db.Column(db.Boolean, default=False)
    bio_in_house_lbs = db.Column(db.Float)
    bio_in_reactor_lbs = db.Column(db.Float)
    grams_ran = db.Column(db.Float)
    butane_in_house_lbs = db.Column(db.Float)
    solvent_ratio = db.Column(db.Float)
    system_temp = db.Column(db.Float)
    wet_hte_g = db.Column(db.Float)
    wet_thca_g = db.Column(db.Float)
    dry_hte_g = db.Column(db.Float)
    dry_thca_g = db.Column(db.Float)
    overall_yield_pct = db.Column(db.Float)
    thca_yield_pct = db.Column(db.Float)
    hte_yield_pct = db.Column(db.Float)
    cost_per_gram_combined = db.Column(db.Float)
    cost_per_gram_thca = db.Column(db.Float)
    cost_per_gram_hte = db.Column(db.Float)
    decarb_sample_done = db.Column(db.Boolean, default=False)
    fuel_consumption = db.Column(db.Float)
    run_type = db.Column(db.String(20), default="standard")  # standard, kief, ld
    # After dry HTE is separated from THCA: lab testing → clean (menu) or dirty (Prescott strip) → terp accounting.
    hte_pipeline_stage = db.Column(db.String(40))  # awaiting_lab, lab_clean, lab_dirty_queued_strip, terp_stripped
    hte_lab_result_paths_json = db.Column(db.Text)  # JSON array; COA / lab result images or PDFs under static/
    hte_terpenes_recovered_g = db.Column(db.Float)
    hte_distillate_retail_g = db.Column(db.Float)
    notes = db.Column(db.Text)
    deleted_at = db.Column(db.DateTime)
    deleted_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utc_now)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    slack_channel_id = db.Column(db.String(32))
    slack_message_ts = db.Column(db.String(32))
    slack_import_applied_at = db.Column(db.DateTime)

    inputs = db.relationship("RunInput", backref="run", lazy="dynamic", cascade="all, delete-orphan")
    extraction_charges = db.relationship("ExtractionCharge", backref="run", lazy="dynamic")

    def calculate_yields(self):
        """Recalculate all yield fields."""
        if self.bio_in_reactor_lbs:
            self.grams_ran = self.bio_in_reactor_lbs * 454
        if self.grams_ran and self.grams_ran > 0:
            dry_total = (self.dry_hte_g or 0) + (self.dry_thca_g or 0)
            self.overall_yield_pct = (dry_total / self.grams_ran) * 100 if dry_total else 0
            self.thca_yield_pct = ((self.dry_thca_g or 0) / self.grams_ran) * 100
            self.hte_yield_pct = ((self.dry_hte_g or 0) / self.grams_ran) * 100

    def calculate_cost(self):
        """
        Calculate cost per gram for this run.

        Components:
        - Biomass input cost: sum(input_lbs * purchase.price_per_lb)
        - Operational costs (Cost Entries): allocated evenly across total dry grams produced
          within each CostEntry date range, then added as a flat $/g.

        Product allocation:
        - Combined $/g is always total run dollars ÷ total dry grams.
        - THCA/HTE $/g depends on SystemSetting.cost_allocation_method:
          - per_gram_uniform: THCA and HTE match combined $/g
          - split_50_50: split dollars 50/50 between THCA and HTE when both exist
          - custom_split: split dollars by configured THCA % (remainder to HTE)
        """
        from sqlalchemy import func

        # ── Biomass input cost (from purchase pricing) ────────────────────────
        biomass_cost = 0.0
        for inp in self.inputs:
            if inp.lot and inp.lot.purchase and inp.lot.purchase.price_per_lb:
                biomass_cost += (inp.weight_lbs or 0) * inp.lot.purchase.price_per_lb

        dry_thca = float(self.dry_thca_g or 0)
        dry_hte = float(self.dry_hte_g or 0)
        dry_total = dry_thca + dry_hte

        if dry_total <= 0:
            self.cost_per_gram_combined = None
            self.cost_per_gram_thca = None
            self.cost_per_gram_hte = None
            return

        # ── Operational costs allocation ──────────────────────────────────────
        op_rate = 0.0
        if self.run_date:
            entries = CostEntry.query.filter(
                CostEntry.start_date <= self.run_date,
                CostEntry.end_date >= self.run_date,
            ).all()

            dry_expr = func.coalesce(Run.dry_thca_g, 0) + func.coalesce(Run.dry_hte_g, 0)
            for e in entries:
                total_grams_in_period = db.session.query(func.sum(dry_expr)).filter(
                    Run.run_date >= e.start_date,
                    Run.run_date <= e.end_date,
                    Run.deleted_at.is_(None),
                ).scalar() or 0
                if total_grams_in_period and total_grams_in_period > 0:
                    op_rate += (e.total_cost or 0) / float(total_grams_in_period)

        total_cost_for_run = biomass_cost + (op_rate * dry_total)
        self.cost_per_gram_combined = (total_cost_for_run / dry_total) if dry_total > 0 else None

        method = (SystemSetting.get("cost_allocation_method", "per_gram_uniform") or "per_gram_uniform").strip()

        if method == "split_50_50":
            if dry_thca > 0 and dry_hte > 0:
                self.cost_per_gram_thca = (total_cost_for_run * 0.5) / dry_thca
                self.cost_per_gram_hte = (total_cost_for_run * 0.5) / dry_hte
            elif dry_thca > 0:
                self.cost_per_gram_thca = total_cost_for_run / dry_thca
                self.cost_per_gram_hte = None
            elif dry_hte > 0:
                self.cost_per_gram_thca = None
                self.cost_per_gram_hte = total_cost_for_run / dry_hte
            else:
                self.cost_per_gram_thca = None
                self.cost_per_gram_hte = None
        elif method == "custom_split":
            pct = SystemSetting.get_float("cost_allocation_thca_pct", 50.0)
            try:
                pct = float(pct)
            except (TypeError, ValueError):
                pct = 50.0
            pct = max(0.0, min(100.0, pct))
            thca_share = pct / 100.0
            hte_share = 1.0 - thca_share

            if dry_thca > 0 and dry_hte > 0:
                self.cost_per_gram_thca = (total_cost_for_run * thca_share) / dry_thca
                self.cost_per_gram_hte = (total_cost_for_run * hte_share) / dry_hte
            elif dry_thca > 0:
                self.cost_per_gram_thca = total_cost_for_run / dry_thca
                self.cost_per_gram_hte = None
            elif dry_hte > 0:
                self.cost_per_gram_thca = None
                self.cost_per_gram_hte = total_cost_for_run / dry_hte
            else:
                self.cost_per_gram_thca = None
                self.cost_per_gram_hte = None
        else:
            rate = self.cost_per_gram_combined
            self.cost_per_gram_thca = (rate if dry_thca > 0 else None)
            self.cost_per_gram_hte = (rate if dry_hte > 0 else None)

    @property
    def source_display(self):
        """Get display string for source lots."""
        sources = []
        for inp in self.inputs:
            if inp.lot:
                sources.append(f"{inp.lot.strain_name} ({inp.weight_lbs:.0f} lbs)")
        return ", ".join(sources) if sources else "Unlinked"


class RunInput(db.Model):
    __tablename__ = "run_inputs"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    run_id = db.Column(db.String(36), db.ForeignKey("runs.id"), nullable=False)
    lot_id = db.Column(db.String(36), db.ForeignKey("purchase_lots.id"), nullable=False)
    weight_lbs = db.Column(db.Float, nullable=False)
    allocation_source = db.Column(db.String(20), default="manual")
    allocation_confidence = db.Column(db.Float)
    allocation_notes = db.Column(db.Text)
    slack_ingested_message_id = db.Column(db.String(36))


class LotScanEvent(db.Model):
    __tablename__ = "lot_scan_events"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    lot_id = db.Column(db.String(36), db.ForeignKey("purchase_lots.id"), nullable=False, index=True)
    tracking_id_snapshot = db.Column(db.String(24), nullable=False)
    action = db.Column(db.String(40), nullable=False, default="scan_open")
    context_json = db.Column(db.Text)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utc_now, nullable=False)

    user = db.relationship("User")

    @property
    def context(self):
        try:
            value = json.loads(self.context_json or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    def set_context(self, context):
        self.context_json = json.dumps(context or {})


class ExtractionCharge(db.Model):
    __tablename__ = "extraction_charges"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    purchase_lot_id = db.Column(db.String(36), db.ForeignKey("purchase_lots.id"), nullable=False, index=True)
    run_id = db.Column(db.String(36), db.ForeignKey("runs.id"), index=True)
    weight_capture_id = db.Column(db.String(36), db.ForeignKey("weight_captures.id"))
    lot_scan_event_id = db.Column(db.String(36), db.ForeignKey("lot_scan_events.id"))
    charged_weight_lbs = db.Column(db.Float, nullable=False)
    reactor_number = db.Column(db.Integer, nullable=False)
    charged_at = db.Column(db.DateTime, nullable=False, default=utc_now)
    source_mode = db.Column(db.String(20), nullable=False, default="main_app")
    status = db.Column(db.String(20), nullable=False, default="pending")
    notes = db.Column(db.Text)
    slack_ingested_message_id = db.Column(db.String(36))
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now)

    weight_capture = db.relationship("WeightCapture")
    lot_scan_event = db.relationship("LotScanEvent")
    creator = db.relationship("User")


class ScaleDevice(db.Model):
    __tablename__ = "scale_devices"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    name = db.Column(db.String(120), nullable=False)
    location = db.Column(db.String(120))
    make_model = db.Column(db.String(200))
    interface_type = db.Column(db.String(40))  # rs232, usb_serial, tcp, modbus_rtu, modbus_tcp
    protocol_type = db.Column(db.String(40))  # vendor protocol / parser key
    connection_target = db.Column(db.String(200))
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)


class WeightCapture(db.Model):
    __tablename__ = "weight_captures"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    capture_type = db.Column(db.String(40), nullable=False, default="manual")  # intake, allocation, output, adjustment
    source_mode = db.Column(db.String(20), nullable=False, default="manual")  # manual, device
    measured_weight = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(16), nullable=False, default="lb")
    gross_weight = db.Column(db.Float)
    tare_weight = db.Column(db.Float)
    net_weight = db.Column(db.Float)
    is_stable = db.Column(db.Boolean)
    accepted_at = db.Column(db.DateTime)
    rejected_at = db.Column(db.DateTime)
    raw_payload = db.Column(db.Text)
    notes = db.Column(db.Text)
    device_id = db.Column(db.String(36), db.ForeignKey("scale_devices.id"))
    purchase_id = db.Column(db.String(36), db.ForeignKey("purchases.id"))
    purchase_lot_id = db.Column(db.String(36), db.ForeignKey("purchase_lots.id"))
    run_id = db.Column(db.String(36), db.ForeignKey("runs.id"))
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=utc_now)

    device = db.relationship("ScaleDevice")
    purchase = db.relationship("Purchase")
    purchase_lot = db.relationship("PurchaseLot")
    run = db.relationship("Run")


@event.listens_for(PurchaseLot, "before_insert")
def _purchase_lot_before_insert(_mapper, _connection, target):
    if not target.tracking_id:
        target.tracking_id = gen_tracking_id("LOT")
    if not target.barcode_value:
        target.barcode_value = target.tracking_id
    if not target.qr_value:
        target.qr_value = f"/scan/lot/{target.tracking_id}"
    if target.label_generated_at is None:
        target.label_generated_at = utc_now()
    if target.label_version is None:
        target.label_version = 1


class KpiTarget(db.Model):
    __tablename__ = "kpi_targets"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    kpi_name = db.Column(db.String(100), unique=True, nullable=False)
    display_name = db.Column(db.String(200), nullable=False)
    target_value = db.Column(db.Float, nullable=False)
    green_threshold = db.Column(db.Float, nullable=False)
    yellow_threshold = db.Column(db.Float, nullable=False)
    direction = db.Column(db.String(20), nullable=False)  # higher_is_better, lower_is_better
    unit = db.Column(db.String(20))
    effective_date = db.Column(db.Date, default=date.today)
    updated_by = db.Column(db.String(36), db.ForeignKey("users.id"))

    def evaluate(self, actual_value):
        """Return 'green', 'yellow', or 'red' based on actual vs thresholds."""
        if actual_value is None:
            return "gray"
        if self.direction == "higher_is_better":
            if actual_value >= self.green_threshold:
                return "green"
            elif actual_value >= self.yellow_threshold:
                return "yellow"
            else:
                return "red"
        else:  # lower_is_better
            if actual_value <= self.green_threshold:
                return "green"
            elif actual_value <= self.yellow_threshold:
                return "yellow"
            else:
                return "red"


class SystemSetting(db.Model):
    __tablename__ = "system_settings"
    key = db.Column(db.String(100), primary_key=True)
    value = db.Column(db.String(500), nullable=False)
    description = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=utc_now, onupdate=utc_now)

    @staticmethod
    def get(key, default=None):
        s = db.session.get(SystemSetting, key)
        return s.value if s else default

    @staticmethod
    def get_float(key, default=0.0):
        val = SystemSetting.get(key)
        try:
            return float(val)
        except (TypeError, ValueError):
            return default


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    timestamp = db.Column(db.DateTime, default=utc_now)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    action = db.Column(db.String(20), nullable=False)  # create, update, delete
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(36), nullable=False)
    details = db.Column(db.Text)

    user = db.relationship("User", backref="audit_logs")


class CostEntry(db.Model):
    """Track operational costs: solvents, personnel, overhead."""
    __tablename__ = "cost_entries"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    cost_type = db.Column(db.String(30), nullable=False)  # solvent, personnel, overhead
    name = db.Column(db.String(200), nullable=False)
    unit_cost = db.Column(db.Float)
    unit = db.Column(db.String(50))
    quantity = db.Column(db.Float)
    total_cost = db.Column(db.Float, nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=utc_now)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))


class FieldAccessToken(db.Model):
    """
    Revocable access token for field/mobile data entry without site login.

    The plain token is only shown at creation time; we store only a SHA-256 hash.
    """
    __tablename__ = "field_access_tokens"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    label = db.Column(db.String(200), nullable=False)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    expires_at = db.Column(db.DateTime)
    revoked_at = db.Column(db.DateTime)
    last_used_at = db.Column(db.DateTime)

    @property
    def is_active(self):
        if self.revoked_at is not None:
            return False
        expires_at = coerce_utc(self.expires_at)
        if expires_at is not None and utc_now() > expires_at:
            return False
        return True


class FieldPurchaseSubmission(db.Model):
    """
    Field-submitted potential purchase data.

    Submissions require admin approval before creating a real Purchase record.
    """
    __tablename__ = "field_purchase_submissions"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    submitted_at = db.Column(db.DateTime, default=utc_now, nullable=False)
    source_token_id = db.Column(db.String(36), db.ForeignKey("field_access_tokens.id"))
    source_token = db.relationship("FieldAccessToken", foreign_keys=[source_token_id])

    # What the field user provided
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])
    purchase_date = db.Column(db.Date, nullable=False)
    delivery_date = db.Column(db.Date)
    harvest_date = db.Column(db.Date)
    estimated_potency_pct = db.Column(db.Float)
    price_per_lb = db.Column(db.Float)
    storage_note = db.Column(db.Text)
    license_info = db.Column(db.Text)
    queue_placement = db.Column(db.String(20))  # aggregate, indoor, outdoor
    coa_status_text = db.Column(db.Text)
    notes = db.Column(db.Text)

    # Lot lines as JSON: [{"strain": "...", "weight_lbs": 123.4}, ...]
    lots_json = db.Column(db.Text)
    # Optional field photos (JSON array of relative static paths)
    photos_json = db.Column(db.Text)
    # Optional categorized photos
    supplier_photos_json = db.Column(db.Text)
    biomass_photos_json = db.Column(db.Text)
    coa_photos_json = db.Column(db.Text)

    # Review / approval
    status = db.Column(db.String(20), nullable=False, default="pending")  # pending, approved, rejected
    reviewed_at = db.Column(db.DateTime)
    reviewed_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    review_notes = db.Column(db.Text)

    approved_purchase_id = db.Column(db.String(36), db.ForeignKey("purchases.id"))
    approved_purchase = db.relationship("Purchase", foreign_keys=[approved_purchase_id])


class LabTest(db.Model):
    __tablename__ = "lab_tests"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
    purchase_id = db.Column(db.String(36), db.ForeignKey("purchases.id"))
    test_date = db.Column(db.Date, nullable=False)
    test_type = db.Column(db.String(50), nullable=False, default="coa")
    status_text = db.Column(db.Text)
    potency_pct = db.Column(db.Float)
    notes = db.Column(db.Text)
    result_paths_json = db.Column(db.Text)  # JSON array of files under static/uploads/labs
    created_at = db.Column(db.DateTime, default=utc_now)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))

    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])
    purchase = db.relationship("Purchase", foreign_keys=[purchase_id])


class SupplierAttachment(db.Model):
    __tablename__ = "supplier_attachments"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
    document_type = db.Column(db.String(50), nullable=False, default="coa")
    title = db.Column(db.String(200))
    file_path = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=utc_now)
    uploaded_by = db.Column(db.String(36), db.ForeignKey("users.id"))

    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])


class PhotoAsset(db.Model):
    __tablename__ = "photo_assets"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"))
    purchase_id = db.Column(db.String(36), db.ForeignKey("purchases.id"))
    submission_id = db.Column(db.String(36), db.ForeignKey("field_purchase_submissions.id"))
    photo_context = db.Column(db.String(32))
    source_type = db.Column(db.String(50), nullable=False, default="manual")  # field_submission, supplier_attachment, lab_test, purchase_upload
    category = db.Column(db.String(50), nullable=False, default="other")  # supplier_license, biomass, coa, lab_result, supplier_doc
    title = db.Column(db.String(200))
    tags = db.Column(db.String(500))  # comma-separated searchable tags
    file_path = db.Column(db.String(500), nullable=False)
    uploaded_at = db.Column(db.DateTime, default=utc_now)
    uploaded_by = db.Column(db.String(36), db.ForeignKey("users.id"))

    supplier = db.relationship("Supplier", foreign_keys=[supplier_id])
    purchase = db.relationship("Purchase", foreign_keys=[purchase_id])


class SlackIngestedMessage(db.Model):
    """
    One row per Slack channel message ingested via conversations.history (deduped by channel + ts).
    """
    __tablename__ = "slack_ingested_messages"
    __table_args__ = (db.UniqueConstraint("channel_id", "message_ts", name="uq_slack_channel_ts"),)

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    channel_id = db.Column(db.String(32), nullable=False)
    message_ts = db.Column(db.String(32), nullable=False)
    slack_user_id = db.Column(db.String(32))
    raw_text = db.Column(db.Text)
    message_kind = db.Column(db.String(40))  # yield_report, production_log, unknown
    derived_json = db.Column(db.Text)
    ingested_at = db.Column(db.DateTime, default=utc_now)
    ingested_by = db.Column(db.String(36), db.ForeignKey("users.id"))
    # User dismissed from triage list (noise / will never promote); not the same as run-linked "imported".
    hidden_from_imports = db.Column(db.Boolean, default=False, nullable=False)


class SlackChannelSyncConfig(db.Model):
    """Up to six Slack channels for history sync, each with its own cursor (last message ts)."""
    __tablename__ = "slack_channel_sync_configs"
    __table_args__ = (db.UniqueConstraint("slot_index", name="uq_slack_sync_slot"),)

    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    slot_index = db.Column(db.Integer, nullable=False)
    channel_hint = db.Column(db.String(200), nullable=False, default="")
    resolved_channel_id = db.Column(db.String(32))
    last_watermark_ts = db.Column(db.String(32))
