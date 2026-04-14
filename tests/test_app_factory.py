from __future__ import annotations

import unittest

import app as app_module
import gold_drop.biomass_module as biomass_module
import gold_drop.bootstrap_module as bootstrap_module
import gold_drop.costs_module as costs_module
import gold_drop.dashboard_module as dashboard_module
import gold_drop.field_intake_module as field_intake_module
import gold_drop.inventory_module as inventory_module
import gold_drop.batch_edit_module as batch_edit_module
import gold_drop.purchases_module as purchases_module
import gold_drop.purchase_import_module as purchase_import_module
import gold_drop.runs_module as runs_module
import gold_drop.settings_module as settings_module
import gold_drop.strains_module as strains_module
import gold_drop.suppliers_module as suppliers_module


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
        self.assertIn("/runs", rules)
        self.assertIn("/", rules)
        self.assertIn("/field", rules)
        self.assertIn("/biomass-purchasing", rules)
        self.assertIn("/suppliers", rules)
        self.assertIn("/photos", rules)
        self.assertIn("/purchases/import", rules)
        self.assertIn("/costs", rules)
        self.assertIn("/inventory", rules)
        self.assertIn("/batch-edit/<entity>", rules)
        self.assertIn("/strains", rules)
        self.assertIn("/api/slack/events", rules)
        self.assertIn("/api/v1/site", rules)
        self.assertIn("/api/v1/purchases", rules)
        self.assertIn("/api/v1/runs", rules)
        self.assertIn("/api/v1/lots", rules)
        self.assertIn("/api/v1/inventory/on-hand", rules)
        self.assertIn("/settings/slack-imports", rules)
        self.assertIn("/settings/slack-run-mappings", rules)

    def test_extracted_route_modules_import(self) -> None:
        self.assertTrue(hasattr(settings_module, "settings_view"))
        self.assertTrue(hasattr(purchases_module, "purchases_list_view"))
        self.assertTrue(hasattr(biomass_module, "biomass_list_view"))
        self.assertTrue(hasattr(runs_module, "runs_list_view"))
        self.assertTrue(hasattr(dashboard_module, "dashboard_view"))
        self.assertTrue(hasattr(field_intake_module, "field_home_view"))
        self.assertTrue(hasattr(costs_module, "costs_list_view"))
        self.assertTrue(hasattr(inventory_module, "inventory_view"))
        self.assertTrue(hasattr(batch_edit_module, "batch_edit_view"))
        self.assertTrue(hasattr(suppliers_module, "suppliers_list_view"))
        self.assertTrue(hasattr(purchase_import_module, "purchase_import_view"))
        self.assertTrue(hasattr(strains_module, "strains_list_view"))
        self.assertTrue(hasattr(bootstrap_module, "init_db"))

    def test_changed_flow_routes_require_auth_instead_of_404(self) -> None:
        client = app_module.app.test_client()
        for path in ("/", "/biomass-purchasing", "/runs", "/runs/new", "/purchases", "/purchases/new", "/purchases/import", "/suppliers", "/photos", "/biomass", "/biomass/new", "/costs", "/inventory", "/strains", "/settings"):
            response = client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 302, path)
            self.assertIn("/login", response.headers.get("Location", ""), path)


if __name__ == "__main__":
    unittest.main()
