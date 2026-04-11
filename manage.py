"""CLI entrypoint for migration/admin commands."""

from __future__ import annotations

from flask.cli import FlaskGroup
from flask_migrate import Migrate

from app import create_app
from models import db


app = create_app()
migrate = Migrate(app, db)
cli = FlaskGroup(create_app=create_app)


if __name__ == "__main__":
    cli()
