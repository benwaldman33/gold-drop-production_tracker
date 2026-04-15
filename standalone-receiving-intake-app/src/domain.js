export function normalizeText(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

export function canConfirmReceipt(status) {
  return ["approved", "committed"].includes(normalizeText(status));
}

export function isReceiptClosed(status) {
  return ["delivered", "cancelled", "complete"].includes(normalizeText(status));
}

export function receivingTitle(item) {
  return `${item?.supplier?.name || item?.supplier_name || "Unknown supplier"} - ${item?.strain_name || "Unknown strain"}`;
}
