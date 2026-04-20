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
  if (parts[0] === "runs" && parts[1] === "charge" && parts[2]) return { name: "run", chargeId: parts[2] };
  if (parts[0] === "lots" && parts[1] && parts[2] === "charge") return { name: "charge", id: parts[1] };
  if (parts[0] === "lots" && parts[1]) return { name: "lot", id: parts[1] };
  if (parts[0] === "lots") return { name: "lots", query: query.get("q") || "" };
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

export function localDateTimeInputValue(value = new Date()) {
  const dt = new Date(value);
  const offset = dt.getTimezoneOffset();
  const shifted = new Date(dt.getTime() - offset * 60_000);
  return shifted.toISOString().slice(0, 16);
}

export function shortDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
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
    buttons.push(
      `<button class="btn ${action.target_state === "cancelled" ? "btn-danger" : "btn-secondary"}" data-action="transition-charge" data-charge-id="${escape(current.charge_id)}" data-target-state="${escape(action.target_state)}">${escape(action.label)}</button>`,
    );
  }
  return `<div class="action-grid">${buttons.join("")}</div>`;
}
