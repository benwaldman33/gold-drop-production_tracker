"""Blueprint registration for the Flask app factory."""

from __future__ import annotations

from flask import Flask

from blueprints.purchases import bp as purchases_bp


def register_blueprints(app: Flask) -> None:
    """Attach application blueprints to the Flask app."""
    app.register_blueprint(purchases_bp)
