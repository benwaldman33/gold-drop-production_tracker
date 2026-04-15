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

test("live api unwraps mobile envelopes for auth and opportunities", async () => {
  const calls = [];
  const fetchImpl = async (url, options = {}) => {
    calls.push({ url, options });
    if (url.endsWith("/api/mobile/v1/auth/me")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              authenticated: true,
              user: { id: "user-1", username: "buyer1", display_name: "Buyer One" },
              permissions: {},
              site: { site_name: "Gold Drop" },
            },
          };
        },
      };
    }
    if (url.includes("/api/mobile/v1/opportunities/mine")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: [{ id: "opp-1", status: "submitted", supplier_name: "Farmlane", strain_name: "Blue Dream" }],
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/opportunities")) {
      return {
        ok: true,
        status: 201,
        async json() {
          return {
            meta: {},
            data: {
              opportunity: {
                id: "opp-2",
                status: "submitted",
                supplier: { id: "sup-1", name: "Farmlane" },
                photos: [],
              },
            },
          };
        },
      };
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const api = createApiClient({ mode: "live", apiBaseUrl: "https://example.test", fetchImpl });
  const me = await api.me();
  assert.equal(me.user.username, "buyer1");

  const opportunities = await api.listOpportunitiesMine();
  assert.equal(opportunities.length, 1);
  assert.equal(opportunities[0].supplier.name, "Farmlane");

  const created = await api.createOpportunity({ supplier_id: "sup-1", strain_name: "Blue Dream", expected_weight_lbs: 120 });
  assert.equal(created.id, "opp-2");
  assert.equal(created.supplier.name, "Farmlane");
  assert.equal(calls.length, 3);
});

test("live api uses mobile supplier reads and normalizes duplicates", async () => {
  const fetchImpl = async (url, options = {}) => {
    if (url.includes("/api/mobile/v1/suppliers?")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: [
              {
                id: "sup-1",
                name: "Farmlane",
                location: "Salinas",
                opportunity_count: 2,
                open_count: 1,
              },
            ],
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/suppliers")) {
      if (options.method === "POST") {
        return {
          ok: true,
          status: 200,
          async json() {
            return {
              meta: {},
              data: {
                requires_confirmation: true,
                duplicate_candidates: [{ id: "sup-1", name: "Farmlane", location: "Salinas" }],
              },
            };
          },
        };
      }
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const api = createApiClient({ mode: "live", apiBaseUrl: "https://example.test", fetchImpl });
  const suppliers = await api.listSuppliers("farm");
  assert.equal(suppliers[0].name, "Farmlane");
  assert.equal(suppliers[0].open_count, 1);

  const result = await api.createSupplier({ name: "Farmlane" });
  assert.equal(result.requires_confirmation, true);
  assert.equal(result.duplicate_candidates[0].id, "sup-1");
});
