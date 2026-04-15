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
        self.assertIn("/runs/scale-capture", rules)
        self.assertIn("/", rules)
        self.assertIn("/field", rules)
        self.assertIn("/biomass-purchasing", rules)
        self.assertIn("/cross-site", rules)
        self.assertIn("/suppliers", rules)
        self.assertIn("/photos", rules)
        self.assertIn("/purchases/import", rules)
        self.assertIn("/costs", rules)
        self.assertIn("/inventory", rules)
        self.assertIn("/batch-edit/<entity>", rules)
        self.assertIn("/strains", rules)
        self.assertIn("/api/slack/events", rules)
        self.assertIn("/api/v1/site", rules)
        self.assertIn("/api/v1/capabilities", rules)
        self.assertIn("/api/v1/sync/manifest", rules)
        self.assertIn("/api/v1/aggregation/sites", rules)
        self.assertIn("/api/v1/aggregation/sites/<site_id>", rules)
        self.assertIn("/api/v1/aggregation/summary", rules)
        self.assertIn("/api/v1/aggregation/suppliers", rules)
        self.assertIn("/api/v1/aggregation/strains", rules)
        self.assertIn("/api/v1/search", rules)
        self.assertIn("/api/v1/tools/inventory-snapshot", rules)
        self.assertIn("/api/v1/tools/open-lots", rules)
        self.assertIn("/api/v1/tools/journey-resolve", rules)
        self.assertIn("/api/v1/tools/reconciliation-overview", rules)
        self.assertIn("/api/v1/summary/dashboard", rules)
        self.assertIn("/api/v1/departments", rules)
        self.assertIn("/api/v1/departments/<slug>", rules)
        self.assertIn("/api/v1/purchases", rules)
        self.assertIn("/api/v1/runs", rules)
        self.assertIn("/api/v1/suppliers", rules)
        self.assertIn("/api/v1/strains", rules)
        self.assertIn("/api/v1/lots", rules)
        self.assertIn("/api/v1/lots/<lot_id>/journey", rules)
        self.assertIn("/api/v1/slack-imports", rules)
        self.assertIn("/api/v1/runs/<run_id>/journey", rules)
        self.assertIn("/api/v1/exceptions", rules)
        self.assertIn("/api/v1/scale-devices", rules)
        self.assertIn("/api/v1/weight-captures", rules)
        self.assertIn("/api/v1/scan-events", rules)
        self.assertIn("/api/v1/lots/<lot_id>/scans", rules)
        self.assertIn("/api/v1/summary/inventory", rules)
        self.assertIn("/api/v1/summary/slack-imports", rules)
        self.assertIn("/api/v1/summary/exceptions", rules)
        self.assertIn("/api/v1/summary/scales", rules)
        self.assertIn("/api/v1/summary/scanner", rules)
        self.assertIn("/api/v1/inventory/on-hand", rules)
        self.assertIn("/floor-ops", rules)
        self.assertIn("/scan", rules)
        self.assertIn("/scan/lot/<tracking_id>", rules)
        self.assertIn("/scan/lot/<tracking_id>/start-run", rules)
        self.assertIn("/scan/lot/<tracking_id>/confirm-movement", rules)
        self.assertIn("/scan/lot/<tracking_id>/confirm-testing", rules)
        self.assertIn("/settings/slack-imports", rules)
        self.assertIn("/settings/slack-run-mappings", rules)
        self.assertIn("/settings/api_clients/create", rules)
        self.assertIn("/settings/pull_remote_sites", rules)
        self.assertIn("/settings/scale_devices/create", rules)
        self.assertIn("/settings/scale_devices/<device_id>/test_capture", rules)

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
        for path in ("/", "/biomass-purchasing", "/runs", "/runs/new", "/purchases", "/purchases/new", "/purchases/import", "/suppliers", "/photos", "/biomass", "/biomass/new", "/costs", "/inventory", "/strains", "/settings"):
            client = app_module.app.test_client()
            response = client.get(path, follow_redirects=False)
            self.assertNotEqual(response.status_code, 404, path)
            self.assertNotEqual(response.status_code, 500, path)


if __name__ == "__main__":
    unittest.main()
