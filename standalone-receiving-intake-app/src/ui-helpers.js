export function parseRoute(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const [path, queryString] = raw.split("?");
  const query = new URLSearchParams(queryString || "");
  const parts = path.split("/").filter(Boolean);

  if (!parts.length || parts[0] === "login") return { name: "login" };
  if (parts[0] === "home") return { name: "home", status: query.get("status") || "ready" };
  if (parts[0] === "queue" && parts[1] && parts[2] === "receive") return { name: "receive", id: parts[1] };
  if (parts[0] === "queue" && parts[1] && parts[2] === "edit") return { name: "edit", id: parts[1] };
  if (parts[0] === "queue" && parts[1]) return { name: "detail", id: parts[1] };
  if (parts[0] === "queue") return { name: "queue", status: query.get("status") || "ready" };
  return { name: "home" };
}

export function buildReceivePayload(form) {
  return {
    delivered_weight_lbs: String(form.get("delivered_weight_lbs") || "").trim(),
    delivery_date: String(form.get("delivery_date") || "").trim(),
    testing_status: String(form.get("testing_status") || "").trim(),
    actual_potency_pct: String(form.get("actual_potency_pct") || "").trim(),
    clean_or_dirty: String(form.get("clean_or_dirty") || "clean"),
    delivery_notes: String(form.get("delivery_notes") || "").trim(),
    location: String(form.get("location") || "").trim(),
    floor_state: String(form.get("floor_state") || "receiving").trim(),
    lot_notes: String(form.get("lot_notes") || "").trim(),
  };
}

export function selectedFilesFromForm(form, fieldName) {
  if (!form || typeof form.querySelector !== "function") return [];
  const input = form.querySelector(`input[type="file"][name="${fieldName}"]`);
  return [...(input?.files || [])];
}

export function shortDate(value) {
  if (!value) return "";
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export function shortDateTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}
