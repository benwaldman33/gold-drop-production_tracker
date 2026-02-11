"""Database models for Gold Drop Biomass Tracking System."""
import uuid
from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


def gen_uuid():
    return str(uuid.uuid4())


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="viewer")  # super_admin, user, viewer
    is_active_user = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return self.id

    @property
    def is_super_admin(self):
        return self.role == "super_admin"

    @property
    def can_edit(self):
        return self.role in ("super_admin", "user")


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
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    purchases = db.relationship("Purchase", backref="supplier", lazy="dynamic")

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
            cutoff = datetime.utcnow().date() - __import__('datetime').timedelta(days=days)
            query = query.filter(Run.run_date >= cutoff)
        result = query.scalar()
        return result if result else 0


class Purchase(db.Model):
    __tablename__ = "purchases"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    supplier_id = db.Column(db.String(36), db.ForeignKey("suppliers.id"), nullable=False)
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
    clean_or_dirty = db.Column(db.String(10))
    indoor_outdoor = db.Column(db.String(20))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    lots = db.relationship("PurchaseLot", backref="purchase", lazy="dynamic", cascade="all, delete-orphan")

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
    potency_pct = db.Column(db.Float)
    micro_pot_test = db.Column(db.String(100))
    milled = db.Column(db.Boolean, default=False)
    location = db.Column(db.String(200))
    notes = db.Column(db.Text)

    run_inputs = db.relationship("RunInput", backref="lot", lazy="dynamic")

    @property
    def supplier_name(self):
        return self.purchase.supplier_name if self.purchase else "Unknown"

    @property
    def display_label(self):
        return f"{self.strain_name} ({self.supplier_name}) - {self.remaining_weight_lbs:.0f} lbs remaining"


class Run(db.Model):
    __tablename__ = "runs"
    id = db.Column(db.String(36), primary_key=True, default=gen_uuid)
    run_date = db.Column(db.Date, nullable=False)
    reactor_number = db.Column(db.Integer, nullable=False)
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
    decarb_sample_done = db.Column(db.Boolean, default=False)
    fuel_consumption = db.Column(db.Float)
    run_type = db.Column(db.String(20), default="standard")  # standard, kief, ld
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.String(36), db.ForeignKey("users.id"))

    inputs = db.relationship("RunInput", backref="run", lazy="dynamic", cascade="all, delete-orphan")

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
        """Calculate cost per gram based on input lot costs."""
        total_cost = 0
        for inp in self.inputs:
            if inp.lot and inp.lot.purchase and inp.lot.purchase.price_per_lb:
                total_cost += inp.weight_lbs * inp.lot.purchase.price_per_lb
        dry_total = (self.dry_hte_g or 0) + (self.dry_thca_g or 0)
        if dry_total > 0 and total_cost > 0:
            self.cost_per_gram_combined = total_cost / dry_total
        else:
            self.cost_per_gram_combined = None

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
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    @staticmethod
    def get(key, default=None):
        s = SystemSetting.query.get(key)
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
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.String(36), db.ForeignKey("users.id"))
    action = db.Column(db.String(20), nullable=False)  # create, update, delete
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.String(36), nullable=False)
    details = db.Column(db.Text)

    user = db.relationship("User", backref="audit_logs")
