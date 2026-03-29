"""Unit tests for Slack mapping validation and Run preview filtering (no Flask render)."""

import unittest

import app as app_module


class SlackMappingLogicTest(unittest.TestCase):
    def test_preview_non_run_consumes_derived_key(self) -> None:
        rules = [
            {
                "message_kinds": [],
                "source_key": "strain",
                "target_field": "notes_hint",
                "destination": "biomass",
                "transform": {"type": "passthrough"},
            },
            {
                "message_kinds": [],
                "source_key": "bio_lbs",
                "target_field": "bio_in_reactor_lbs",
                "transform": {"type": "to_float"},
            },
        ]
        derived = {"strain": "Blue Dream", "bio_lbs": "10"}
        preview = app_module._preview_slack_to_run_fields(derived, "1234.567", "yield_report", rules)
        self.assertNotIn("strain", preview["unmapped_keys"])
        self.assertEqual(preview["filled"].get("bio_in_reactor_lbs"), 10.0)

    def test_validate_rejects_non_snake_non_run_target(self) -> None:
        bad = [{
            "message_kinds": [],
            "source_key": "strain",
            "target_field": "BadCamel",
            "destination": "biomass",
            "transform": {"type": "passthrough"},
        }]
        with self.assertRaises(ValueError):
            app_module._validate_slack_run_field_rules(bad)


if __name__ == "__main__":
    unittest.main()
