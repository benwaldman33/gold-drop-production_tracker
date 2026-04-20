import test from "node:test";
import assert from "node:assert/strict";
import { clampChargeWeight, lotTitle, normalizeText, readyLotCount, stateTone } from "../src/domain.js";
import { parseRoute } from "../src/ui-helpers.js";

test("normalizeText trims and lowercases", () => {
  assert.equal(normalizeText("  Reactor   Bay "), "reactor bay");
});

test("parseRoute understands charge screen and board filter", () => {
  assert.deepEqual(parseRoute("#/lots/abc123/charge"), { name: "charge", id: "abc123" });
  assert.deepEqual(parseRoute("#/reactors?board_view=running"), { name: "reactors", boardView: "running" });
});

test("clampChargeWeight respects bounds and tenth-pound rounding", () => {
  assert.equal(clampChargeWeight("12.34", 20), 12.3);
  assert.equal(clampChargeWeight(25, 20), 20);
  assert.equal(clampChargeWeight(-1, 20), 0);
});

test("lotTitle and readiness helpers stay operator-readable", () => {
  assert.equal(lotTitle({ supplier_name: "Forest Farms", strain_name: "Blue Dream" }), "Forest Farms - Blue Dream");
  assert.equal(readyLotCount([{ ready_for_charge: true }, { ready_for_charge: false }, { ready_for_charge: true }]), 2);
  assert.equal(stateTone("cancelled"), "danger");
});
