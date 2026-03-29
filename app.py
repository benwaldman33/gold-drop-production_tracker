"""Gold Drop Biomass Inventory & Extraction Tracking System."""
import os
import csv
import io
import json
import re
import hashlib
import hmac
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, date, timedelta
from functools import wraps

from flask import (Flask, render_template, request, redirect, url_for, flash,
                   jsonify, Response, session)
from flask_login import (LoginManager, login_user, logout_user, login_required,
                         current_user)
from sqlalchemy import func, desc, and_, text, select, exists
from sqlalchemy.exc import OperationalError, ProgrammingError
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from models import (db, User, Supplier, Purchase, PurchaseLot, Run, RunInput,
                    KpiTarget, SystemSetting, AuditLog, BiomassAvailability, CostEntry,
                    FieldAccessToken, FieldPurchaseSubmission, LabTest, SupplierAttachment, PhotoAsset,
                    SlackIngestedMessage, SlackChannelSyncConfig)

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "gold-drop-dev-key-change-in-prod")
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///golddrop.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["FIELD_UPLOAD_DIR"] = os.path.join(app.root_path, "static", "uploads", "field")
app.config["FIELD_UPLOAD_MAX_BYTES"] = 20 * 1024 * 1024  # 20 MB per image
app.config["LAB_UPLOAD_DIR"] = os.path.join(app.root_path, "static", "uploads", "labs")
app.config["LAB_UPLOAD_MAX_BYTES"] = 50 * 1024 * 1024  # 50 MB per file

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


def _slack_enabled() -> bool:
    return (SystemSetting.get("slack_enabled", "0") or "0").strip() in ("1", "true", "yes", "on")


def _slack_webhook_url() -> str | None:
    return (SystemSetting.get("slack_webhook_url", "") or "").strip() or None


def _slack_signing_secret() -> str | None:
    return (SystemSetting.get("slack_signing_secret", "") or "").strip() or None


def _slack_bot_token() -> str | None:
    return (SystemSetting.get("slack_bot_token", "") or "").strip() or None


def _slack_channel() -> str | None:
    return (SystemSetting.get("slack_default_channel", "") or "").strip() or None


def _post_slack_webhook(text_value: str) -> None:
    webhook = _slack_webhook_url()
    if not webhook or not _slack_enabled():
        return
    payload = json.dumps({"text": text_value}).encode("utf-8")
    req = urllib.request.Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=6):
            pass
    except Exception:
        app.logger.exception("Slack webhook send failed")


def _post_slack_api_message(text_value: str) -> None:
    token = _slack_bot_token()
    channel = _slack_channel()
    if not token or not channel or not _slack_enabled():
        return
    payload = json.dumps({"channel": channel, "text": text_value}).encode("utf-8")
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=6):
            pass
    except Exception:
        app.logger.exception("Slack API send failed")


def notify_slack(text_value: str) -> None:
    _post_slack_webhook(text_value)
    _post_slack_api_message(text_value)


def _verify_slack_signature(req) -> bool:
    secret = _slack_signing_secret()
    if not secret:
        return False
    timestamp = req.headers.get("X-Slack-Request-Timestamp", "")
    signature = req.headers.get("X-Slack-Signature", "")
    if not timestamp or not signature:
        return False
    try:
        ts = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - ts) > 60 * 5:
        return False
    raw_body = req.get_data(cache=True, as_text=False) or b""
    basestring = f"v0:{timestamp}:{raw_body.decode('utf-8')}".encode("utf-8")
    digest = "v0=" + hmac.new(secret.encode("utf-8"), basestring, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature)


