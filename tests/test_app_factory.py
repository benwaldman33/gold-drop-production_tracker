from __future__ import annotations

import unittest

import app as app_module


class AppFactorySmokeTest(unittest.TestCase):
    def test_create_app_returns_flask_app(self) -> None:
        fresh = app_module.create_app()
        self.assertIsNotNone(fresh)
        self.assertEqual(fresh.import_name, app_module.app.import_name)

    def test_core_routes_registered(self) -> None:
        app = app_module.app
        with app.app_context():
            rules = {rule.rule for rule in app.url_map.iter_rules()}
        self.assertIn("/settings", rules)
        self.assertIn("/purchases", rules)
        self.assertIn("/biomass", rules)
        self.assertIn("/api/slack/events", rules)


if __name__ == "__main__":
    unittest.main()
