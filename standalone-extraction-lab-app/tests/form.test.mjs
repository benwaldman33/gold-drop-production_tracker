import test from "node:test";
import assert from "node:assert/strict";
import { lastNamedFormValue, namedFormCheckboxValue } from "../src/ui-helpers.js";

test("lastNamedFormValue prefers the last non-empty duplicate field", () => {
  const form = new FormData();
  form.append("primary_solvent_charge_lbs", "");
  form.append("primary_solvent_charge_lbs", "500");
  assert.equal(lastNamedFormValue(form, "primary_solvent_charge_lbs"), "500");
});

test("lastNamedFormValue falls back to earlier values when the last is empty", () => {
  const form = new FormData();
  form.append("chiller_check_actual_temp_c", "-40");
  form.append("chiller_check_actual_temp_c", "");
  assert.equal(lastNamedFormValue(form, "chiller_check_actual_temp_c"), "-40");
});

test("namedFormCheckboxValue returns 1 when any duplicate checkbox is set", () => {
  const form = new FormData();
  form.append("shutdown_nitrogen_off", "");
  form.append("shutdown_nitrogen_off", "1");
  assert.equal(namedFormCheckboxValue(form, "shutdown_nitrogen_off"), "1");
});