def _slack_web_api(token: str, method: str, params: dict) -> dict:
    """POST application/x-www-form-urlencoded to Slack Web API."""
    body = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}).encode("utf-8")
    req = urllib.request.Request(
        f"https://slack.com/api/{method}",
        data=body,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _slack_resolve_channel_id(token: str, channel_setting: str) -> str | None:
    """Resolve #name or channel ID from Settings default channel."""
    hint = (channel_setting or "").strip()
    if not hint:
        return None
    if hint.upper().startswith("C") and len(hint) >= 9:
        return hint
    name = hint.lstrip("#").strip().lower()
    cursor = None
    for _ in range(40):
        params: dict[str, str] = {"types": "public_channel,private_channel", "limit": "200"}
        if cursor:
            params["cursor"] = cursor
        data = _slack_web_api(token, "conversations.list", params)
        if not data.get("ok"):
            app.logger.warning("Slack conversations.list failed: %s", data.get("error"))
            return None
        for ch in data.get("channels") or []:
            if (ch.get("name") or "").lower() == name:
                return ch.get("id")
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    return None


SLACK_SYNC_CHANNEL_SLOTS = 6


def _ensure_slack_sync_configs() -> None:
    """Ensure six sync slots exist; first install seeds slot 0 from slack_default_channel."""
    count = SlackChannelSyncConfig.query.count()
    if count == 0:
        default_ch = (SystemSetting.get("slack_default_channel") or "").strip()
        for i in range(SLACK_SYNC_CHANNEL_SLOTS):
            hint = default_ch if i == 0 else ""
            db.session.add(SlackChannelSyncConfig(slot_index=i, channel_hint=hint))
        db.session.commit()
        return
    have = {r.slot_index for r in SlackChannelSyncConfig.query.all()}
    added = False
    for i in range(SLACK_SYNC_CHANNEL_SLOTS):
        if i not in have:
            db.session.add(SlackChannelSyncConfig(slot_index=i, channel_hint=""))
            added = True
    if added:
        db.session.commit()


def _slack_ingest_channel_history(
    token: str,
    channel_id: str,
    oldest: str,
    ingested_by: str,
) -> tuple[int, int, str | None, str | None]:
    """
    Pull conversations.history pages; insert new SlackIngestedMessage rows (deduped).
    Returns (new_rows, scanned, max_ts_seen, error_code).
    """
    new_rows = 0
    scanned = 0
    max_ts_seen: str | None = None
    cursor = None
    for _page in range(50):
        params: dict[str, str] = {"channel": channel_id, "limit": "200", "oldest": oldest}
        if cursor:
            params["cursor"] = cursor
        data = _slack_web_api(token, "conversations.history", params)
        if not data.get("ok"):
            return new_rows, scanned, max_ts_seen, str(data.get("error", "unknown"))
        for msg in data.get("messages") or []:
            scanned += 1
            if msg.get("subtype") in ("channel_join", "channel_leave", "channel_topic", "channel_purpose"):
                continue
            ts = msg.get("ts")
            if not ts:
                continue
            if max_ts_seen is None or float(ts) > float(max_ts_seen):
                max_ts_seen = str(ts)
            if SlackIngestedMessage.query.filter_by(channel_id=channel_id, message_ts=str(ts)).first():
                continue
            txt = (msg.get("text") or "").strip()
            if not txt:
                if msg.get("files"):
                    txt = "[attachment or file only]"
                else:
                    continue
            derived = _derive_slack_production_message(txt)
            db.session.add(SlackIngestedMessage(
                channel_id=channel_id,
                message_ts=str(ts),
                slack_user_id=(msg.get("user") or None),
                raw_text=txt,
                message_kind=derived.get("message_kind"),
                derived_json=json.dumps(derived),
                ingested_by=ingested_by,
            ))
            new_rows += 1
        cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
        if not cursor:
            break
    return new_rows, scanned, max_ts_seen, None


def _derive_slack_production_message(raw: str) -> dict:
    """Lightweight classifier + field extraction for production / yield Slack templates."""
    text = raw or ""
    lower = text.lower()
    kind = "unknown"
    if re.search(r"wet\s*thca|wet\s*hte", lower) and re.search(r"bio\s*:\s*[\d,]+", lower):
        kind = "yield_report"
    elif re.search(r"reactor\s*:", lower) and re.search(r"strain\s*:", lower):
        kind = "production_log"

    def grab(pat: str):
        m = re.search(pat, text, flags=re.I)
        return m.group(1).strip() if m else None

    out: dict = {"message_kind": kind, "source": grab(r"source\s*:\s*([^\n]+)")}
    strain = grab(r"strain\s*:\s*([^\n]+)")
    if strain:
        out["strain"] = strain
    if kind == "yield_report":
        bm = re.search(r"bio\s*:\s*([\d,]+)\s*lbs?", text, re.I)
        if bm:
            try:
                out["bio_lbs"] = float(bm.group(1).replace(",", ""))
            except ValueError:
                pass
        for label, key in (("wet wt", "wet_total_g"), ("wet thca", "wet_thca_g"), ("wet hte", "wet_hte_g")):
            mm = re.search(rf"{label}\s*:\s*([\d,]+)\s*g", lower)
            if mm:
                try:
                    out[key] = float(mm.group(1).replace(",", ""))
                except ValueError:
                    pass
        ym = re.search(r"yield\s*:\s*([\d.]+)\s*%", lower)
        if ym:
            try:
                out["yield_pct_mentioned"] = float(ym.group(1))
            except ValueError:
                pass
    elif kind == "production_log":
        rm = re.search(r"reactor\s*:\s*([A-Za-z0-9]+)", text, re.I)
        if rm:
            out["reactor"] = rm.group(1).upper()
        wm = re.search(r"bio\s*wt\s*:\s*([\d.]+)", text, re.I)
        if wm:
            try:
                out["bio_weight_lbs"] = float(wm.group(1))
            except ValueError:
                pass
    notes = grab(r"notes\s*:\s*([^\n]+)")
    if notes:
        out["notes_line"] = notes
    return out


def _hash_field_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _allowed_image_filename(filename: str) -> bool:
    name = (filename or "").lower()
    return name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"))


def _allowed_lab_filename(filename: str) -> bool:
    name = (filename or "").lower()
    return name.endswith((".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".pdf"))


def _file_size_bytes(file_obj) -> int:
    cur = file_obj.stream.tell()
    file_obj.stream.seek(0, os.SEEK_END)
    size = file_obj.stream.tell()
    file_obj.stream.seek(cur, os.SEEK_SET)
    return int(size or 0)


def _save_uploads(files, prefix: str, upload_dir: str, max_bytes: int, validator, error_message: str) -> list[str]:
    os.makedirs(upload_dir, exist_ok=True)
    saved = []
    for f in files or []:
        if not f or not getattr(f, "filename", ""):
            continue
        if not validator(f.filename):
            raise ValueError(error_message)
        size = _file_size_bytes(f)
        if size <= 0:
            continue
        if size > max_bytes:
            raise ValueError(f"Each file must be {int(max_bytes/(1024*1024))} MB or smaller.")

        base = secure_filename(f.filename) or "file.bin"
        ext = os.path.splitext(base)[1].lower() or ".bin"
        unique_name = f"{prefix}-{secrets.token_hex(8)}{ext}"
        abs_path = os.path.join(upload_dir, unique_name)
        f.save(abs_path)
        parent = os.path.basename(upload_dir)
        saved.append(f"uploads/{parent}/{unique_name}")
    return saved


def _save_field_photos(files, prefix: str) -> list[str]:
    """
    Save uploaded field photos under static/uploads/field and return
    relative static paths (e.g. uploads/field/abc.jpg).
    """
    return _save_uploads(
        files=files,
        prefix=prefix,
        upload_dir=app.config["FIELD_UPLOAD_DIR"],
        max_bytes=int(app.config.get("FIELD_UPLOAD_MAX_BYTES", 20 * 1024 * 1024)),
        validator=_allowed_image_filename,
        error_message="Only image files (.jpg, .jpeg, .png, .webp, .heic, .heif) are allowed.",
    )


def _save_lab_files(files, prefix: str) -> list[str]:
    return _save_uploads(
        files=files,
        prefix=prefix,
        upload_dir=app.config["LAB_UPLOAD_DIR"],
        max_bytes=int(app.config.get("LAB_UPLOAD_MAX_BYTES", 50 * 1024 * 1024)),
        validator=_allowed_lab_filename,
        error_message="Only lab files (.jpg, .jpeg, .png, .webp, .heic, .heif, .pdf) are allowed.",
    )


def _json_paths(value) -> list[str]:
    try:
        items = json.loads(value or "[]")
        return [p for p in items if isinstance(p, str) and p.strip()]
    except Exception:
        return []


def _create_photo_asset(
    file_path: str,
    *,
    source_type: str,
    category: str,
    tags: list[str] | None = None,
    title: str | None = None,
    supplier_id: str | None = None,
    purchase_id: str | None = None,
    submission_id: str | None = None,
    uploaded_by: str | None = None,
) -> None:
    db.session.add(PhotoAsset(
        file_path=file_path,
        source_type=source_type,
        category=category,
        tags=",".join([t.strip().lower() for t in (tags or []) if t and t.strip()]) or None,
        title=title,
        supplier_id=supplier_id,
        purchase_id=purchase_id,
        submission_id=submission_id,
        uploaded_by=uploaded_by,
    ))


def _photo_asset_exists(*, file_path: str, source_type: str, category: str, submission_id: str | None = None, supplier_id: str | None = None, purchase_id: str | None = None) -> bool:
    q = PhotoAsset.query.filter(
        PhotoAsset.file_path == file_path,
        PhotoAsset.source_type == source_type,
        PhotoAsset.category == category,
    )
    if submission_id:
        q = q.filter(PhotoAsset.submission_id == submission_id)
    if supplier_id:
        q = q.filter(PhotoAsset.supplier_id == supplier_id)
    if purchase_id:
        q = q.filter(PhotoAsset.purchase_id == purchase_id)
    return q.first() is not None


def _supplier_attachment_exists(*, supplier_id: str, file_path: str) -> bool:
    return SupplierAttachment.query.filter(
        SupplierAttachment.supplier_id == supplier_id,
        SupplierAttachment.file_path == file_path,
    ).first() is not None


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
        if "storage_note" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN storage_note TEXT"))
        if "license_info" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN license_info TEXT"))
        if "queue_placement" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN queue_placement VARCHAR(20)"))
        if "coa_status_text" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN coa_status_text TEXT"))
        if "deleted_at" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in cols:
            db.session.execute(text("ALTER TABLE purchases ADD COLUMN deleted_by VARCHAR(36)"))

    # Biomass availabilities: purchase_id (if table already exists)
    if has_table("biomass_availabilities"):
        cols = column_names("biomass_availabilities")
        if "purchase_id" not in cols:
            db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN purchase_id VARCHAR(36)"))
        if "field_photo_paths_json" not in cols:
            db.session.execute(text("ALTER TABLE biomass_availabilities ADD COLUMN field_photo_paths_json TEXT"))

    # Runs: cost_per_gram_thca / cost_per_gram_hte
    if has_table("runs"):
        cols = column_names("runs")
        if "cost_per_gram_thca" not in cols:
            db.session.execute(text("ALTER TABLE runs ADD COLUMN cost_per_gram_thca FLOAT"))
        if "cost_per_gram_hte" not in cols:
            db.session.execute(text("ALTER TABLE runs ADD COLUMN cost_per_gram_hte FLOAT"))
        if "deleted_at" not in cols:
            db.session.execute(text("ALTER TABLE runs ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in cols:
            db.session.execute(text("ALTER TABLE runs ADD COLUMN deleted_by VARCHAR(36)"))

    if has_table("purchase_lots"):
        cols = column_names("purchase_lots")
        if "deleted_at" not in cols:
            db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN deleted_at DATETIME"))
        if "deleted_by" not in cols:
            db.session.execute(text("ALTER TABLE purchase_lots ADD COLUMN deleted_by VARCHAR(36)"))

    # Field purchase submissions: photos_json
    if has_table("field_purchase_submissions"):
        cols = column_names("field_purchase_submissions")
        if "photos_json" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN photos_json TEXT"))
        if "harvest_date" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN harvest_date DATE"))
        if "storage_note" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN storage_note TEXT"))
        if "license_info" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN license_info TEXT"))
        if "queue_placement" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN queue_placement VARCHAR(20)"))
        if "coa_status_text" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN coa_status_text TEXT"))
        if "supplier_photos_json" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN supplier_photos_json TEXT"))
        if "biomass_photos_json" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN biomass_photos_json TEXT"))
        if "coa_photos_json" not in cols:
            db.session.execute(text("ALTER TABLE field_purchase_submissions ADD COLUMN coa_photos_json TEXT"))

    # New table: lab_tests
    if not has_table("lab_tests"):
        db.session.execute(text(
            "CREATE TABLE lab_tests ("
            "id VARCHAR(36) PRIMARY KEY, "
            "supplier_id VARCHAR(36) NOT NULL, "
            "purchase_id VARCHAR(36), "
            "test_date DATE NOT NULL, "
            "test_type VARCHAR(50) NOT NULL, "
            "status_text TEXT, "
            "potency_pct FLOAT, "
            "notes TEXT, "
            "result_paths_json TEXT, "
            "created_at DATETIME, "
            "created_by VARCHAR(36)"
            ")"
        ))
    # New table: supplier_attachments
    if not has_table("supplier_attachments"):
        db.session.execute(text(
            "CREATE TABLE supplier_attachments ("
            "id VARCHAR(36) PRIMARY KEY, "
            "supplier_id VARCHAR(36) NOT NULL, "
            "document_type VARCHAR(50) NOT NULL, "
            "title VARCHAR(200), "
            "file_path VARCHAR(500) NOT NULL, "
            "uploaded_at DATETIME, "
            "uploaded_by VARCHAR(36)"
            ")"
        ))
    # New table: photo_assets (searchable media library)
    if not has_table("photo_assets"):
        db.session.execute(text(
            "CREATE TABLE photo_assets ("
            "id VARCHAR(36) PRIMARY KEY, "
            "supplier_id VARCHAR(36), "
            "purchase_id VARCHAR(36), "
            "submission_id VARCHAR(36), "
            "source_type VARCHAR(50) NOT NULL, "
            "category VARCHAR(50) NOT NULL, "
            "title VARCHAR(200), "
            "tags VARCHAR(500), "
            "file_path VARCHAR(500) NOT NULL, "
            "uploaded_at DATETIME, "
            "uploaded_by VARCHAR(36)"
            ")"
        ))
    # Slack ingested channel messages (history sync)
    if not has_table("slack_ingested_messages"):
        db.session.execute(text(
            "CREATE TABLE slack_ingested_messages ("
            "id VARCHAR(36) PRIMARY KEY, "
            "channel_id VARCHAR(32) NOT NULL, "
            "message_ts VARCHAR(32) NOT NULL, "
            "slack_user_id VARCHAR(32), "
            "raw_text TEXT, "
            "message_kind VARCHAR(40), "
            "derived_json TEXT, "
            "ingested_at DATETIME, "
            "ingested_by VARCHAR(36), "
            "UNIQUE(channel_id, message_ts)"
            ")"
        ))
    # Per-channel Slack history sync slots (cursor per channel)
    if not has_table("slack_channel_sync_configs"):
        db.session.execute(text(
            "CREATE TABLE slack_channel_sync_configs ("
            "id VARCHAR(36) PRIMARY KEY, "
            "slot_index INTEGER NOT NULL, "
            "channel_hint VARCHAR(200) NOT NULL DEFAULT '', "
            "resolved_channel_id VARCHAR(32), "
            "last_watermark_ts VARCHAR(32), "
            "UNIQUE(slot_index)"
            ")"
        ))

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

def _get_or_create_supplier_from_field_form(token):
    """
    Field intake can select an existing supplier or create one by name.
    Returns (supplier, created_bool).
    """
    supplier_id = (request.form.get("supplier_id") or "").strip()
    new_name = (request.form.get("new_supplier_name") or "").strip()

    if supplier_id:
        sup = db.session.get(Supplier, supplier_id)
        if not sup:
            raise ValueError("Selected supplier was not found.")
        return sup, False

    if not new_name:
        raise ValueError("Supplier is required (pick one or enter a new supplier name).")

    new_location = (request.form.get("new_supplier_location") or "").strip() or None
    new_phone = (request.form.get("new_supplier_phone") or "").strip() or None
    new_email = (request.form.get("new_supplier_email") or "").strip() or None

    # Dedupe by name (case-insensitive)
    existing = Supplier.query.filter(func.lower(Supplier.name) == new_name.lower()).first()
    if existing:
        return existing, False

    sup = Supplier(
        name=new_name,
        location=new_location,
        contact_phone=new_phone,
        contact_email=new_email,
        is_active=True,
        notes="Created via field intake",
    )
    db.session.add(sup)
    db.session.flush()
    log_audit(
        "create",
        "supplier",
        sup.id,
        details=json.dumps({
            "source": "field_intake",
            "token_label": token.label,
            "name": new_name,
            "location": new_location,
            "contact_phone": new_phone,
            "contact_email": new_email,
        }),
        user_id=None,
    )
    return sup, True


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
            sup, _created = _get_or_create_supplier_from_field_form(token)

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

            photos = request.files.getlist("photos")
            saved_photo_paths = _save_field_photos(photos, prefix="biomass")

            b = BiomassAvailability(
                supplier_id=sup.id,
                availability_date=availability_date,
                strain_name=(request.form.get("strain_name") or "").strip() or None,
                declared_weight_lbs=declared_weight,
                declared_price_per_lb=declared_price,
                estimated_potency_pct=estimated_potency,
                testing_timing=(request.form.get("testing_timing") or "before_delivery").strip() or "before_delivery",
                testing_status=(request.form.get("testing_status") or "pending").strip() or "pending",
                stage=stage,
                field_photo_paths_json=(json.dumps(saved_photo_paths) if saved_photo_paths else None),
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
                    "photos_count": len(saved_photo_paths),
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
            sup, _created = _get_or_create_supplier_from_field_form(token)

            pd = (request.form.get("purchase_date") or "").strip()
            if not pd:
                raise ValueError("Purchase Date is required.")
            purchase_date = datetime.strptime(pd, "%Y-%m-%d").date()

            dd = (request.form.get("delivery_date") or "").strip()
            delivery_date = datetime.strptime(dd, "%Y-%m-%d").date() if dd else None
            hd = (request.form.get("harvest_date") or "").strip()
            harvest_date = datetime.strptime(hd, "%Y-%m-%d").date() if hd else None

            ep = (request.form.get("estimated_potency_pct") or "").strip()
            estimated_potency = float(ep) if ep else None
            if estimated_potency is not None and not (0 <= estimated_potency <= 100):
                raise ValueError("Estimated Potency must be between 0 and 100.")

            ppl = (request.form.get("price_per_lb") or "").strip()
            price_per_lb = float(ppl) if ppl else None
            if price_per_lb is not None and price_per_lb < 0:
                raise ValueError("Price/lb cannot be negative.")
            queue_placement = ((request.form.get("queue_placement") or "").strip() or None)
            if queue_placement and queue_placement not in ("aggregate", "indoor", "outdoor"):
                raise ValueError("Queue Placement must be Aggregate, Indoor, or Outdoor.")

            # Lots (at least one)
            lot_strains = request.form.getlist("lot_strains[]")
            lot_weights = request.form.getlist("lot_weights[]")
            lots = []
            for strain, w in zip(lot_strains, lot_weights):
                strain = (strain or "").strip()
                w = (w or "").strip()
                if not strain and not w:
                    continue
                if w:
                    try:
                        weight = float(w)
                    except ValueError:
                        raise ValueError("Lot weight must be a number.")
                    if weight <= 0:
                        raise ValueError("Lot weight must be greater than 0.")
                else:
                    weight = None
                lots.append({"strain": strain or None, "weight_lbs": weight})

            supplier_photos = request.files.getlist("supplier_photos")
            biomass_photos = request.files.getlist("biomass_photos")
            coa_photos = request.files.getlist("coa_photos")
            saved_supplier_paths = _save_field_photos(supplier_photos, prefix="purchase-supplier")
            saved_biomass_paths = _save_field_photos(biomass_photos, prefix="purchase-biomass")
            saved_coa_paths = _save_field_photos(coa_photos, prefix="purchase-coa")
            all_paths = saved_supplier_paths + saved_biomass_paths + saved_coa_paths

            sub = FieldPurchaseSubmission(
                source_token_id=token.id,
                supplier_id=sup.id,
                purchase_date=purchase_date,
                delivery_date=delivery_date,
                harvest_date=harvest_date,
                estimated_potency_pct=estimated_potency,
                price_per_lb=price_per_lb,
                storage_note=((request.form.get("storage_note") or "").strip() or None),
                license_info=((request.form.get("license_info") or "").strip() or None),
                queue_placement=queue_placement,
                coa_status_text=((request.form.get("coa_status_text") or "").strip() or None),
                notes=((request.form.get("notes") or "").strip() or None),
                lots_json=json.dumps(lots),
                photos_json=(json.dumps(all_paths) if all_paths else None),
                supplier_photos_json=(json.dumps(saved_supplier_paths) if saved_supplier_paths else None),
                biomass_photos_json=(json.dumps(saved_biomass_paths) if saved_biomass_paths else None),
                coa_photos_json=(json.dumps(saved_coa_paths) if saved_coa_paths else None),
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
                    "photos_count": len(all_paths),
                }),
                user_id=None,
            )
            db.session.commit()
            notify_slack(f"New field purchase submission from {sup.name}: {len(lots)} lot row(s), pending review.")
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
    runs_q = Run.query.filter(Run.deleted_at.is_(None), Run.run_date >= start_date)
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
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
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
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
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
        PurchaseLot.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
        Purchase.status.in_(("delivered", "in_testing", "available", "processing", "complete"))
    ).scalar() or 0

    week_start = date.today() - timedelta(days=date.today().weekday())
    wtd_runs_q = Run.query.filter(
        Run.deleted_at.is_(None),
        Run.run_date >= week_start,
        Run.run_date <= date.today(),
    )
    if exclude_unpriced:
        wtd_runs_q = wtd_runs_q.filter(_priced_run_filter())
    wtd_runs = wtd_runs_q.all()
    wtd_lbs = sum(r.bio_in_reactor_lbs or 0 for r in wtd_runs)
    wtd_dry_thca = sum(r.dry_thca_g or 0 for r in wtd_runs)
    wtd_dry_hte = sum(r.dry_hte_g or 0 for r in wtd_runs)

    current_month_start = date.today().replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    mom_rows = db.session.query(
        Supplier.id.label("supplier_id"),
        Supplier.name.label("supplier_name"),
        func.avg(Run.overall_yield_pct).label("avg_yield"),
    ).join(Purchase, Purchase.supplier_id == Supplier.id
    ).join(PurchaseLot, PurchaseLot.purchase_id == Purchase.id
    ).join(RunInput, RunInput.lot_id == PurchaseLot.id
    ).join(Run, Run.id == RunInput.run_id
    ).filter(
        Run.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
        PurchaseLot.deleted_at.is_(None),
        Run.is_rollover == False,
        Run.run_date >= current_month_start,
        Run.overall_yield_pct.isnot(None),
    ).group_by(Supplier.id, Supplier.name).all()
    if exclude_unpriced:
        mom_rows = db.session.query(
            Supplier.id.label("supplier_id"),
            Supplier.name.label("supplier_name"),
            func.avg(Run.overall_yield_pct).label("avg_yield"),
        ).join(Purchase, Purchase.supplier_id == Supplier.id
        ).join(PurchaseLot, PurchaseLot.purchase_id == Purchase.id
        ).join(RunInput, RunInput.lot_id == PurchaseLot.id
        ).join(Run, Run.id == RunInput.run_id
        ).filter(
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
            Run.is_rollover == False,
            Run.run_date >= current_month_start,
            Run.overall_yield_pct.isnot(None),
            _priced_run_filter(),
        ).group_by(Supplier.id, Supplier.name).all()
    best_supplier_mom = None
    if mom_rows:
        best = max(mom_rows, key=lambda r: float(r.avg_yield or 0))
        prev = db.session.query(func.avg(Run.overall_yield_pct)).join(
            RunInput, Run.id == RunInput.run_id
        ).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
        ).filter(
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
            Run.is_rollover == False,
            Purchase.supplier_id == best.supplier_id,
            Run.run_date >= prev_month_start,
            Run.run_date <= prev_month_end,
        )
        if exclude_unpriced:
            prev = prev.filter(_priced_run_filter())
        prev_avg = prev.scalar()
        best_supplier_mom = {
            "name": best.supplier_name,
            "current": float(best.avg_yield or 0),
            "previous": float(prev_avg or 0) if prev_avg is not None else None,
        }
        if best_supplier_mom["previous"] and best_supplier_mom["previous"] > 0:
            best_supplier_mom["pct_change"] = ((best_supplier_mom["current"] - best_supplier_mom["previous"]) / best_supplier_mom["previous"]) * 100.0
        else:
            best_supplier_mom["pct_change"] = None

    return render_template("dashboard.html",
                           kpi_cards=kpi_cards, period=period,
                           total_runs=total_runs, total_lbs=total_lbs,
                           total_dry_output=total_dry_output, on_hand=on_hand,
                           exclude_unpriced=exclude_unpriced,
                           wtd_lbs=wtd_lbs, wtd_dry_thca=wtd_dry_thca, wtd_dry_hte=wtd_dry_hte,
                           best_supplier_mom=best_supplier_mom)


# ── Runs ─────────────────────────────────────────────────────────────────────

@app.route("/runs")
@login_required
def runs_list():
    page = request.args.get("page", 1, type=int)
    sort = request.args.get("sort", "run_date")
    order = request.args.get("order", "desc")
    search = request.args.get("search", "").strip()
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    supplier_filter = (request.args.get("supplier_id") or "").strip()
    min_pot_raw = (request.args.get("min_potency") or "").strip()
    max_pot_raw = (request.args.get("max_potency") or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    try:
        min_potency = float(min_pot_raw) if min_pot_raw else None
        max_potency = float(max_pot_raw) if max_pot_raw else None
    except ValueError:
        min_potency = None
        max_potency = None

    query = Run.query.filter(Run.deleted_at.is_(None))
    if search:
        query = query.join(RunInput, isouter=True).join(PurchaseLot, isouter=True).filter(
            db.or_(PurchaseLot.strain_name.ilike(f"%{search}%"),
                   Run.notes.ilike(f"%{search}%"))
        ).distinct()
    if start_date:
        query = query.filter(Run.run_date >= start_date)
    if end_date:
        query = query.filter(Run.run_date <= end_date)
    if min_potency is not None:
        query = query.filter(Run.thca_yield_pct >= min_potency)
    if max_potency is not None:
        query = query.filter(Run.thca_yield_pct <= max_potency)
    if supplier_filter:
        query = query.join(RunInput, RunInput.run_id == Run.id).join(
            PurchaseLot, PurchaseLot.id == RunInput.lot_id
        ).join(Purchase, Purchase.id == PurchaseLot.purchase_id).filter(
            Purchase.supplier_id == supplier_filter
        ).distinct()

    sort_col = getattr(Run, sort, Run.run_date)
    if order == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    pagination = query.paginate(page=page, per_page=25, error_out=False)
    run_ids = [r.id for r in pagination.items]
    pricing_status = _pricing_status_for_run_ids(run_ids)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template("runs.html", runs=pagination.items, pagination=pagination,
                           sort=sort, order=order, search=search,
                           pricing_status=pricing_status, suppliers=suppliers,
                           supplier_filter=supplier_filter,
                           start_date=start_raw, end_date=end_raw,
                           min_potency=min_pot_raw, max_potency=max_pot_raw)


@app.route("/runs/new", methods=["GET", "POST"])
@editor_required
def run_new():
    if request.method == "POST":
        return _save_run(None)

    lots = PurchaseLot.query.join(Purchase).filter(
        PurchaseLot.remaining_weight_lbs > 0,
        PurchaseLot.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
    ).all()
    return render_template("run_form.html", run=None, lots=lots, today=date.today())


@app.route("/runs/<run_id>/edit", methods=["GET", "POST"])
@editor_required
def run_edit(run_id):
    run = db.session.get(Run, run_id)
    if not run or run.deleted_at is not None:
        flash("Run not found.", "error")
        return redirect(url_for("runs_list"))

    if request.method == "POST":
        return _save_run(run)

    lots = PurchaseLot.query.join(Purchase).filter(
        PurchaseLot.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
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
        on_hand_statuses = ("delivered", "in_testing", "available", "processing", "complete")
        run.bio_in_house_lbs = db.session.query(func.sum(PurchaseLot.remaining_weight_lbs)).join(Purchase).filter(
            PurchaseLot.remaining_weight_lbs > 0,
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            Purchase.status.in_(on_hand_statuses),
        ).scalar() or 0
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
                    if lot and lot.deleted_at is None and lot.purchase and lot.purchase.deleted_at is None:
                        lot.remaining_weight_lbs = max(0, lot.remaining_weight_lbs - weight)

        run.calculate_cost()
        log_audit("update" if existing_run else "create", "run", run.id)
        db.session.commit()
        flash("Run saved successfully.", "success")
        return redirect(url_for("runs_list"))

    except Exception as e:
        db.session.rollback()
        flash(f"Error saving run: {str(e)}", "error")
        lots = PurchaseLot.query.join(Purchase).filter(
            PurchaseLot.remaining_weight_lbs > 0,
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
        ).all()
        return render_template("run_form.html", run=existing_run, lots=lots, today=date.today())


@app.route("/runs/<run_id>/delete", methods=["POST"])
@editor_required
def run_delete(run_id):
    run = db.session.get(Run, run_id)
    if run and run.deleted_at is None:
        # Restore lot weights
        for inp in run.inputs:
            lot = db.session.get(PurchaseLot, inp.lot_id)
            if lot and lot.deleted_at is None:
                lot.remaining_weight_lbs += inp.weight_lbs
        run.deleted_at = datetime.utcnow()
        run.deleted_by = current_user.id
        log_audit("delete", "run", run.id, details=json.dumps({"mode": "soft"}))
        db.session.commit()
        notify_slack(f"Run soft-deleted: {run.id}.")
        flash("Run deleted.", "success")
    return redirect(url_for("runs_list"))


@app.route("/runs/<run_id>/hard_delete", methods=["POST"])
@admin_required
def run_hard_delete(run_id):
    run = db.session.get(Run, run_id)
    if not run:
        flash("Run not found.", "error")
        return redirect(url_for("runs_list"))
    if run.deleted_at is None:
        for inp in run.inputs:
            lot = db.session.get(PurchaseLot, inp.lot_id)
            if lot and lot.deleted_at is None:
                lot.remaining_weight_lbs += inp.weight_lbs
    log_audit("delete", "run", run.id, details=json.dumps({"mode": "hard"}))
    db.session.delete(run)
    db.session.commit()
    notify_slack(f"Run hard-deleted: {run.id}.")
    flash("Run permanently deleted.", "success")
    return redirect(url_for("runs_list"))


# ── Cost Entries ─────────────────────────────────────────────────────────────

@app.route("/costs")
@login_required
def costs_list():
    """View operational cost entries."""
    cost_type = request.args.get("type", "")
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    query = CostEntry.query
    if cost_type:
        query = query.filter_by(cost_type=cost_type)
    if start_date:
        query = query.filter(CostEntry.end_date >= start_date)
    if end_date:
        query = query.filter(CostEntry.start_date <= end_date)
    entries = query.order_by(CostEntry.start_date.desc()).all()

    solvent_total = sum(e.total_cost for e in CostEntry.query.filter_by(cost_type="solvent").all())
    personnel_total = sum(e.total_cost for e in CostEntry.query.filter_by(cost_type="personnel").all())
    overhead_total = sum(e.total_cost for e in CostEntry.query.filter_by(cost_type="overhead").all())

    return render_template("costs.html", entries=entries, cost_type=cost_type,
                           solvent_total=solvent_total, personnel_total=personnel_total,
                           overhead_total=overhead_total, start_date=start_raw, end_date=end_raw)


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
    supplier_filter = (request.args.get("supplier_id") or "").strip()
    strain_filter = (request.args.get("strain") or "").strip().lower()
    # On-hand lots: only from purchases that have actually arrived
    on_hand_statuses = ("delivered", "in_testing", "available", "processing", "complete")
    on_hand_q = PurchaseLot.query.join(Purchase).filter(
        PurchaseLot.remaining_weight_lbs > 0,
        PurchaseLot.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
        Purchase.status.in_(on_hand_statuses)
    )
    if supplier_filter:
        on_hand_q = on_hand_q.filter(Purchase.supplier_id == supplier_filter)
    if strain_filter:
        on_hand_q = on_hand_q.filter(func.lower(PurchaseLot.strain_name).like(f"%{strain_filter}%"))
    on_hand = on_hand_q.all()

    # In-transit purchases
    in_transit_q = Purchase.query.filter(
        Purchase.deleted_at.is_(None),
        Purchase.status.in_(["committed", "ordered", "in_transit"])
    )
    if supplier_filter:
        in_transit_q = in_transit_q.filter(Purchase.supplier_id == supplier_filter)
    in_transit = in_transit_q.all()

    # Summary
    total_on_hand = sum(l.remaining_weight_lbs for l in on_hand)
    total_in_transit = sum(p.stated_weight_lbs for p in in_transit)
    daily_target = SystemSetting.get_float("daily_throughput_target", 500)
    days_supply = total_on_hand / daily_target if daily_target > 0 else 0

    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template("inventory.html", on_hand=on_hand, in_transit=in_transit,
                           total_on_hand=total_on_hand, total_in_transit=total_in_transit,
                           days_supply=days_supply, suppliers=suppliers,
                           supplier_filter=supplier_filter, strain_filter=(request.args.get("strain") or "").strip())


# ── Purchases ────────────────────────────────────────────────────────────────

@app.route("/purchases")
@login_required
def purchases_list():
    page = request.args.get("page", 1, type=int)
    status_filter = request.args.get("status", "")
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    supplier_filter = (request.args.get("supplier_id") or "").strip()
    min_pot_raw = (request.args.get("min_potency") or "").strip()
    max_pot_raw = (request.args.get("max_potency") or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    try:
        min_potency = float(min_pot_raw) if min_pot_raw else None
        max_potency = float(max_pot_raw) if max_pot_raw else None
    except ValueError:
        min_potency = None
        max_potency = None
    query = Purchase.query.filter(Purchase.deleted_at.is_(None))
    if status_filter:
        query = query.filter_by(status=status_filter)
    if start_date:
        query = query.filter(Purchase.purchase_date >= start_date)
    if end_date:
        query = query.filter(Purchase.purchase_date <= end_date)
    if supplier_filter:
        query = query.filter(Purchase.supplier_id == supplier_filter)
    if min_potency is not None:
        query = query.filter(Purchase.stated_potency_pct >= min_potency)
    if max_potency is not None:
        query = query.filter(Purchase.stated_potency_pct <= max_potency)
    pagination = query.order_by(Purchase.purchase_date.desc()).paginate(page=page, per_page=25)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template("purchases.html", purchases=pagination.items, pagination=pagination,
                           status_filter=status_filter, suppliers=suppliers,
                           supplier_filter=supplier_filter,
                           start_date=start_raw, end_date=end_raw,
                           min_potency=min_pot_raw, max_potency=max_pot_raw)


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
    if not purchase or purchase.deleted_at is not None:
        flash("Purchase not found.", "error")
        return redirect(url_for("purchases_list"))
    if request.method == "POST":
        return _save_purchase(purchase)
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    purchase_audit_photos = PhotoAsset.query.filter(
        PhotoAsset.purchase_id == purchase.id,
        PhotoAsset.source_type == "field_submission",
    ).order_by(PhotoAsset.uploaded_at.desc()).all()
    rate = SystemSetting.get_float("potency_rate", 1.50)
    return render_template("purchase_form.html", purchase=purchase, suppliers=suppliers,
                           rate=rate, today=date.today(), purchase_audit_photos=purchase_audit_photos)


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
        p.storage_note = request.form.get("storage_note", "").strip() or None
        p.license_info = request.form.get("license_info", "").strip() or None
        qp = (request.form.get("queue_placement") or "").strip().lower()
        p.queue_placement = qp if qp in ("aggregate", "indoor", "outdoor") else None
        p.coa_status_text = request.form.get("coa_status_text", "").strip() or None
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
        purchase_audit_photos = []
        if existing:
            purchase_audit_photos = PhotoAsset.query.filter(
                PhotoAsset.purchase_id == existing.id,
                PhotoAsset.source_type == "field_submission",
            ).order_by(PhotoAsset.uploaded_at.desc()).all()
        return render_template("purchase_form.html", purchase=existing, suppliers=suppliers,
                               rate=rate, today=date.today(), purchase_audit_photos=purchase_audit_photos)
    except Exception:
        db.session.rollback()
        app.logger.exception("Error saving purchase")
        flash("Error saving purchase. Please check your inputs and try again.", "error")
        suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
        rate = SystemSetting.get_float("potency_rate", 1.50)
        purchase_audit_photos = []
        if existing:
            purchase_audit_photos = PhotoAsset.query.filter(
                PhotoAsset.purchase_id == existing.id,
                PhotoAsset.source_type == "field_submission",
            ).order_by(PhotoAsset.uploaded_at.desc()).all()
        return render_template("purchase_form.html", purchase=existing, suppliers=suppliers,
                               rate=rate, today=date.today(), purchase_audit_photos=purchase_audit_photos)


@app.route("/purchases/<purchase_id>/delete", methods=["POST"])
@editor_required
def purchase_delete(purchase_id):
    p = db.session.get(Purchase, purchase_id)
    if not p or p.deleted_at is not None:
        flash("Purchase not found.", "error")
        return redirect(url_for("purchases_list"))
    has_run_inputs = db.session.query(RunInput.id).join(PurchaseLot).join(Run).filter(
        PurchaseLot.purchase_id == p.id,
        PurchaseLot.deleted_at.is_(None),
        Run.deleted_at.is_(None),
    ).first() is not None
    if has_run_inputs:
        flash("Cannot delete purchase that is used in active runs. Delete those runs first.", "error")
        return redirect(url_for("purchase_edit", purchase_id=p.id))
    p.deleted_at = datetime.utcnow()
    p.deleted_by = current_user.id
    for lot in p.lots:
        lot.deleted_at = datetime.utcnow()
        lot.deleted_by = current_user.id
    linked = BiomassAvailability.query.filter(BiomassAvailability.purchase_id == p.id).first()
    if linked:
        linked.purchase_id = None
        linked.stage = "declared"
    log_audit("delete", "purchase", p.id, details=json.dumps({"mode": "soft"}))
    db.session.commit()
    notify_slack(f"Purchase soft-deleted: {p.batch_id or p.id}.")
    flash("Purchase deleted.", "success")
    return redirect(url_for("purchases_list"))


@app.route("/purchases/<purchase_id>/hard_delete", methods=["POST"])
@admin_required
def purchase_hard_delete(purchase_id):
    p = db.session.get(Purchase, purchase_id)
    if not p:
        flash("Purchase not found.", "error")
        return redirect(url_for("purchases_list"))
    has_any_run_inputs = db.session.query(RunInput.id).join(PurchaseLot).filter(PurchaseLot.purchase_id == p.id).first() is not None
    if has_any_run_inputs:
        flash("Cannot hard-delete purchase that has run history.", "error")
        return redirect(url_for("purchase_edit", purchase_id=p.id))
    linked = BiomassAvailability.query.filter(BiomassAvailability.purchase_id == p.id).first()
    if linked:
        linked.purchase_id = None
    log_audit("delete", "purchase", p.id, details=json.dumps({"mode": "hard"}))
    db.session.delete(p)
    db.session.commit()
    notify_slack(f"Purchase hard-deleted: {p.batch_id or p.id}.")
    flash("Purchase permanently deleted.", "success")
    return redirect(url_for("purchases_list"))


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
        ).filter(
            Purchase.supplier_id == s.id,
            Run.is_rollover == False,
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
        )
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
        ).filter(
            Purchase.supplier_id == s.id,
            Run.is_rollover == False,
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
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

    current_month_start = date.today().replace(day=1)
    prev_month_end = current_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    best_supplier_mom = None
    month_rows = db.session.query(
        Supplier.id.label("supplier_id"),
        Supplier.name.label("supplier_name"),
        func.avg(Run.overall_yield_pct).label("avg_yield"),
    ).join(Purchase, Purchase.supplier_id == Supplier.id
    ).join(PurchaseLot, PurchaseLot.purchase_id == Purchase.id
    ).join(RunInput, RunInput.lot_id == PurchaseLot.id
    ).join(Run, Run.id == RunInput.run_id
    ).filter(
        Run.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
        PurchaseLot.deleted_at.is_(None),
        Run.is_rollover == False,
        Run.run_date >= current_month_start,
        Run.overall_yield_pct.isnot(None),
    )
    if exclude_unpriced:
        month_rows = month_rows.filter(_priced_run_filter())
    month_rows = month_rows.group_by(Supplier.id, Supplier.name).all()
    if month_rows:
        best = max(month_rows, key=lambda r: float(r.avg_yield or 0))
        prev_q = db.session.query(func.avg(Run.overall_yield_pct)).join(
            RunInput, Run.id == RunInput.run_id
        ).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
        ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
        ).filter(
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
            Purchase.supplier_id == best.supplier_id,
            Run.is_rollover == False,
            Run.run_date >= prev_month_start,
            Run.run_date <= prev_month_end,
            Run.overall_yield_pct.isnot(None),
        )
        if exclude_unpriced:
            prev_q = prev_q.filter(_priced_run_filter())
        prev_avg = prev_q.scalar()
        best_supplier_mom = {
            "name": best.supplier_name,
            "current": float(best.avg_yield or 0),
            "previous": float(prev_avg) if prev_avg is not None else None,
        }
        if best_supplier_mom["previous"] and best_supplier_mom["previous"] > 0:
            best_supplier_mom["pct_change"] = ((best_supplier_mom["current"] - best_supplier_mom["previous"]) / best_supplier_mom["previous"]) * 100.0
        else:
            best_supplier_mom["pct_change"] = None

    return render_template("suppliers.html", supplier_stats=supplier_stats,
                           yield_kpi=yield_kpi, thca_kpi=thca_kpi,
                           best_supplier_mom=best_supplier_mom)


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
        form_type = (request.form.get("form_type") or "supplier").strip()
        if form_type == "supplier":
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
        elif form_type == "lab_test":
            td = (request.form.get("test_date") or "").strip()
            if not td:
                flash("Lab test date is required.", "error")
                return redirect(url_for("supplier_edit", sid=s.id))
            try:
                test_date = datetime.strptime(td, "%Y-%m-%d").date()
            except ValueError:
                flash("Lab test date is invalid.", "error")
                return redirect(url_for("supplier_edit", sid=s.id))
            files = request.files.getlist("lab_files")
            saved_paths = _save_lab_files(files, prefix=f"lab-{s.id}")
            pot_raw = (request.form.get("potency_pct") or "").strip()
            try:
                potency_pct = float(pot_raw) if pot_raw else None
            except ValueError:
                flash("Lab test potency must be numeric.", "error")
                return redirect(url_for("supplier_edit", sid=s.id))
            t = LabTest(
                supplier_id=s.id,
                purchase_id=((request.form.get("purchase_id") or "").strip() or None),
                test_date=test_date,
                test_type=((request.form.get("test_type") or "coa").strip() or "coa"),
                status_text=((request.form.get("status_text") or "").strip() or None),
                potency_pct=potency_pct,
                notes=((request.form.get("notes") or "").strip() or None),
                result_paths_json=(json.dumps(saved_paths) if saved_paths else None),
                created_by=current_user.id,
            )
            db.session.add(t)
            for path in saved_paths:
                _create_photo_asset(
                    path,
                    source_type="lab_test",
                    category="lab_result",
                    tags=["lab", "test", "supplier"],
                    title=f"Lab test {test_date.isoformat()}",
                    supplier_id=s.id,
                    purchase_id=t.purchase_id,
                    uploaded_by=current_user.id,
                )
            log_audit("create", "lab_test", t.id, details=json.dumps({"supplier_id": s.id, "files": len(saved_paths)}))
            db.session.commit()
            flash("Lab test entry added.", "success")
        elif form_type == "supplier_attachment":
            files = request.files.getlist("attachment_files")
            title = (request.form.get("title") or "").strip() or None
            doc_type = ((request.form.get("document_type") or "coa").strip() or "coa")
            saved_paths = _save_lab_files(files, prefix=f"supplier-{s.id}")
            if not saved_paths:
                flash("Select at least one attachment file.", "error")
                return redirect(url_for("supplier_edit", sid=s.id))
            for path in saved_paths:
                a = SupplierAttachment(
                    supplier_id=s.id,
                    document_type=doc_type,
                    title=title,
                    file_path=path,
                    uploaded_by=current_user.id,
                )
                db.session.add(a)
                _create_photo_asset(
                    path,
                    source_type="supplier_attachment",
                    category="supplier_doc",
                    tags=["supplier", doc_type],
                    title=title or f"Supplier {doc_type}",
                    supplier_id=s.id,
                    uploaded_by=current_user.id,
                )
            log_audit("create", "supplier_attachment", s.id, details=json.dumps({"count": len(saved_paths), "type": doc_type}))
            db.session.commit()
            flash("Supplier attachments uploaded.", "success")
        return redirect(url_for("supplier_edit", sid=s.id))

    purchases = Purchase.query.filter(
        Purchase.deleted_at.is_(None),
        Purchase.supplier_id == s.id,
    ).order_by(Purchase.purchase_date.desc()).all()
    lab_tests = LabTest.query.filter_by(supplier_id=s.id).order_by(LabTest.test_date.desc()).all()
    for t in lab_tests:
        try:
            paths = json.loads(t.result_paths_json or "[]")
            t.file_paths = [p for p in paths if isinstance(p, str) and p.strip()]
        except Exception:
            t.file_paths = []
    attachments = SupplierAttachment.query.filter_by(supplier_id=s.id).order_by(SupplierAttachment.uploaded_at.desc()).all()
    return render_template("supplier_form.html", supplier=s, purchases=purchases, lab_tests=lab_tests, attachments=attachments)


@app.route("/suppliers/<sid>/lab_tests/<test_id>/delete", methods=["POST"])
@editor_required
def supplier_lab_test_delete(sid, test_id):
    t = db.session.get(LabTest, test_id)
    if not t or t.supplier_id != sid:
        flash("Lab test record not found.", "error")
        return redirect(url_for("supplier_edit", sid=sid))
    for path in _json_paths(t.result_paths_json):
        PhotoAsset.query.filter(
            PhotoAsset.file_path == path,
            PhotoAsset.supplier_id == sid,
            PhotoAsset.source_type == "lab_test",
        ).delete(synchronize_session=False)
    log_audit("delete", "lab_test", t.id, details=json.dumps({"supplier_id": sid}))
    db.session.delete(t)
    db.session.commit()
    flash("Lab test record deleted.", "success")
    return redirect(url_for("supplier_edit", sid=sid))


@app.route("/suppliers/<sid>/attachments/<attachment_id>/delete", methods=["POST"])
@editor_required
def supplier_attachment_delete(sid, attachment_id):
    a = db.session.get(SupplierAttachment, attachment_id)
    if not a or a.supplier_id != sid:
        flash("Attachment not found.", "error")
        return redirect(url_for("supplier_edit", sid=sid))
    PhotoAsset.query.filter(
        PhotoAsset.file_path == a.file_path,
        PhotoAsset.supplier_id == sid,
        PhotoAsset.source_type == "supplier_attachment",
    ).delete(synchronize_session=False)
    log_audit("delete", "supplier_attachment", a.id, details=json.dumps({"supplier_id": sid}))
    db.session.delete(a)
    db.session.commit()
    flash("Attachment deleted.", "success")
    return redirect(url_for("supplier_edit", sid=sid))


@app.route("/photos")
@login_required
def photos_library():
    q = (request.args.get("q") or "").strip()
    supplier_id = (request.args.get("supplier_id") or "").strip()
    purchase_id = (request.args.get("purchase_id") or "").strip()
    category = (request.args.get("category") or "").strip()

    query = PhotoAsset.query
    if supplier_id:
        query = query.filter(PhotoAsset.supplier_id == supplier_id)
    if purchase_id:
        query = query.filter(PhotoAsset.purchase_id == purchase_id)
    if category:
        query = query.filter(PhotoAsset.category == category)
    if q:
        like = f"%{q.lower()}%"
        query = query.filter(
            func.lower(func.coalesce(PhotoAsset.tags, "")).like(like) |
            func.lower(func.coalesce(PhotoAsset.title, "")).like(like) |
            func.lower(func.coalesce(PhotoAsset.file_path, "")).like(like)
        )

    assets = query.order_by(PhotoAsset.uploaded_at.desc()).limit(400).all()
    suppliers = Supplier.query.order_by(Supplier.name.asc()).all()
    purchases = Purchase.query.filter(Purchase.deleted_at.is_(None)).order_by(Purchase.purchase_date.desc()).limit(300).all()
    categories = [row[0] for row in db.session.query(PhotoAsset.category).distinct().order_by(PhotoAsset.category.asc()).all() if row and row[0]]
    return render_template(
        "photos.html",
        assets=assets,
        suppliers=suppliers,
        purchases=purchases,
        q=q,
        supplier_id=supplier_id,
        purchase_id=purchase_id,
        category=category,
        categories=categories,
    )


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
    ).filter(
        Run.is_rollover == False,
        Run.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
        PurchaseLot.deleted_at.is_(None),
    )
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
                        return _settings_redirect()
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
                return _settings_redirect()
            if len(new_pw) < 8:
                flash("New password must be at least 8 characters.", "error")
                return _settings_redirect()
            if new_pw != confirm_pw:
                flash("New password and confirmation do not match.", "error")
                return _settings_redirect()

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
                return _settings_redirect()
            if len(new_pw) < 8:
                flash("New password must be at least 8 characters.", "error")
                return _settings_redirect()
            if new_pw != confirm_pw:
                flash("New password and confirmation do not match.", "error")
                return _settings_redirect()

            u.set_password(new_pw)
            log_audit("password_reset", "user", u.id, details=json.dumps({"username": u.username}))
            db.session.commit()
            flash(f"Password updated for '{u.display_name}'.", "success")

        elif form_type == "slack":
            slack_map = {
                "slack_enabled": "Enable Slack integration",
                "slack_webhook_url": "Slack incoming webhook URL",
                "slack_signing_secret": "Slack signing secret",
                "slack_bot_token": "Slack bot token",
                "slack_default_channel": "Default Slack channel",
            }
            for key, desc in slack_map.items():
                if key == "slack_enabled":
                    val = "1" if request.form.get("slack_enabled") else "0"
                else:
                    val = (request.form.get(key) or "").strip()
                existing = db.session.get(SystemSetting, key)
                if existing:
                    existing.value = val
                else:
                    db.session.add(SystemSetting(key=key, value=val, description=desc))
            db.session.commit()
            flash("Slack integration settings updated.", "success")

        elif form_type == "slack_sync_channels":
            _ensure_slack_sync_configs()
            for i in range(SLACK_SYNC_CHANNEL_SLOTS):
                hint = (request.form.get(f"sync_ch_{i}") or "").strip()
                row = SlackChannelSyncConfig.query.filter_by(slot_index=i).first()
                if not row:
                    row = SlackChannelSyncConfig(slot_index=i, channel_hint=hint)
                    db.session.add(row)
                else:
                    old = (row.channel_hint or "").strip()
                    row.channel_hint = hint
                    if old != hint:
                        row.resolved_channel_id = None
                        row.last_watermark_ts = None
            db.session.commit()
            flash("Slack history sync channels saved (up to 6). Each channel keeps its own last-sync cursor.", "success")

        return _settings_redirect()

    _ensure_slack_sync_configs()
    slack_sync_slots = SlackChannelSyncConfig.query.order_by(SlackChannelSyncConfig.slot_index).all()
    system_settings = {s.key: s.value for s in SystemSetting.query.all()}
    kpis = KpiTarget.query.all()
    users = User.query.order_by(User.created_at.asc()).all()
    field_tokens = FieldAccessToken.query.order_by(FieldAccessToken.created_at.desc()).all()
    pending_field_submissions = FieldPurchaseSubmission.query.filter_by(status="pending").order_by(
        FieldPurchaseSubmission.submitted_at.desc()
    ).all()
    reviewed_field_submissions = FieldPurchaseSubmission.query.filter(
        FieldPurchaseSubmission.status.in_(("approved", "rejected"))
    ).order_by(FieldPurchaseSubmission.submitted_at.desc()).all()
    all_field_submissions = pending_field_submissions + reviewed_field_submissions
    for s in all_field_submissions:
        try:
            s.lots_count = len(json.loads(s.lots_json or "[]"))
        except Exception:
            s.lots_count = 0
        try:
            photo_paths = json.loads(s.photos_json or "[]")
            s.photo_paths = [p for p in photo_paths if isinstance(p, str) and p.strip()]
        except Exception:
            s.photo_paths = []
        try:
            supplier_paths = json.loads(s.supplier_photos_json or "[]")
            s.supplier_photo_paths = [p for p in supplier_paths if isinstance(p, str) and p.strip()]
        except Exception:
            s.supplier_photo_paths = []
        try:
            biomass_paths = json.loads(s.biomass_photos_json or "[]")
            s.biomass_photo_paths = [p for p in biomass_paths if isinstance(p, str) and p.strip()]
        except Exception:
            s.biomass_photo_paths = []
        try:
            coa_paths = json.loads(s.coa_photos_json or "[]")
            s.coa_photo_paths = [p for p in coa_paths if isinstance(p, str) and p.strip()]
        except Exception:
            s.coa_photo_paths = []

    # One-time display after creating a field link (POST-redirect-GET)
    last_field_link = session.pop("last_field_link", None)
    last_field_sms = session.pop("last_field_sms", None)
    last_field_email_subject = session.pop("last_field_email_subject", None)
    last_field_email_body = session.pop("last_field_email_body", None)

    return render_template(
        "settings.html",
        system_settings=system_settings,
        slack_sync_slots=slack_sync_slots,
        kpis=kpis,
        users=users,
        field_tokens=field_tokens,
        field_submissions=pending_field_submissions,
        reviewed_field_submissions=reviewed_field_submissions,
        server_now=datetime.utcnow(),
        last_field_link=last_field_link,
        last_field_sms=last_field_sms,
        last_field_email_subject=last_field_email_subject,
        last_field_email_body=last_field_email_body,
    )


def _settings_redirect():
    anchor = (request.form.get("return_to") or request.args.get("return_to") or "").strip()
    target = url_for("settings")
    if anchor:
        if not anchor.startswith("#"):
            anchor = f"#{anchor.lstrip('#')}"
        target = f"{target}{anchor}"
    return redirect(target)


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
        return _settings_redirect()

    # Prevent self-disable (avoid locking yourself out)
    if current_user.id == u.id:
        flash("You cannot disable your own account.", "error")
        return _settings_redirect()

    # Prevent disabling the last active super admin
    if u.role == "super_admin" and u.is_active_user:
        active_admins = User.query.filter_by(role="super_admin", is_active_user=True).count()
        if active_admins <= 1:
            flash("You cannot disable the last active Super Admin.", "error")
            return _settings_redirect()

    u.is_active_user = not bool(u.is_active_user)
    log_audit(
        "activate" if u.is_active_user else "deactivate",
        "user",
        u.id,
        details=json.dumps({"username": u.username, "role": u.role}),
    )
    db.session.commit()
    flash(f"User {'activated' if u.is_active_user else 'disabled'}.", "success")
    return _settings_redirect()


@app.route("/settings/field_tokens/new", methods=["POST"])
@admin_required
def field_token_create():
    label = (request.form.get("label") or "").strip()
    if not label:
        flash("Token label is required.", "error")
        return _settings_redirect()

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
    notify_slack(f"Field token created: {label} (expires in {expires_days} days).")
    flash("Field link created. Scroll down to copy/share it.", "success")
    return _settings_redirect()


@app.route("/settings/field_tokens/<token_id>/revoke", methods=["POST"])
@admin_required
def field_token_revoke(token_id):
    tok = db.session.get(FieldAccessToken, token_id)
    if not tok:
        flash("Token not found.", "error")
        return _settings_redirect()
    tok.revoked_at = datetime.utcnow()
    log_audit("revoke", "field_access_token", tok.id, details=json.dumps({"label": tok.label}))
    db.session.commit()
    notify_slack(f"Field token revoked: {tok.label}.")
    flash("Token revoked.", "success")
    return _settings_redirect()


@app.route("/settings/field_tokens/<token_id>/delete", methods=["POST"])
@admin_required
def field_token_delete(token_id):
    tok = db.session.get(FieldAccessToken, token_id)
    if not tok:
        flash("Token not found.", "error")
        return _settings_redirect()
    if tok.revoked_at is None and (tok.expires_at is None or tok.expires_at >= datetime.utcnow()):
        flash("Only revoked or expired tokens can be deleted.", "error")
        return _settings_redirect()
    log_audit("delete", "field_access_token", tok.id, details=json.dumps({"label": tok.label}))
    db.session.delete(tok)
    db.session.commit()
    flash("Token record deleted.", "success")
    return _settings_redirect()


@app.route("/settings/users/<user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id):
    u = db.session.get(User, user_id)
    if not u:
        flash("User not found.", "error")
        return _settings_redirect()
    if current_user.id == u.id:
        flash("You cannot delete your own account.", "error")
        return _settings_redirect()
    if u.role == "super_admin":
        active_admins = User.query.filter_by(role="super_admin", is_active_user=True).count()
        if u.is_active_user and active_admins <= 1:
            flash("You cannot delete the last active Super Admin.", "error")
            return _settings_redirect()
    has_audit = AuditLog.query.filter_by(user_id=u.id).first() is not None
    if has_audit:
        flash("User has historical activity and cannot be hard-deleted. Disable instead.", "error")
        return _settings_redirect()
    log_audit("delete", "user", u.id, details=json.dumps({"username": u.username, "role": u.role}))
    db.session.delete(u)
    db.session.commit()
    flash("User permanently deleted.", "success")
    return _settings_redirect()


@app.route("/settings/field_submissions/<submission_id>/approve", methods=["POST"])
@admin_required
def field_submission_approve(submission_id):
    sub = db.session.get(FieldPurchaseSubmission, submission_id)
    if not sub:
        flash("Submission not found.", "error")
        return _settings_redirect()
    if sub.status != "pending":
        flash("Submission has already been reviewed.", "error")
        return _settings_redirect()

    try:
        lots = json.loads(sub.lots_json or "[]")
    except Exception:
        lots = []

    total_weight = sum(float(l.get("weight_lbs") or 0) for l in lots if (l.get("weight_lbs") is not None))
    if total_weight < 0:
        flash("Submission lot weights are invalid.", "error")
        return _settings_redirect()

    purchase = Purchase(
        supplier_id=sub.supplier_id,
        purchase_date=sub.purchase_date,
        delivery_date=sub.delivery_date,
        harvest_date=sub.harvest_date,
        status="committed",
        stated_weight_lbs=(total_weight if total_weight > 0 else 0.0),
        stated_potency_pct=sub.estimated_potency_pct,
        price_per_lb=sub.price_per_lb,
        storage_note=sub.storage_note,
        license_info=sub.license_info,
        queue_placement=sub.queue_placement,
        coa_status_text=sub.coa_status_text,
        notes=(sub.notes or "") + (f"\n\nApproved from field submission {sub.id}" if sub.notes else f"Approved from field submission {sub.id}"),
    )
    db.session.add(purchase)
    db.session.flush()

    # Create lots
    for l in lots:
        strain = (l.get("strain") or "").strip()
        weight_val = l.get("weight_lbs")
        w = float(weight_val) if weight_val is not None else 0.0
        if w <= 0:
            continue
        lot = PurchaseLot(
            purchase_id=purchase.id,
            strain_name=(strain or "Unspecified"),
            weight_lbs=w,
            remaining_weight_lbs=w,
        )
        db.session.add(lot)

    # Generate batch id
    sup = db.session.get(Supplier, purchase.supplier_id)
    supplier_name = sup.name if sup else "BATCH"
    d = purchase.delivery_date or purchase.purchase_date
    purchase.batch_id = _ensure_unique_batch_id(
        _generate_batch_id(supplier_name, d, (total_weight if total_weight > 0 else 0.0)),
        exclude_purchase_id=purchase.id
    )

    # Total cost if possible
    if purchase.price_per_lb:
        purchase.total_cost = purchase.stated_weight_lbs * purchase.price_per_lb

    supplier_photo_paths = _json_paths(sub.supplier_photos_json)
    biomass_photo_paths = _json_paths(sub.biomass_photos_json)
    coa_photo_paths = _json_paths(sub.coa_photos_json)
    if not supplier_photo_paths and not biomass_photo_paths and not coa_photo_paths:
        # Backward compatibility: older submissions only had a single photos_json bucket.
        biomass_photo_paths = _json_paths(sub.photos_json)

    # Promote supplier/license photos into supplier record docs.
    for path in supplier_photo_paths:
        if not _supplier_attachment_exists(supplier_id=sub.supplier_id, file_path=path):
            db.session.add(SupplierAttachment(
                supplier_id=sub.supplier_id,
                document_type="license",
                title=f"Field submission {sub.id} supplier doc",
                file_path=path,
                uploaded_by=current_user.id,
            ))
        if not _photo_asset_exists(
            file_path=path,
            source_type="field_submission",
            category="supplier_license",
            submission_id=sub.id,
            supplier_id=sub.supplier_id,
            purchase_id=purchase.id,
        ):
            _create_photo_asset(
                path,
                source_type="field_submission",
                category="supplier_license",
                tags=["field", "supplier", "license"],
                title=f"Field submission {sub.id}",
                supplier_id=sub.supplier_id,
                purchase_id=purchase.id,
                submission_id=sub.id,
                uploaded_by=current_user.id,
            )

    # Keep biomass and COA photos attached to purchase audit trail.
    for path in biomass_photo_paths:
        if not _photo_asset_exists(
            file_path=path,
            source_type="field_submission",
            category="biomass",
            submission_id=sub.id,
            supplier_id=sub.supplier_id,
            purchase_id=purchase.id,
        ):
            _create_photo_asset(
                path,
                source_type="field_submission",
                category="biomass",
                tags=["field", "purchase", "biomass", "audit"],
                title=f"Purchase audit biomass photo ({sub.id})",
                supplier_id=sub.supplier_id,
                purchase_id=purchase.id,
                submission_id=sub.id,
                uploaded_by=current_user.id,
            )
    for path in coa_photo_paths:
        if not _photo_asset_exists(
            file_path=path,
            source_type="field_submission",
            category="coa",
            submission_id=sub.id,
            supplier_id=sub.supplier_id,
            purchase_id=purchase.id,
        ):
            _create_photo_asset(
                path,
                source_type="field_submission",
                category="coa",
                tags=["field", "purchase", "coa", "audit"],
                title=f"Purchase audit COA photo ({sub.id})",
                supplier_id=sub.supplier_id,
                purchase_id=purchase.id,
                submission_id=sub.id,
                uploaded_by=current_user.id,
            )

    # Mark submission approved
    sub.status = "approved"
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by = current_user.id
    sub.review_notes = (request.form.get("review_notes") or "").strip() or None
    sub.approved_purchase_id = purchase.id

    log_audit("approve", "field_purchase_submission", sub.id, details=json.dumps({"purchase_id": purchase.id}))
    log_audit("create", "purchase", purchase.id, details=json.dumps({"source": "field_submission", "submission_id": sub.id}))
    db.session.commit()
    notify_slack(f"Field submission approved for {sub.supplier.name if sub.supplier else 'supplier'}; purchase {purchase.batch_id or purchase.id} created.")
    flash("Submission approved and converted to a Purchase.", "success")
    return redirect(url_for("purchase_edit", purchase_id=purchase.id))


@app.route("/settings/field_submissions/<submission_id>/reject", methods=["POST"])
@admin_required
def field_submission_reject(submission_id):
    sub = db.session.get(FieldPurchaseSubmission, submission_id)
    if not sub:
        flash("Submission not found.", "error")
        return _settings_redirect()
    if sub.status != "pending":
        flash("Submission has already been reviewed.", "error")
        return _settings_redirect()
    sub.status = "rejected"
    sub.reviewed_at = datetime.utcnow()
    sub.reviewed_by = current_user.id
    sub.review_notes = (request.form.get("review_notes") or "").strip() or None
    log_audit("reject", "field_purchase_submission", sub.id, details=json.dumps({"notes": sub.review_notes}))
    db.session.commit()
    notify_slack(f"Field submission rejected for {sub.supplier.name if sub.supplier else 'supplier'}.")
    flash("Submission rejected.", "success")
    return _settings_redirect()


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
    return _settings_redirect()


@app.route("/settings/backfill_photo_assets", methods=["POST"])
@admin_required
def settings_backfill_photo_assets():
    """
    One-time backfill for historical approved field submissions:
    - supplier/license photos -> SupplierAttachment + PhotoAsset
    - biomass/COA photos -> PhotoAsset linked to purchase for audit
    """
    try:
        submissions = FieldPurchaseSubmission.query.filter(
            FieldPurchaseSubmission.status == "approved",
            FieldPurchaseSubmission.approved_purchase_id.isnot(None),
        ).all()

        supplier_attachments_added = 0
        assets_added = 0
        touched_submissions = 0

        for sub in submissions:
            supplier_id = sub.supplier_id
            purchase_id = sub.approved_purchase_id
            if not supplier_id or not purchase_id:
                continue

            supplier_photo_paths = _json_paths(sub.supplier_photos_json)
            biomass_photo_paths = _json_paths(sub.biomass_photos_json)
            coa_photo_paths = _json_paths(sub.coa_photos_json)
            if not supplier_photo_paths and not biomass_photo_paths and not coa_photo_paths:
                biomass_photo_paths = _json_paths(sub.photos_json)

            changed = False

            for path in supplier_photo_paths:
                if not _supplier_attachment_exists(supplier_id=supplier_id, file_path=path):
                    db.session.add(SupplierAttachment(
                        supplier_id=supplier_id,
                        document_type="license",
                        title=f"Field submission {sub.id} supplier doc",
                        file_path=path,
                        uploaded_by=current_user.id,
                    ))
                    supplier_attachments_added += 1
                    changed = True
                if not _photo_asset_exists(
                    file_path=path,
                    source_type="field_submission",
                    category="supplier_license",
                    submission_id=sub.id,
                    supplier_id=supplier_id,
                    purchase_id=purchase_id,
                ):
                    _create_photo_asset(
                        path,
                        source_type="field_submission",
                        category="supplier_license",
                        tags=["field", "supplier", "license"],
                        title=f"Field submission {sub.id}",
                        supplier_id=supplier_id,
                        purchase_id=purchase_id,
                        submission_id=sub.id,
                        uploaded_by=current_user.id,
                    )
                    assets_added += 1
                    changed = True

            for path in biomass_photo_paths:
                if not _photo_asset_exists(
                    file_path=path,
                    source_type="field_submission",
                    category="biomass",
                    submission_id=sub.id,
                    supplier_id=supplier_id,
                    purchase_id=purchase_id,
                ):
                    _create_photo_asset(
                        path,
                        source_type="field_submission",
                        category="biomass",
                        tags=["field", "purchase", "biomass", "audit"],
                        title=f"Purchase audit biomass photo ({sub.id})",
                        supplier_id=supplier_id,
                        purchase_id=purchase_id,
                        submission_id=sub.id,
                        uploaded_by=current_user.id,
                    )
                    assets_added += 1
                    changed = True

            for path in coa_photo_paths:
                if not _photo_asset_exists(
                    file_path=path,
                    source_type="field_submission",
                    category="coa",
                    submission_id=sub.id,
                    supplier_id=supplier_id,
                    purchase_id=purchase_id,
                ):
                    _create_photo_asset(
                        path,
                        source_type="field_submission",
                        category="coa",
                        tags=["field", "purchase", "coa", "audit"],
                        title=f"Purchase audit COA photo ({sub.id})",
                        supplier_id=supplier_id,
                        purchase_id=purchase_id,
                        submission_id=sub.id,
                        uploaded_by=current_user.id,
                    )
                    assets_added += 1
                    changed = True

            if changed:
                touched_submissions += 1

        db.session.commit()
        flash(
            f"Photo backfill complete. Updated {touched_submissions} submissions, added "
            f"{supplier_attachments_added} supplier attachment(s) and {assets_added} photo asset(s).",
            "success",
        )
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Photo backfill failed")
        flash(f"Photo backfill failed: {e}", "error")
    return _settings_redirect()


@app.route("/settings/slack_sync_channel", methods=["POST"])
@admin_required
def settings_slack_sync_channel():
    """
    Pull conversations.history for each configured sync channel (max 6).
    First run for a channel uses a rolling window (sync_days); later runs use per-channel watermark ts.
    """
    token = _slack_bot_token()
    if not token:
        flash("Set Bot Token in Slack settings first.", "error")
        return _settings_redirect()
    days_raw = (request.form.get("sync_days") or "90").strip()
    try:
        days = int(days_raw)
    except ValueError:
        days = 90
    days = max(1, min(365, days))
    oldest_window = str(time.time() - days * 86400)
    try:
        _ensure_slack_sync_configs()
        configs = [
            c for c in SlackChannelSyncConfig.query.order_by(SlackChannelSyncConfig.slot_index).all()
            if (c.channel_hint or "").strip()
        ]
        if not configs:
            flash(
                "No channels configured for history sync. Under Settings → Slack Integration, fill in at least one "
                "channel (e.g. #biomass-intake) in Channel history sync and save.",
                "error",
            )
            return _settings_redirect()
        total_new = 0
        total_scanned = 0
        errors: list[str] = []
        audit_channels: list[dict] = []
        for cfg in configs:
            hint = cfg.channel_hint.strip()
            channel_id = _slack_resolve_channel_id(token, hint)
            if not channel_id:
                errors.append(hint)
                continue
            cfg.resolved_channel_id = channel_id
            oldest = (cfg.last_watermark_ts or "").strip() or oldest_window
            new_rows, scanned, max_ts_seen, err = _slack_ingest_channel_history(
                token, channel_id, oldest, current_user.id,
            )
            if err:
                errors.append(f"{hint}:{err}")
                db.session.commit()
                continue
            total_new += new_rows
            total_scanned += scanned
            if max_ts_seen:
                cfg.last_watermark_ts = max_ts_seen
            elif not (cfg.last_watermark_ts or "").strip():
                cfg.last_watermark_ts = str(time.time())
            db.session.commit()
            audit_channels.append({
                "hint": hint,
                "channel_id": channel_id,
                "new": new_rows,
                "scanned": scanned,
            })
        if errors and not audit_channels:
            flash(
                "Could not sync any channel. Check names or IDs, invite the bot, and add OAuth scopes "
                "channels:history, channels:read (private: groups:history, groups:read). "
                f"Details: {', '.join(errors)}",
                "error",
            )
            return _settings_redirect()
        log_audit(
            "slack_channel_sync",
            "slack",
            "multi",
            details=json.dumps({"days": days, "new": total_new, "scanned": total_scanned, "channels": audit_channels, "errors": errors}),
        )
        msg = (
            f"Slack sync: {total_new} new message(s) saved, {total_scanned} row(s) seen "
            f"across {len(audit_channels)} channel(s)."
        )
        if errors:
            msg += " Could not sync: " + "; ".join(errors) + "."
        msg += " Open Slack imports to review parsed fields."
        flash(msg, "success")
    except urllib.error.HTTPError as e:
        db.session.rollback()
        flash(f"Slack HTTP error: {e}", "error")
    except Exception as e:
        db.session.rollback()
        app.logger.exception("Slack channel sync failed")
        flash(f"Slack sync failed: {e}", "error")
    return _settings_redirect()


@app.route("/settings/slack-imports")
@admin_required
def settings_slack_imports():
    rows = SlackIngestedMessage.query.order_by(
        desc(SlackIngestedMessage.message_ts),
    ).limit(400).all()
    for r in rows:
        try:
            r.derived = json.loads(r.derived_json) if r.derived_json else {}
        except Exception:
            r.derived = {}
    return render_template("slack_imports.html", rows=rows)


@app.route("/api/slack/events", methods=["POST"])
def slack_events():
    """
    Slack Events API: URL verification challenge and event callbacks.
    Request URL: https://<your-host>/api/slack/events
    Uses the same signing secret as slash commands (Settings → Slack).
    """
    if not _verify_slack_signature(request):
        return "Unauthorized", 401
    payload = request.get_json(silent=True) or {}
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload.get("challenge") or ""})
    if payload.get("type") == "event_callback":
        # Acknowledge immediately; extend here to process message.* events.
        return "", 200
    return "", 200


@app.route("/api/slack/command", methods=["POST"])
def slack_command():
    if not _verify_slack_signature(request):
        return "Unauthorized", 401
    cmd_text = (request.form.get("text") or "").strip().lower()
    if cmd_text.startswith("pending"):
        pending = FieldPurchaseSubmission.query.filter_by(status="pending").count()
        return jsonify({"response_type": "ephemeral", "text": f"Pending field submissions: {pending}"})
    if cmd_text.startswith("inventory"):
        on_hand = db.session.query(func.sum(PurchaseLot.remaining_weight_lbs)).join(Purchase).filter(
            PurchaseLot.remaining_weight_lbs > 0,
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            Purchase.status.in_(("delivered", "in_testing", "available", "processing", "complete")),
        ).scalar() or 0
        return jsonify({"response_type": "ephemeral", "text": f"Current biomass on hand: {on_hand:,.1f} lbs"})
    if cmd_text.startswith("export runs"):
        link = url_for("export_csv", entity="runs", _external=True)
        return jsonify({"response_type": "ephemeral", "text": f"Runs export: {link}"})
    return jsonify({"response_type": "ephemeral", "text": "Try: pending, inventory, export runs"})


@app.route("/api/slack/interactivity", methods=["POST"])
def slack_interactivity():
    if not _verify_slack_signature(request):
        return "Unauthorized", 401
    payload_raw = (request.form.get("payload") or "").strip()
    if not payload_raw:
        return "OK", 200
    try:
        payload = json.loads(payload_raw)
    except json.JSONDecodeError:
        return "OK", 200
    action = ((payload.get("actions") or [{}])[0].get("action_id") or "").strip()
    submission_id = ((payload.get("actions") or [{}])[0].get("value") or "").strip()
    if action in ("approve_submission", "reject_submission") and submission_id:
        # Slack-triggered review logs an audit event; web UI handles full conversion workflow.
        log_audit("slack_action", "field_purchase_submission", submission_id, details=json.dumps({"action": action}))
        db.session.commit()
    return "OK", 200


# ── CSV Import/Export ────────────────────────────────────────────────────────

@app.route("/export/<entity>")
@login_required
def export_csv(entity):
    """Export data as CSV."""
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    status_filter = (request.args.get("status") or "").strip()
    supplier_id = (request.args.get("supplier_id") or "").strip()
    strain_filter = (request.args.get("strain") or "").strip().lower()
    min_pot_raw = (request.args.get("min_potency") or "").strip()
    max_pot_raw = (request.args.get("max_potency") or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        return "Invalid date filter.", 400
    try:
        min_pot = float(min_pot_raw) if min_pot_raw else None
        max_pot = float(max_pot_raw) if max_pot_raw else None
    except ValueError:
        return "Invalid potency filter.", 400

    si = io.StringIO()
    writer = csv.writer(si)

    if entity == "runs":
        writer.writerow(["Date", "Reactor", "Rollover", "Source", "Lbs Ran", "Grams Ran",
                         "Wet HTE", "Wet THCA", "Dry HTE", "Dry THCA", "Overall Yield %",
                         "THCA Yield %", "HTE Yield %", "Cost/Gram", "Notes"])
        q = Run.query.filter(Run.deleted_at.is_(None))
        if start_date:
            q = q.filter(Run.run_date >= start_date)
        if end_date:
            q = q.filter(Run.run_date <= end_date)
        if min_pot is not None:
            q = q.filter(Run.thca_yield_pct >= min_pot)
        if max_pot is not None:
            q = q.filter(Run.thca_yield_pct <= max_pot)
        if supplier_id or strain_filter:
            q = q.join(RunInput, Run.id == RunInput.run_id).join(PurchaseLot, RunInput.lot_id == PurchaseLot.id
            ).join(Purchase, PurchaseLot.purchase_id == Purchase.id)
            q = q.filter(PurchaseLot.deleted_at.is_(None), Purchase.deleted_at.is_(None))
            if supplier_id:
                q = q.filter(Purchase.supplier_id == supplier_id)
            if strain_filter:
                q = q.filter(func.lower(PurchaseLot.strain_name).like(f"%{strain_filter}%"))
            q = q.distinct()
        for r in q.order_by(Run.run_date.desc()).all():
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
        q = Purchase.query.filter(Purchase.deleted_at.is_(None))
        if start_date:
            q = q.filter(Purchase.purchase_date >= start_date)
        if end_date:
            q = q.filter(Purchase.purchase_date <= end_date)
        if status_filter:
            q = q.filter(Purchase.status == status_filter)
        if supplier_id:
            q = q.filter(Purchase.supplier_id == supplier_id)
        if min_pot is not None:
            q = q.filter(Purchase.stated_potency_pct >= min_pot)
        if max_pot is not None:
            q = q.filter(Purchase.stated_potency_pct <= max_pot)
        for p in q.order_by(Purchase.purchase_date.desc()).all():
            strains = ", ".join([l.strain_name for l in p.lots])
            writer.writerow([p.purchase_date, p.batch_id, p.supplier_name, p.status,
                             p.stated_weight_lbs, p.actual_weight_lbs,
                             p.stated_potency_pct, p.tested_potency_pct,
                             p.price_per_lb, p.total_cost, p.true_up_amount, strains])
    elif entity == "inventory":
        writer.writerow(["Strain", "Supplier", "Weight (lbs)", "Remaining (lbs)",
                         "Potency %", "Milled", "Location"])
        q = PurchaseLot.query.join(Purchase).filter(
            PurchaseLot.remaining_weight_lbs > 0,
            PurchaseLot.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
        )
        if supplier_id:
            q = q.filter(Purchase.supplier_id == supplier_id)
        if strain_filter:
            q = q.filter(func.lower(PurchaseLot.strain_name).like(f"%{strain_filter}%"))
        for l in q.all():
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
        q = BiomassAvailability.query.join(Supplier)
        if start_date:
            q = q.filter(BiomassAvailability.availability_date >= start_date)
        if end_date:
            q = q.filter(BiomassAvailability.availability_date <= end_date)
        if status_filter:
            q = q.filter(BiomassAvailability.stage == status_filter)
        if supplier_id:
            q = q.filter(BiomassAvailability.supplier_id == supplier_id)
        if strain_filter:
            q = q.filter(func.lower(BiomassAvailability.strain_name).like(f"%{strain_filter}%"))
        for b in q.order_by(BiomassAvailability.availability_date.desc(), Supplier.name.asc()).all():
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
    elif entity == "suppliers":
        writer.writerow(["Supplier", "Contact", "Phone", "Email", "Location", "Active"])
        q = Supplier.query
        if supplier_id:
            q = q.filter(Supplier.id == supplier_id)
        for s in q.order_by(Supplier.name.asc()).all():
            writer.writerow([s.name, s.contact_name or "", s.contact_phone or "", s.contact_email or "", s.location or "", s.is_active])
    elif entity == "strains":
        writer.writerow(["Strain", "Supplier", "Avg Yield %", "Avg THCA %", "Avg HTE %", "Avg $/g", "Runs", "Total Lbs"])
        q = db.session.query(
            PurchaseLot.strain_name,
            Supplier.name.label("supplier_name"),
            func.avg(Run.overall_yield_pct).label("avg_yield"),
            func.avg(Run.thca_yield_pct).label("avg_thca"),
            func.avg(Run.hte_yield_pct).label("avg_hte"),
            func.avg(Run.cost_per_gram_combined).label("avg_cpg"),
            func.count(Run.id).label("run_count"),
            func.sum(Run.bio_in_reactor_lbs).label("total_lbs"),
        ).join(RunInput, PurchaseLot.id == RunInput.lot_id
        ).join(Run, RunInput.run_id == Run.id
        ).join(Purchase, PurchaseLot.purchase_id == Purchase.id
        ).join(Supplier, Purchase.supplier_id == Supplier.id
        ).filter(
            Run.deleted_at.is_(None),
            Purchase.deleted_at.is_(None),
            PurchaseLot.deleted_at.is_(None),
        )
        if start_date:
            q = q.filter(Run.run_date >= start_date)
        if end_date:
            q = q.filter(Run.run_date <= end_date)
        if supplier_id:
            q = q.filter(Purchase.supplier_id == supplier_id)
        if strain_filter:
            q = q.filter(func.lower(PurchaseLot.strain_name).like(f"%{strain_filter}%"))
        for r in q.group_by(PurchaseLot.strain_name, Supplier.name).order_by(desc("avg_yield")).all():
            writer.writerow([r.strain_name, r.supplier_name, r.avg_yield, r.avg_thca, r.avg_hte, r.avg_cpg, r.run_count, r.total_lbs])
    elif entity == "costs":
        writer.writerow(["Type", "Name", "Start Date", "End Date", "Total Cost", "Unit Cost", "Qty", "Unit", "Notes"])
        q = CostEntry.query
        if start_date:
            q = q.filter(CostEntry.end_date >= start_date)
        if end_date:
            q = q.filter(CostEntry.start_date <= end_date)
        if status_filter:
            q = q.filter(CostEntry.cost_type == status_filter)
        for c in q.order_by(CostEntry.start_date.desc()).all():
            writer.writerow([c.cost_type, c.name, c.start_date, c.end_date, c.total_cost, c.unit_cost, c.quantity, c.unit, c.notes or ""])
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
    if not purchase or purchase.deleted_at is not None:
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
    start_raw = (request.args.get("start_date") or "").strip()
    end_raw = (request.args.get("end_date") or "").strip()
    supplier_filter = (request.args.get("supplier_id") or "").strip()
    strain_filter = (request.args.get("strain") or "").strip()
    try:
        start_date = datetime.strptime(start_raw, "%Y-%m-%d").date() if start_raw else None
        end_date = datetime.strptime(end_raw, "%Y-%m-%d").date() if end_raw else None
    except ValueError:
        start_date = None
        end_date = None
    query = BiomassAvailability.query.join(Supplier)
    if stage:
        query = query.filter(BiomassAvailability.stage == stage)
    if start_date:
        query = query.filter(BiomassAvailability.availability_date >= start_date)
    if end_date:
        query = query.filter(BiomassAvailability.availability_date <= end_date)
    if supplier_filter:
        query = query.filter(BiomassAvailability.supplier_id == supplier_filter)
    if strain_filter:
        query = query.filter(func.lower(BiomassAvailability.strain_name).like(f"%{strain_filter.lower()}%"))
    items = query.order_by(BiomassAvailability.availability_date.desc(), Supplier.name.asc()).all()
    suppliers = Supplier.query.filter_by(is_active=True).order_by(Supplier.name).all()
    return render_template(
        "biomass.html",
        items=items,
        stage_filter=stage,
        suppliers=suppliers,
        supplier_filter=supplier_filter,
        start_date=start_raw,
        end_date=end_raw,
        strain_filter=strain_filter,
    )


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
    lots = PurchaseLot.query.join(Purchase).filter(
        PurchaseLot.remaining_weight_lbs > 0,
        PurchaseLot.deleted_at.is_(None),
        Purchase.deleted_at.is_(None),
    ).all()
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
    # Each Gunicorn worker imports this module and runs init_db(); concurrent create_all()
    # races on new tables (e.g. slack_ingested_messages). Treat harmless DDL conflicts as OK.
    try:
        db.create_all()
    except (OperationalError, ProgrammingError) as e:
        db.session.rollback()
        err_txt = str(getattr(e, "orig", None) or e).lower()
        if "already exists" not in err_txt and "duplicate" not in err_txt:
            raise
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
