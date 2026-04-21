import test from "node:test";
import assert from "node:assert/strict";
import { createApiClient } from "../src/api.js";
import { resetStorage } from "../src/storage.js";

test.beforeEach(() => {
  resetStorage();
});

test("mock api login, board, charge, and transition flow", async () => {
  const api = createApiClient({ mode: "mock" });
  const before = await api.me();
  assert.equal(before.authenticated, false);

  await api.login("extractor1", "secret");
  const board = await api.getBoard("all");
  assert.equal(board.summary.reactor_count, 3);

  const lots = await api.listLots("Blue");
  assert.equal(lots.length, 1);
  const lookedUp = await api.lookupLot("LOT-A1B2C3D4");
  assert.equal(lookedUp.id, lots[0].id);

  const created = await api.createCharge(lots[0].id, {
    charged_weight_lbs: 22.5,
    reactor_number: 2,
    charged_at: "2026-04-19T09:10",
    notes: "Touch workflow charge",
  });
  assert.equal(created.charge.source_mode, "standalone_extraction");
  assert.equal(created.charge.reactor_number, 2);

  const transitioned = await api.transitionCharge(created.charge.id, { target_state: "in_reactor" });
  assert.equal(transitioned.charge.status, "in_reactor");

  const runPayload = await api.getChargeRun(created.charge.id);
  assert.equal(runPayload.run.reactor_number, 2);
  assert.equal(runPayload.run.progression.stage_key, "ready_to_start");

  const startedRun = await api.saveChargeRun(created.charge.id, {
    progression_action: "start_run",
  });
  assert.equal(startedRun.run.progression.stage_key, "ready_to_mix");
  assert.ok(startedRun.run.run_fill_started_at);

  const savedRun = await api.saveChargeRun(created.charge.id, {
    fill_count: 1,
    fill_total_weight_lbs: 22.5,
    notes: "Execution notes",
  });
  assert.equal(savedRun.run.fill_count, 1);
  assert.equal(savedRun.run.notes, "Execution notes");
});

test("live api unwraps extraction mobile envelopes", async () => {
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
              user: { id: "user-1", username: "extractor1", display_name: "Extractor One" },
              permissions: { can_extract_lab: true },
              site: { site_name: "Gold Drop" },
            },
          };
        },
      };
    }
    if (url.includes("/api/mobile/v1/extraction/board")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              summary: { reactor_count: 3, active_reactor_count: 1 },
              board_view: "all",
              board_view_options: [{ value: "all", label: "All reactors" }],
              reactor_cards: [],
              reactor_history: [],
            },
          };
        },
      };
    }
    if (url.includes("/api/mobile/v1/extraction/lots?")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: [{ id: "lot-1", supplier_name: "Forest Farms", strain_name: "Blue Dream", ready_for_charge: true }],
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/extraction/lots/lot-1")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              lot: { id: "lot-1", tracking_id: "LOT-ABC", supplier_name: "Forest Farms", strain_name: "Blue Dream" },
            },
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/extraction/lookup/LOT-ABC")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              lot: { id: "lot-1", tracking_id: "LOT-ABC", supplier_name: "Forest Farms", strain_name: "Blue Dream" },
            },
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/extraction/lots/lot-1/charge")) {
      assert.equal(options.method, "POST");
      return {
        ok: true,
        status: 201,
        async json() {
          return {
            meta: {},
            data: {
              charge: { id: "chg-1", status: "pending", reactor_number: 1, source_mode: "standalone_extraction" },
              lot: { id: "lot-1" },
              next_run_url: "/runs/new?return_to=/floor-ops",
            },
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/extraction/charges/chg-1/transition")) {
      assert.equal(options.method, "POST");
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              charge: { id: "chg-1", status: "running", state_label: "Running" },
            },
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/extraction/charges/chg-1/run") && (!options.method || options.method === "GET")) {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              charge: { id: "chg-1", status: "applied", reactor_number: 1, source_mode: "standalone_extraction" },
              lot: { id: "lot-1", tracking_id: "LOT-ABC", supplier_name: "Forest Farms", strain_name: "Blue Dream" },
              run: { id: "run-1", reactor_number: 1, bio_in_reactor_lbs: 30, notes: "", open_main_app_url: "/runs/run-1/edit?return_to=/floor-ops" },
            },
          };
        },
      };
    }
    if (url.endsWith("/api/mobile/v1/extraction/charges/chg-1/run") && options.method === "POST") {
      return {
        ok: true,
        status: 200,
        async json() {
          return {
            meta: {},
            data: {
              charge: { id: "chg-1", status: "applied", reactor_number: 1, source_mode: "standalone_extraction" },
              lot: { id: "lot-1", tracking_id: "LOT-ABC", supplier_name: "Forest Farms", strain_name: "Blue Dream" },
              run: { id: "run-1", reactor_number: 1, bio_in_reactor_lbs: 30, notes: "Saved", open_main_app_url: "/runs/run-1/edit?return_to=/floor-ops" },
            },
          };
        },
      };
    }
    throw new Error(`Unexpected URL ${url}`);
  };

  const api = createApiClient({ mode: "live", apiBaseUrl: "https://example.test", fetchImpl });
  const me = await api.me();
  assert.equal(me.user.username, "extractor1");

  const board = await api.getBoard("all");
  assert.equal(board.summary.reactor_count, 3);

  const lots = await api.listLots("Blue");
  assert.equal(lots[0].ready_for_charge, true);

  const lot = await api.getLot("lot-1");
  assert.equal(lot.tracking_id, "LOT-ABC");

  const lookedUp = await api.lookupLot("LOT-ABC");
  assert.equal(lookedUp.id, "lot-1");

  const created = await api.createCharge("lot-1", { charged_weight_lbs: 30, reactor_number: 1, charged_at: "2026-04-19T09:10" });
  assert.equal(created.charge.source_mode, "standalone_extraction");

  const transitioned = await api.transitionCharge("chg-1", { target_state: "running" });
  assert.equal(transitioned.charge.state_label, "Running");

  const runPayload = await api.getChargeRun("chg-1");
  assert.equal(runPayload.run.id, "run-1");

  const savedRun = await api.saveChargeRun("chg-1", { notes: "Saved" });
  assert.equal(savedRun.run.notes, "Saved");
});
