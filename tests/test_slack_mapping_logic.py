"""Unit tests for Slack mapping validation and Run preview filtering (no Flask render)."""

import unittest
from unittest.mock import MagicMock, patch

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

    def test_coverage_label_none_when_no_filled(self) -> None:
        self.assertEqual(
            app_module._slack_coverage_label({"filled": {}, "unmapped_keys": ["a"], "missing_recommended": []}),
            "none",
        )

    def test_coverage_label_full(self) -> None:
        self.assertEqual(
            app_module._slack_coverage_label({"filled": {"run_date": "x"}, "unmapped_keys": [], "missing_recommended": []}),
            "full",
        )

    def test_coverage_label_partial(self) -> None:
        self.assertEqual(
            app_module._slack_coverage_label({"filled": {"run_date": "x"}, "unmapped_keys": ["strain"], "missing_recommended": []}),
            "partial",
        )

    def test_derive_timing_labels(self) -> None:
        txt = (
            "End Time: 3:45 PM\n"
            "Mixer Time: 10 min\n"
            "Flush Time Start: 01:15\n"
            "Recovery at: 02:30\n"
            "Flush at: 04:00"
        )
        d = app_module._derive_slack_production_message(txt)
        self.assertEqual(d.get("end_time"), "3:45 PM")
        self.assertEqual(d.get("mixer_time"), "10 min")
        self.assertEqual(d.get("flush_time_start"), "01:15")
        self.assertEqual(d.get("recovery_at"), "02:30")
        self.assertEqual(d.get("flush_at"), "04:00")

    def test_from_iso_date_transform(self) -> None:
        d = app_module._apply_slack_mapping_transform(
            "2026-03-28",
            {"type": "from_iso_date"},
            "",
            "slack_message_date",
        )
        self.assertEqual(d.isoformat() if d else None, "2026-03-28")

    def test_validate_accepts_from_iso_date(self) -> None:
        rules = [
            {
                "message_kinds": [],
                "source_key": "slack_message_date",
                "target_field": "run_date",
                "transform": {"type": "from_iso_date"},
            },
        ]
        app_module._validate_slack_run_field_rules(rules)

    def test_slack_message_date_backfill_in_preview(self) -> None:
        """Preview copies derived and injects slack_message_date from message_ts when absent."""
        rules = [
            {
                "message_kinds": [],
                "source_key": "slack_message_date",
                "target_field": "run_date",
                "transform": {"type": "from_iso_date"},
            },
        ]
        derived = {"message_kind": "unknown"}
        preview = app_module._preview_slack_to_run_fields(derived, "1743200000.000000", "unknown", rules)
        self.assertIn("run_date", preview["filled"])
        self.assertNotIn("slack_message_date", derived)

    def test_needs_resolution_ui(self) -> None:
        self.assertTrue(app_module._slack_message_needs_resolution_ui({"source": "X"}))
        self.assertTrue(app_module._slack_message_needs_resolution_ui({"strain": "Y"}))
        self.assertFalse(app_module._slack_message_needs_resolution_ui({"bio_lbs": 1}))
        self.assertFalse(
            app_module._slack_message_needs_resolution_ui({"message_kind": "biomass_intake", "source": "X", "strain": "Z"}),
        )

    def test_slack_imports_kind_text_filters(self) -> None:
        self.assertTrue(
            app_module._slack_imports_row_matches_kind_text(
                "all", "", "contains", "biomass_intake", "hello",
            )
        )
        self.assertFalse(
            app_module._slack_imports_row_matches_kind_text(
                "biomass_intake", "", "contains", "yield_report", "x",
            )
        )
        self.assertTrue(
            app_module._slack_imports_row_matches_kind_text(
                "biomass_intake", "WORLDWIDE", "contains", "biomass_intake",
                "Source: Worldwide",
            )
        )
        self.assertFalse(
            app_module._slack_imports_row_matches_kind_text(
                "all", "missing", "contains", "unknown", "no such phrase",
            )
        )
        self.assertTrue(
            app_module._slack_imports_row_matches_kind_text(
                "all", "  Hello\n", "equals", "production_log", "  hello\n",
            )
        )
        self.assertTrue(
            app_module._slack_imports_row_matches_kind_text(
                "all", "noise", "not_contains", "unknown", "clean message body",
            )
        )
        self.assertFalse(
            app_module._slack_imports_row_matches_kind_text(
                "all", "Worldwide", "not_contains", "biomass_intake", "Source: Worldwide",
            )
        )

    def test_biomass_intake_derived(self) -> None:
        txt = (
            "Received: 3/18/26\n"
            "Intake: 3/18/26\n"
            "Source: Worldwide\n"
            "Manifest #<tel:0010471676|0010471676>\n"
            "Manifest wt: 365.42 lbs\n"
            "Actual wt: 356 lbs\n"
            "Discrepancy: -9.42 lbs\n"
            "Strain: Luxury Runtz\n"
        )
        d = app_module._derive_slack_production_message(txt)
        self.assertEqual(d.get("message_kind"), "biomass_intake")
        self.assertEqual(d.get("manifest_id_normalized"), "0010471676")
        self.assertAlmostEqual(d.get("manifest_wt_lbs"), 365.42)
        self.assertAlmostEqual(d.get("actual_wt_lbs"), 356.0)
        self.assertEqual(d.get("strain"), "Luxury Runtz")
        self.assertEqual(d.get("source"), "Worldwide")
        self.assertEqual(d.get("intake_received_date"), "2026-03-18")

    def test_default_bio_weight(self) -> None:
        self.assertEqual(app_module._slack_default_bio_weight_lbs({"bio_lbs": 12.5}), 12.5)
        self.assertEqual(app_module._slack_default_bio_weight_lbs({"bio_weight_lbs": 3}), 3.0)

    def test_apply_form_passthrough(self) -> None:
        form = {
            "slack_supplier_mode": "existing",
            "slack_supplier_id": "abc",
            "slack_confirm_fuzzy_supplier": "1",
        }
        d = app_module._slack_apply_form_passthrough(form)
        self.assertEqual(d["slack_supplier_id"], "abc")
        self.assertEqual(d["slack_confirm_fuzzy_supplier"], "1")

    def test_resolution_errors_on_source_without_supplier_choice(self) -> None:
        form = {"slack_supplier_mode": "skip"}
        res, err = app_module._slack_resolution_from_apply_form(
            form,
            derived={"source": "Farm"},
            message_ts="1.0",
        )
        self.assertIsNone(res)
        self.assertIsNotNone(err)

    @patch.object(app_module.db.session, "get")
    def test_resolution_fuzzy_confirm(self, mock_get) -> None:
        sup = MagicMock()
        sup.name = "Other Supplier"
        mock_get.return_value = sup
        form = {
            "slack_supplier_mode": "existing",
            "slack_supplier_id": "sid-1",
        }
        res, err = app_module._slack_resolution_from_apply_form(
            form,
            derived={"source": "My Farm"},
            message_ts="1.0",
        )
        self.assertIsNone(res)
        self.assertIsNotNone(err)
        self.assertIn("Confirm supplier mapping", err or "")
        form["slack_confirm_fuzzy_supplier"] = "1"
        res2, err2 = app_module._slack_resolution_from_apply_form(
            form,
            derived={"source": "My Farm"},
            message_ts="1.0",
        )
        self.assertIsNotNone(res2)
        self.assertIsNone(err2)


if __name__ == "__main__":
    unittest.main()
