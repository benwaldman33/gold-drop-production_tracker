from __future__ import annotations

import unittest

import app as app_module
import gold_drop.biomass_module as biomass_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.purchases_module as purchases_module
import gold_drop.settings_module as settings_module


class AppFactorySmokeTest(unittest.TestCase):
    def test_create_app_returns_flask_app(self) -> None:
        fresh = app_module.create_app()
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.import_name, app_module.app.import_name)
        with fresh.app_context():
            rules = {rule.rule for rule in fresh.url_map.iter_rules()}
        self.assertIn("/settings", rules)
        self.assertIn("/purchases", rules)
        self.assertIn("/biomass", rules)

    def test_core_routes_registered(self) -> None:
        app = app_module.app
        with app.app_context():
            rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn("/settings", rules)
        self.assertIn("/purchases", rules)
        self.assertIn("/biomass", rules)
        self.assertIn("/api/slack/events", rules)

    def test_extracted_route_modules_import(self) -> None:
        self.assertTrue(hasattr(settings_module, "settings_view"))
        self.assertTrue(hasattr(purchases_module, "purchases_list_view"))
        self.assertTrue(hasattr(biomass_module, "biomass_list_view"))
        self.assertTrue(hasattr(bootstrap_module, "init_db"))

    def test_changed_flow_routes_require_auth_instead_of_404(self) -> None:
        client = app_module.app.test_client()
        for path in ("/purchases", "/purchases/new", "/biomass", "/biomass/new", "/settings"):
            response = client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/login", response.headers.get("Location", ""), path)


if __name__ == "__main__":
    unittest.main()
