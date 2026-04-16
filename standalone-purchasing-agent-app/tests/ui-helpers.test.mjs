import test from "node:test";
import assert from "node:assert/strict";
import { buildOpportunityPayload, buildSupplierPayload, parseRoute } from "../src/ui-helpers.js";

test("parseRoute handles opportunity paths", () => {
  assert.deepEqual(parseRoute("#/opportunities/new"), { name: "opportunity-new" });
  assert.deepEqual(parseRoute("#/opportunities/opp-1"), { name: "opportunity" , id: "opp-1" });
  assert.deepEqual(parseRoute("#/opportunities/opp-1/edit"), { name: "edit", id: "opp-1" });
  assert.deepEqual(parseRoute("#/opportunities/opp-1/delivery"), { name: "delivery", id: "opp-1" });
});

test("parseRoute handles supplier search paths", () => {
  assert.deepEqual(parseRoute("#/suppliers?q=Farmlane"), { name: "suppliers", query: "Farmlane" });
  assert.deepEqual(parseRoute("#/suppliers/new"), { name: "supplier-new" });
  assert.deepEqual(parseRoute("#/suppliers/sup-1"), { name: "supplier", id: "sup-1" });
});

test("buildOpportunityPayload extracts form data", () => {
  const form = new FormData();
  form.set("supplier_id", "sup-1");
  form.set("strain_name", "Blue Dream");
  form.set("expected_weight_lbs", "350");
  form.set("expected_potency_pct", "23.5");
  form.set("offered_price_per_lb", "285");
  form.set("availability_date", "2026-04-18");
  form.set("clean_or_dirty", "clean");
  form.set("testing_notes", "fresh");
  form.set("notes", "important");
  form.set("confirm_new_supplier", "on");

  const payload = buildOpportunityPayload(form);
  assert.equal(payload.supplier_id, "sup-1");
  assert.equal(payload.strain_name, "Blue Dream");
  assert.equal(payload.expected_weight_lbs, "350");
  assert.equal(payload.expected_potency_pct, "23.5");
  assert.equal(payload.confirm_new_supplier, true);
});

test("buildSupplierPayload extracts supplier form data", () => {
  const form = new FormData();
  form.set("name", "Farmlane");
  form.set("location", "Salinas, CA");
  form.set("contact_name", "Maya");
  form.set("phone", "555-0111");
  form.set("email", "sales@example.com");
  form.set("notes", "note");
  form.set("confirm_new_supplier", "on");

  const payload = buildSupplierPayload(form);
  assert.equal(payload.name, "Farmlane");
  assert.equal(payload.location, "Salinas, CA");
  assert.equal(payload.confirm_new_supplier, true);
});
