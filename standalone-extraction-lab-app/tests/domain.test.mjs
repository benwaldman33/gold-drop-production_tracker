import test from "node:test";
import assert from "node:assert/strict";
import { clampChargeWeight, halfLotChargeWeight, lotTitle, normalizeText, preferredChargeWeight, readyLotCount, stateTone } from "../src/domain.js";
import { defaultChargeValue, defaultReactorValue, parseRoute } from "../src/ui-helpers.js";

test("normalizeText trims and lowercases", () => {
  assert.equal(normalizeText("  Reactor   Bay "), "reactor bay");
});

test("parseRoute understands charge screen and board filter", () => {
  assert.deepEqual(parseRoute("#/lots/abc123/charge"), { name: "charge", id: "abc123" });
  assert.deepEqual(parseRoute("#/reactors?board_view=running"), { name: "reactors", boardView: "running" });
  assert.deepEqual(parseRoute("#/scan"), { name: "scan" });
  assert.deepEqual(parseRoute("#/runs/charge/chg-123"), { name: "run", chargeId: "chg-123" });
});

test("clampChargeWeight respects bounds and tenth-pound rounding", () => {
  assert.equal(clampChargeWeight("12.34", 20), 12.3);
  assert.equal(clampChargeWeight(25, 20), 20);
  assert.equal(clampChargeWeight(-1, 20), 0);
});

test("preferred charge presets default to 100 lbs and clamp down when needed", () => {
  assert.equal(preferredChargeWeight(150), 100);
  assert.equal(preferredChargeWeight(80), 80);
  assert.equal(defaultChargeValue(200), 100);
  assert.equal(halfLotChargeWeight(85), 42.5);
  assert.equal(defaultReactorValue(2, 3), 2);
  assert.equal(defaultReactorValue(9, 3), 3);
});

test("lotTitle and readiness helpers stay operator-readable", () => {
  assert.equal(lotTitle({ supplier_name: "Forest Farms", strain_name: "Blue Dream" }), "Forest Farms - Blue Dream");
  assert.equal(readyLotCount([{ ready_for_charge: true }, { ready_for_charge: false }, { ready_for_charge: true }]), 2);
  assert.equal(stateTone("cancelled"), "danger");
});
