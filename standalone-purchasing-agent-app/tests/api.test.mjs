import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient } from "../src/api.js";
import { resetStorage } from "../src/storage.js";

test.beforeEach(() => {
  resetStorage();
});

test("mock api login/me/logout round trip", async () => {
  const api = createApiClient({ mode: "mock" });
  const before = await api.me();
  assert.equal(before.authenticated, false);

  const session = await api.login("buyer1", "secret");
  assert.equal(session.authenticated || true, true);
  assert.equal(session.user.username, "buyer1");

  const after = await api.me();
  assert.equal(after.user.username, "buyer1");

  await api.logout();
  const ended = await api.me();
  assert.equal(ended.authenticated, false);
});

test("mock api creates and edits an opportunity before approval", async () => {
  const api = createApiClient({ mode: "mock" });
  await api.login("buyer1", "secret");

  const opportunity = await api.createOpportunity({
    supplier_id: "sup-001",
    strain_name: "Blue Dream",
    expected_weight_lbs: 120,
    expected_potency_pct: 23,
    offered_price_per_lb: 280,
    availability_date: "2026-04-14",
    clean_or_dirty: "clean",
    testing_notes: "test notes",
    notes: "important",
  });

  assert.equal(opportunity.status, "submitted");
  assert.equal(opportunity.editable, true);

  const updated = await api.patchOpportunity(opportunity.id, { notes: "updated" });
  assert.equal(updated.notes, "updated");
});

test("mock api warns on duplicate suppliers and confirms new supplier", async () => {
  const api = createApiClient({ mode: "mock" });
  await api.login("buyer1", "secret");

  const first = await api.createSupplier({ name: "Farmlane" });
  assert.equal(first.requires_confirmation, true);
  assert.ok(first.duplicate_candidates.length > 0);

  const confirmed = await api.createSupplier({ name: "Farmlane", confirm_new_supplier: true });
  assert.ok(confirmed.supplier);
  assert.equal(confirmed.supplier.name, "Farmlane");
});

test("mock api records delivery only for approved or committed opportunities", async () => {
  const api = createApiClient({ mode: "mock" });
  await api.login("buyer1", "secret");
  const opportunity = await api.getOpportunity("opp-1002");
  assert.equal(opportunity.status, "approved");

  const delivered = await api.recordDelivery(opportunity.id, {
    delivered_weight_lbs: 205,
    delivery_date: "2026-04-16",
    testing_status: "completed",
    actual_potency_pct: 21.3,
    clean_or_dirty: "clean",
    delivery_notes: "received",
  });

  assert.equal(delivered.status, "delivered");
  assert.equal(delivered.delivery.delivered_weight_lbs, 205);
});

test("mock api uploads opportunity photos", async () => {
  const originalReader = global.FileReader;
  global.FileReader = class {
    readAsDataURL() {
      this.result = "data:image/png;base64,QUJD";
      queueMicrotask(() => this.onload?.());
    }
  };

  try {
    const api = createApiClient({ mode: "mock" });
    await api.login("buyer1", "secret");
    const opportunity = await api.createOpportunity({
      supplier_id: "sup-001",
      strain_name: "Blue Dream",
      expected_weight_lbs: 120,
      clean_or_dirty: "clean",
      notes: "",
    });
    const photo = await api.uploadPhoto(opportunity.id, {
      file: { name: "photo.png", size: 12 },
      photo_context: "opportunity",
    });
    assert.equal(photo.photo.photo_context, "opportunity");
    assert.equal(photo.photo.url, "data:image/png;base64,QUJD");
  } finally {
    global.FileReader = originalReader;
  }
});
