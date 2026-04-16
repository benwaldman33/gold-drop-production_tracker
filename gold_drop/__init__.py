from __future__ import annotations


def create_app():
    from app import create_app as root_create_app

    return root_create_app()


__all__ = ["create_app"]
