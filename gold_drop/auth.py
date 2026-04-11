from __future__ import annotations

from functools import wraps

from flask import flash, redirect, url_for
from flask_login import LoginManager, current_user, login_required

from models import User, db

login_manager = LoginManager()
login_manager.login_view = "login"


@login_manager.user_loader
def load_user(user_id):
    u = db.session.get(User, user_id)
    if u and not getattr(u, "is_active_user", True):
        return None
    return u


def init_app(app):
    login_manager.init_app(app)


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


def slack_importer_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_slack_import:
            flash("Slack import access is not enabled for your account.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated


def field_purchase_approval_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_approve_field_purchases:
            flash("Field purchase approval access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated


def purchase_editor_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.can_edit_purchases:
            flash("Purchase edit access required.", "error")
            return redirect(url_for("dashboard"))
        return f(*args, **kwargs)

    return decorated

