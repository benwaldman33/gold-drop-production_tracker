from __future__ import annotations

import app as app_module
from models import RemoteSite, RemoteSitePull, db
from services.site_aggregation import normalize_remote_base_url, pull_remote_site


def test_normalize_remote_base_url_strips_trailing_slash():
    assert normalize_remote_base_url(" https://example.com/api/ ") == "https://example.com/api"


def test_pull_remote_site_caches_latest_payloads_and_records_pull():
    app = app_module.app
    site = RemoteSite(name="Remote Alpha", base_url="https://alpha.example.com/", api_token="secret-token")
    payloads = {
        "https://alpha.example.com/api/v1/site": {"data": {"site_code": "ALPHA", "site_name": "Alpha Site", "site_region": "West", "site_environment": "production"}},
        "https://alpha.example.com/api/v1/sync/manifest": {"data": {"datasets": {"purchases": {"count": 12}}}},
        "https://alpha.example.com/api/v1/summary/dashboard": {"data": {"totals": {"runs": 3}}},
        "https://alpha.example.com/api/v1/summary/inventory": {"data": {"open_lot_count": 4}},
        "https://alpha.example.com/api/v1/summary/exceptions": {"data": {"total": 1}},
        "https://alpha.example.com/api/v1/summary/slack-imports": {"data": {"total_messages": 7}},
    }
    calls = []

    def fake_fetcher(url, token, timeout_seconds):
        calls.append((url, token, timeout_seconds))
        return payloads[url]

    with app.app_context():
        db.session.add(site)
        db.session.commit()

        pull = pull_remote_site(site, fetcher=fake_fetcher, timeout_seconds=5)
        site_id = site.id
        pull_id = pull.id

        db.session.expire_all()
        stored_site = db.session.get(RemoteSite, site_id)
        stored_pull = db.session.get(RemoteSitePull, pull_id)

        assert stored_site.base_url == "https://alpha.example.com"
        assert stored_site.site_code == "ALPHA"
        assert stored_site.site_name == "Alpha Site"
        assert stored_site.last_pull_status == "success"
        assert stored_site.payload("last_dashboard_payload_json") == {"totals": {"runs": 3}}
        assert stored_pull.status == "success"
        assert stored_pull.payload("inventory_payload_json") == {"open_lot_count": 4}
        assert len(calls) == 6
        assert all(token == "secret-token" for _url, token, _timeout in calls)

        db.session.delete(stored_pull)
        db.session.delete(stored_site)
        db.session.commit()


def test_pull_remote_site_marks_failure_and_keeps_error_message():
    app = app_module.app
    site = RemoteSite(name="Remote Beta", base_url="https://beta.example.com", api_token="secret-token")

    def failing_fetcher(url, token, timeout_seconds):
        raise OSError("network down")

    with app.app_context():
        db.session.add(site)
        db.session.commit()

        pull = pull_remote_site(site, fetcher=failing_fetcher)
        site_id = site.id
        pull_id = pull.id

        db.session.expire_all()
        stored_site = db.session.get(RemoteSite, site_id)
        stored_pull = db.session.get(RemoteSitePull, pull_id)

        assert stored_site.last_pull_status == "failed"
        assert "network down" in (stored_site.last_pull_error or "")
        assert stored_pull.status == "failed"
        assert "network down" in (stored_pull.error_message or "")

        db.session.delete(stored_pull)
        db.session.delete(stored_site)
        db.session.commit()
