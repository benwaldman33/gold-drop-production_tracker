export function parseRoute(hash) {
  const raw = String(hash || "").replace(/^#/, "");
  const [path, queryString] = raw.split("?");
  const query = new URLSearchParams(queryString || "");
  const parts = path.split("/").filter(Boolean);

  if (!parts.length || parts[0] === "login") return { name: "login" };
  if (parts[0] === "home") return { name: "home", query: query.get("q") || "" };
  if (parts[0] === "opportunities" && parts[1] === "new") return { name: "opportunity-new", supplier_id: query.get("supplier_id") || "" };
  if (parts[0] === "opportunities" && parts[1] && parts[2] === "edit") return { name: "edit", id: parts[1] };
  if (parts[0] === "opportunities" && parts[1] && parts[2] === "delivery") return { name: "delivery", id: parts[1] };
  if (parts[0] === "opportunities" && parts[1]) return { name: "opportunity", id: parts[1] };
  if (parts[0] === "opportunities") return { name: "opportunities", status: query.get("status") || "" };
  if (parts[0] === "suppliers" && parts[1] === "new") return { name: "supplier-new" };
  if (parts[0] === "suppliers" && parts[1]) return { name: "supplier", id: parts[1] };
  if (parts[0] === "suppliers") return { name: "suppliers", query: query.get("q") || "" };
  return { name: "home" };
}

export function buildOpportunityPayload(form) {
  const supplierId = String(form.get("supplier_id") || "");
  const newSupplierName = String(form.get("new_supplier_name") || "").trim();
  const confirmNewSupplier = form.get("confirm_new_supplier") === "on";
  return {
    supplier_id: supplierId || undefined,
    confirm_new_supplier: confirmNewSupplier,
    new_supplier: newSupplierName
      ? {
          name: newSupplierName,
          contact_name: String(form.get("new_supplier_contact_name") || ""),
          phone: String(form.get("new_supplier_phone") || ""),
          email: String(form.get("new_supplier_email") || ""),
          location: String(form.get("new_supplier_location") || ""),
          notes: String(form.get("new_supplier_notes") || ""),
          confirm_new_supplier: confirmNewSupplier,
        }
      : undefined,
    strain_name: String(form.get("strain_name") || "").trim(),
    expected_weight_lbs: String(form.get("expected_weight_lbs") || "").trim(),
    expected_potency_pct: String(form.get("expected_potency_pct") || "").trim(),
    offered_price_per_lb: String(form.get("offered_price_per_lb") || "").trim(),
    availability_date: String(form.get("availability_date") || "").trim(),
    clean_or_dirty: String(form.get("clean_or_dirty") || "clean"),
    testing_notes: String(form.get("testing_notes") || ""),
    notes: String(form.get("notes") || ""),
  };
}

export function buildSupplierPayload(form) {
  return {
    name: String(form.get("name") || "").trim(),
    location: String(form.get("location") || "").trim(),
    contact_name: String(form.get("contact_name") || "").trim(),
    phone: String(form.get("phone") || "").trim(),
    email: String(form.get("email") || "").trim(),
    notes: String(form.get("notes") || "").trim(),
    confirm_new_supplier: form.get("confirm_new_supplier") === "on",
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
