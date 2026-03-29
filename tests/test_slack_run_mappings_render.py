"""
Quick render check for slack_run_mappings.html (Jinja + base layout + tojson).

Run from repo root:
  python -m unittest tests.test_slack_run_mappings_render -v
"""
import json
import unittest

import app as app_module


class SlackRunMappingsTemplateTest(unittest.TestCase):
    def _render(self, rules: list) -> str:
        app = app_module.app
        pretty = json.dumps({"rules": rules}, indent=2)
        kwargs = app_module._slack_run_mappings_template_kwargs(rules, pretty)
        with app.app_context():
            from flask import render_template
            from flask_login import login_user
            from models import User

            user = User.query.filter_by(username="admin").first()
            self.assertIsNotNone(user, "expected seeded admin user (run after init_db)")

            with app.test_request_context("/"):
                login_user(user)
                return render_template("slack_run_mappings.html", **kwargs)

    def test_renders_default_rules_without_error(self) -> None:
        rules = app_module._default_slack_run_field_rules()
        html = self._render(rules)
        self.assertIn("slack-map-rules-tbody", html)
        self.assertIn("slack-mapping-ui-json", html)
        self.assertIn("slack-mapping-help-json", html)
        self.assertIn('"ruleSlotsMax"', html)
        self.assertIn("complete rules + two spare rows", html)

    def test_renders_empty_rules_without_error(self) -> None:
        """Ensures transform_types|list and min grid rows (rule_slots) work."""
        html = self._render([])
        self.assertIn("slack-map-rules-tbody", html)
        self.assertIn("slack-mapping-ui-json", html)
        # rule_slots = max(2, 0+2) => two <tr> rows (substring must exclude JS references)
        self.assertEqual(html.count('<tr class="slack-map-rule-row"'), 2)


if __name__ == "__main__":
    unittest.main()
