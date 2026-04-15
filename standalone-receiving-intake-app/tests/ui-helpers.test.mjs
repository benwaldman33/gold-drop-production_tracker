import test from "node:test";
import assert from "node:assert/strict";
import { buildReceivePayload, parseRoute } from "../src/ui-helpers.js";

test("parseRoute handles receiving queue paths", () => {
  assert.deepEqual(parseRoute("#/queue"), { name: "queue", status: "ready" });
  assert.deepEqual(parseRoute("#/queue/recv-1"), { name: "detail", id: "recv-1" });
  assert.deepEqual(parseRoute("#/queue/recv-1/receive"), { name: "receive", id: "recv-1" });
});

test("parseRoute handles home status filter", () => {
  assert.deepEqual(parseRoute("#/home?status=delivered"), { name: "home", status: "delivered" });
});

test("buildReceivePayload extracts intake confirmation fields", () => {
  const form = new FormData();
  form.set("delivered_weight_lbs", "92.5");
  form.set("delivery_date", "2026-04-16");
  form.set("testing_status", "pending");
  form.set("actual_potency_pct", "24.1");
  form.set("clean_or_dirty", "clean");
  form.set("delivery_notes", "Received in good condition");
  form.set("location", "Receiving Vault");
  form.set("floor_state", "receiving");
  form.set("lot_notes", "Dock count matched manifest");

  const payload = buildReceivePayload(form);
  assert.equal(payload.delivered_weight_lbs, "92.5");
  assert.equal(payload.location, "Receiving Vault");
  assert.equal(payload.floor_state, "receiving");
});
