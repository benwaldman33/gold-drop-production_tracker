export function normalizeText(value) {
  return String(value || "")
    .trim()
    .replace(/\s+/g, " ")
    .toLowerCase();
}

export function lotTitle(lot) {
  return `${lot?.supplier_name || "Unknown supplier"} - ${lot?.strain_name || "Unknown strain"}`;
}

export function clampChargeWeight(value, maxWeight) {
  const max = Number(maxWeight || 0);
  const parsed = Number(value || 0);
  if (!Number.isFinite(parsed)) return 0;
  if (parsed < 0) return 0;
  if (max > 0 && parsed > max) return max;
  return Math.round(parsed * 10) / 10;
}

export function stateTone(stateKey) {
  switch (String(stateKey || "").toLowerCase()) {
    case "running":
    case "applied":
      return "success";
    case "completed":
      return "neutral";
    case "cancelled":
      return "danger";
    case "in_reactor":
    case "pending":
      return "warning";
    default:
      return "idle";
  }
}

export function readyLotCount(lots) {
  return (lots || []).filter((lot) => lot.ready_for_charge).length;
}
