import test from "node:test";
import assert from "node:assert/strict";
import { clampChargeWeight, halfLotChargeWeight, lotTitle, normalizeText, preferredChargeWeight, readyLotCount, stateTone } from "../src/domain.js";
import { buildReactorActionMarkup, defaultChargeValue, defaultReactorValue, parseRoute, clockDurationMs, parseSiteClockDate, siteTimeZone, isBiomassPrepDone, isChillerPrepDone, hasBoothEvent, finalPurgeStartedAt, finalPurgeCompletedAt } from "../src/ui-helpers.js";

test("normalizeText trims and lowercases", () => {
  assert.equal(normalizeText("  Reactor   Bay "), "reactor bay");
});

test("parseRoute understands charge screen and board filter", () => {
  assert.deepEqual(parseRoute("#/lots/abc123/charge"), { name: "charge", id: "abc123" });
  assert.deepEqual(parseRoute("#/reactors?board_view=running"), { name: "reactors", boardView: "running" });
  assert.deepEqual(parseRoute("#/scan"), { name: "scan" });
  assert.deepEqual(parseRoute("#/downstream"), { name: "downstream" });
  assert.deepEqual(parseRoute("#/runs/charge/chg-123"), { name: "run", chargeId: "chg-123", flow: "reactor" });
  assert.deepEqual(parseRoute("#/runs/charge/chg-123?flow=downstream"), { name: "run", chargeId: "chg-123", flow: "downstream" });
  assert.deepEqual(parseRoute("#/runs/charge/"), { name: "home" });
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

test("reactor action markup promotes open run to a primary button", () => {
  const markup = buildReactorActionMarkup({
    charge_id: "chg-123",
    available_actions: [
      { target_state: "running", label: "Mark Running" },
      { target_state: "cancelled", label: "Cancel Charge" },
    ],
  });
  assert.match(markup, /class="btn btn-primary" href="#\/runs\/charge\/chg-123">Open Run<\/a>/);
  assert.match(markup, /Mark Running/);
  assert.match(markup, /Cancel Charge/);
});

test("parseSiteClockDate interprets API timestamps in site timezone", () => {
  const timeZone = "America/Los_Angeles";
  const start = parseSiteClockDate("2026-06-27T14:00", timeZone);
  assert.ok(start);
  const end = parseSiteClockDate("2026-06-27T14:05", timeZone);
  const elapsedMs = clockDurationMs("2026-06-27T14:00", "2026-06-27T14:05", { timeZone, now: end.getTime() });
  assert.equal(elapsedMs, 5 * 60_000);
});

test("parseSiteClockDate round trips site-local wall time", () => {
  const timeZone = "America/Los_Angeles";
  const parsed = parseSiteClockDate("2026-06-27T14:00", timeZone);
  assert.ok(parsed);
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(parsed).map((part) => [part.type, part.value]),
  );
  assert.equal(parts.year, "2026");
  assert.equal(parts.month, "06");
  assert.equal(parts.day, "27");
  assert.equal(parts.hour === "24" ? "00" : parts.hour, "14");
  assert.equal(parts.minute, "00");
});

test("booth prep status reads live API event keys and labels", () => {
  const run = {
    bio_in_reactor_lbs: 100,
    chiller_check_actual_temp_c: -40,
    chiller_out_of_spec: false,
    booth: {
      history: [
        { event_key: "biomass_loaded_confirmed", event_label: "Biomass loaded confirmed" },
        { event_key: "chiller_temperature_checked", event_label: "Chiller temperature confirmed in spec" },
      ],
    },
  };
  assert.equal(isBiomassPrepDone(run), true);
  assert.equal(isChillerPrepDone(run), true);
  assert.equal(hasBoothEvent(run, "reactor_vacuum_confirmed"), false);
});

test("final purge timestamps resolve from run root or booth session", () => {
  assert.equal(finalPurgeStartedAt({ final_purge_started_at: "2026-06-27T14:00" }), "2026-06-27T14:00");
  assert.equal(
    finalPurgeStartedAt({ booth: { final_purge_started_at: "2026-06-27T14:05" } }),
    "2026-06-27T14:05",
  );
  assert.equal(
    finalPurgeCompletedAt({ final_purge_completed_at: "2026-06-27T14:30" }),
    "2026-06-27T14:30",
  );
  assert.equal(
    finalPurgeCompletedAt({ booth: { final_purge_completed_at: "2026-06-27T14:35" } }),
    "2026-06-27T14:35",
  );
});
