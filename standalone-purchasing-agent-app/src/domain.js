export function normalizeText(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

export function tokenize(value) {
  return normalizeText(value)
    .split(/[^a-z0-9]+/i)
    .map((part) => part.trim())
    .filter(Boolean);
}

export function buildSupplierMatchReasons(candidate, query) {
  const reasons = [];
  const candidateName = normalizeText(candidate?.name);
  const queryName = normalizeText(query);
  if (candidateName === queryName) reasons.push("normalized_name");
  else if (candidateName.includes(queryName) || queryName.includes(candidateName)) reasons.push("substring_name");
  const candidatePhone = normalizeText(candidate?.phone);
  if (candidatePhone && candidatePhone === normalizeText(query)) reasons.push("phone");
  const candidateEmail = normalizeText(candidate?.email);
  if (candidateEmail && candidateEmail === normalizeText(query)) reasons.push("email");
  if (!reasons.length) reasons.push("token_overlap");
  return reasons;
}

export function scoreSupplierMatch(candidate, query) {
  const candidateName = normalizeText(candidate?.name);
  const queryName = normalizeText(query);
  if (!candidateName || !queryName) return 0;
  if (candidateName === queryName) return 1;
  if (candidateName.includes(queryName) || queryName.includes(candidateName)) return 0.94;

  const candidateTokens = new Set(tokenize(candidate?.name));
  const queryTokens = new Set(tokenize(query));
  let overlap = 0;
  for (const token of queryTokens) {
    if (candidateTokens.has(token)) overlap += 1;
  }
  if (!queryTokens.size) return 0;
  const tokenScore = overlap / Math.max(candidateTokens.size, queryTokens.size);
  const emailMatch = normalizeText(candidate?.email) && normalizeText(candidate?.email) === normalizeText(query) ? 0.98 : 0;
  const phoneMatch = normalizeText(candidate?.phone) && normalizeText(candidate?.phone) === normalizeText(query) ? 0.98 : 0;
  return Math.max(tokenScore, emailMatch, phoneMatch);
}

export function findDuplicateSupplierCandidates(query, suppliers) {
  return [...suppliers]
    .map((supplier) => ({ supplier, score: scoreSupplierMatch(supplier, query) }))
    .filter((item) => item.score >= 0.55)
    .sort((a, b) => b.score - a.score)
    .map((item) => ({
      id: item.supplier.id,
      name: item.supplier.name,
      location: item.supplier.location || "",
      match_reason: buildSupplierMatchReasons(item.supplier, query),
      score: Number(item.score.toFixed(2)),
    }));
}

export function isOpportunityEditable(status) {
  return ["draft", "submitted", "under_review"].includes(String(status || "").toLowerCase());
}

export function canRecordDelivery(status) {
  return ["approved", "committed"].includes(String(status || "").toLowerCase());
}

export function opportunityTitle(opportunity) {
  return `${opportunity?.supplier?.name || opportunity?.supplier_name || "Unknown supplier"} - ${opportunity?.strain_name || "Unknown strain"}`;
}
