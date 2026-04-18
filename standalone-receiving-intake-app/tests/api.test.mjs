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

  const session = await api.login("receiver1", "secret");
  assert.equal(session.user.username, "receiver1");

  const after = await api.me();
  assert.equal(after.user.username, "receiver1");

  await api.logout();
  const ended = await api.me();
  assert.equal(ended.authenticated, false);
});

test("mock api lists ready receipts and confirms delivery", async () => {
  const api = createApiClient({ mode: "mock" });
  await api.login("receiver1", "secret");

  const queue = await api.listReceivingQueue("ready");
  assert.ok(queue.length >= 1);

  const updated = await api.receive(queue[0].id, {
    delivered_weight_lbs: "92.5",
    delivery_date: "2026-04-16",
    testing_status: "pending",
    clean_or_dirty: "clean",
    location: "Receiving Vault",
    floor_state: "receiving",
    delivery_notes: "Received in good condition",
  });

  assert.equal(updated.status, "delivered");
  assert.equal(updated.receiving.location, "Receiving Vault");
});

test("mock api updates an already received record", async () => {
  const api = createApiClient({ mode: "mock" });
  await api.login("receiver1", "secret");

  const updated = await api.updateReceiving("recv-1003", {
    delivered_weight_lbs: "176.2",
    delivery_date: "2026-04-10",
    testing_status: "completed",
    actual_potency_pct: "24.8",
    clean_or_dirty: "clean",
    location: "Vault B",
    floor_state: "inventory",
    lot_notes: "Moved after recount",
    delivery_notes: "Edited after recount",
  });

  assert.equal(updated.delivery.delivered_weight_lbs, 176.2);
  assert.equal(updated.receiving.location, "Vault B");
  assert.equal(updated.receiving.last_receiving_edit_by, "Receiver1");
});

test("mock api uploads delivery photos", async () => {
  const originalReader = global.FileReader;
  global.FileReader = class {
    readAsDataURL() {
      this.result = "data:image/png;base64,QUJD";
      queueMicrotask(() => this.onload?.());
    }
  };

  try {
    const api = createApiClient({ mode: "mock" });
    await api.login("receiver1", "secret");
    const queue = await api.listReceivingQueue("ready");
    const photo = await api.uploadPhoto(queue[0].id, {
      file: { name: "dock.png", size: 12 },
      photo_context: "delivery",
    });
    assert.equal(photo.photo_context, "delivery");
    assert.equal(photo.photos[0].url, "data:image/png;base64,QUJD");
  } finally {
    global.FileReader = originalReader;
  }
});

test("live api unwraps mobile envelopes for receiving queue and detail", async () => {
  const fetchImpl = async (url, options = {}) => {
    if (url.endsWith("/api/mobile/v1/auth/me")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              authenticated: true,
              user: { id: "user-1", username: "receiver1", display_name: "Receiver One" },
              permissions: { can_receive_intake: true },
              site: { site_name: "Gold Drop" },
            },
          };
        },
      };
    }
    if (url.includes("/api/mobile/v1/receiving/queue?")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: [{ id: "recv-1", status: "approved", supplier_name: "Farmlane", strain_name: "Blue Dream", receiving: { queue_state: "ready" } }],
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/receiving/queue/recv-1")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: { id: "recv-1", status: "approved", supplier_name: "Farmlane", strain_name: "Blue Dream", receiving: { queue_state: "ready" }, photos: [] },
          };
        },
      };
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const api = createApiClient({ mode: "live", apiBaseUrl: "https://example.test", fetchImpl });
  const me = await api.me();
  assert.equal(me.user.username, "receiver1");

  const queue = await api.listReceivingQueue("ready");
  assert.equal(queue.length, 1);
  assert.equal(queue[0].receiving.queue_state, "ready");

  const detail = await api.getReceivingItem("recv-1");
  assert.equal(detail.id, "recv-1");
});
