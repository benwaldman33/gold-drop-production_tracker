import { clampChargeWeight, preferredChargeWeight, preferredReactorNumber } from "./domain.js";

export function parseRoute(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const [path, queryString] = raw.split("?");
  const query = new URLSearchParams(queryString || "");
  const parts = path.split("/").filter(Boolean);

  if (!parts.length || parts[0] === "login") return { name: "login" };
  if (parts[0] === "home") return { name: "home" };
  if (parts[0] === "scan") return { name: "scan" };
  if (parts[0] === "reactors") return { name: "reactors", boardView: query.get("board_view") || "all" };
  if (parts[0] === "downstream") return { name: "downstream" };
  if (parts[0] === "runs" && parts[1] === "charge" && parts[2]) {
    return { name: "run", chargeId: parts[2], flow: query.get("flow") === "downstream" ? "downstream" : "reactor" };
  }
  if (parts[0] === "lots" && parts[1] && parts[2] === "charge") return { name: "charge", id: parts[1] };
  if (parts[0] === "lots" && parts[1]) return { name: "lot", id: parts[1] };
  if (parts[0] === "lots") return { name: "lots", query: query.get("q") || "" };
  if (parts[0] === "settings") return { name: "settings" };
  return { name: "home" };
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function boothHistory(run) {
  return run?.booth?.history || [];
}

export function hasBoothEvent(run, eventKey, labelPattern) {
  const history = boothHistory(run);
  if (eventKey && history.some((row) => row.event_key === eventKey)) return true;
  if (labelPattern) {
    const pattern = labelPattern instanceof RegExp ? labelPattern : new RegExp(labelPattern, "i");
    return history.some((row) => pattern.test(String(row.event_label || "")));
  }
  return false;
}

export function isBiomassPrepDone(run) {
  return hasBoothEvent(run, "biomass_loaded_confirmed", /biomass.*(loaded confirmed|confirmed loaded)/i);
}

export function isChillerPrepDone(run) {
  return hasBoothEvent(
    run,
    "chiller_temperature_checked",
    /chiller temperature confirmed|chiller temperature acknowledged|chiller temp checked/i,
  );
}

export function isVacuumPrepDone(run) {
  return hasBoothEvent(run, "reactor_vacuum_confirmed", /reactor vacuum confirmed|vacuum confirmed/i);
}

export function chillerReadingC(run) {
  const temp = run?.chiller_check_actual_temp_c ?? run?.booth?.chiller_check_actual_temp_c;
  if (temp == null || temp === "") return null;
  const parsed = Number(temp);
  return Number.isFinite(parsed) ? parsed : null;
}

export function chillerOutOfSpec(run) {
  return Boolean(run?.chiller_out_of_spec ?? run?.booth?.chiller_out_of_spec);
}

export function siteTimeZone(site) {
  return site?.site_timezone || "America/Los_Angeles";
}

export function parseSiteClockDate(value, timeZone = "America/Los_Angeles") {
  const raw = String(value || "").trim();
  if (!raw) return null;
  if (/[zZ]|[+-]\d{2}:\d{2}$/.test(raw)) {
    const date = new Date(raw);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const match = normalized.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/);
  if (!match) {
    const date = new Date(normalized);
    return Number.isNaN(date.getTime()) ? null : date;
  }
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const hour = Number(match[4]);
  const minute = Number(match[5]);
  const second = Number(match[6] || "0");
  let utcMs = Date.UTC(year, month - 1, day, hour, minute, second);
  const formatter = new Intl.DateTimeFormat("en-US", {
    timeZone,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(utcMs)).map((part) => [part.type, part.value]));
    const displayedHour = Number(parts.hour === "24" ? "0" : parts.hour);
    const displayedUtc = Date.UTC(
      Number(parts.year),
      Number(parts.month) - 1,
      Number(parts.day),
      displayedHour,
      Number(parts.minute),
      Number(parts.second),
    );
    const desiredUtc = Date.UTC(year, month - 1, day, hour, minute, second);
    const delta = desiredUtc - displayedUtc;
    if (delta === 0) break;
    utcMs += delta;
  }
  return new Date(utcMs);
}

export function clockDurationMs(startAt, endAt, { timeZone = "America/Los_Angeles", now = Date.now() } = {}) {
  const startDate = parseSiteClockDate(startAt, timeZone);
  if (!startDate) return null;
  const endDate = parseSiteClockDate(endAt, timeZone);
  const referenceMs = endDate ? endDate.getTime() : now;
  return Math.max(0, referenceMs - startDate.getTime());
}

export function localDateTimeInputValue(value = new Date(), timeZone = "America/Los_Angeles") {
  const dt = new Date(value);
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone,
      hour12: false,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).formatToParts(dt).map((part) => [part.type, part.value]),
  );
  const hour = parts.hour === "24" ? "00" : parts.hour;
  return `${parts.year}-${parts.month}-${parts.day}T${hour}:${parts.minute}`;
}

export function shortDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

// When duplicate named fields exist (hidden + visible), prefer the last non-empty value.
export function lastNamedFormValue(form, name) {
  const values = form.getAll(name).map((entry) => String(entry || "").trim());
  for (let index = values.length - 1; index >= 0; index -= 1) {
    if (values[index]) return values[index];
  }
  return "";
}

export function namedFormCheckboxValue(form, name) {
  return form.getAll(name).some((entry) => String(entry || "").trim()) ? "1" : "";
}

export function buildChargePayload(form, maxWeight) {
  const rawWeight = form.get("charged_weight_lbs");
  const chargedWeight = clampChargeWeight(rawWeight, maxWeight);
  return {
    charged_weight_lbs: chargedWeight,
    reactor_number: Number(form.get("reactor_number") || 0),
    charged_at: String(form.get("charged_at") || "").trim(),
    notes: String(form.get("notes") || "").trim(),
  };
}

export function defaultChargeValue(maxWeight, preferredWeight = 100) {
  return preferredChargeWeight(maxWeight, preferredWeight);
}

export function defaultReactorValue(preferredReactor, reactorCount) {
  return preferredReactorNumber(preferredReactor, reactorCount);
}

export function buildReactorActionMarkup(current, escape = escapeHtml) {
  const actions = current?.available_actions || [];
  const hasOpenRun = Boolean(current?.charge_id);
  if (!actions.length && !hasOpenRun) return "";
  const buttons = [];
  if (hasOpenRun) {
    buttons.push(
      `<a class="btn btn-primary" href="#/runs/charge/${escape(current.charge_id)}">Open Run</a>`,
    );
  }
  for (const action of actions) {
    const accent =
      action.target_state === "cleared"
        ? "btn-primary"
        : action.target_state === "cancelled"
          ? "btn-danger"
          : "btn-secondary";
    buttons.push(
      `<button class="btn ${accent}" data-action="transition-charge" data-charge-id="${escape(current.charge_id)}" data-target-state="${escape(action.target_state)}">${escape(action.label)}</button>`,
    );
  }
  return `<div class="action-grid">${buttons.join("")}</div>`;
}
