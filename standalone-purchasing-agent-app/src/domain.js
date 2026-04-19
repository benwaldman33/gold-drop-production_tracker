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

export function similarity(left, right) {
  const a = normalizeText(left);
  const b = normalizeText(right);
  if (!a || !b) return 0;
  if (a === b) return 1;
  const rows = Array.from({ length: a.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= b.length; j += 1) rows[0][j] = j;
  for (let i = 1; i <= a.length; i += 1) {
    for (let j = 1; j <= b.length; j += 1) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      rows[i][j] = Math.min(
        rows[i - 1][j] + 1,
        rows[i][j - 1] + 1,
        rows[i - 1][j - 1] + cost,
      );
    }
  }
  const distance = rows[a.length][b.length];
  return 1 - distance / Math.max(a.length, b.length);
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
  const genericTokens = new Set(["and", "co", "company", "corp", "corporation", "cultivation", "farm", "farms", "from", "group", "inc", "llc", "the"]);
  const candidateTokens = tokenize(candidate?.name).filter((token) => !genericTokens.has(token));
  const queryTokens = tokenize(query).filter((token) => !genericTokens.has(token));
  const bestTokenSimilarity = candidateTokens.length && queryTokens.length
    ? Math.max(...queryTokens.flatMap((left) => candidateTokens.map((right) => similarity(left, right))))
    : 0;
  if (bestTokenSimilarity >= 0.88) reasons.push("fuzzy_name");
  if (similarity(candidateName, queryName) >= 0.85) reasons.push("high_name_similarity");
  if (!reasons.length) reasons.push("token_overlap");
  return reasons;
}

export function scoreSupplierMatch(candidate, query) {
  const candidateName = normalizeText(candidate?.name);
  const queryName = normalizeText(query);
  if (!candidateName || !queryName) return 0;
  if (candidateName === queryName) return 1;
  if (candidateName.includes(queryName) || queryName.includes(candidateName)) return 0.94;

  const genericTokens = new Set(["and", "co", "company", "corp", "corporation", "cultivation", "farm", "farms", "from", "group", "inc", "llc", "the"]);
  const candidateTokens = new Set(tokenize(candidate?.name).filter((token) => !genericTokens.has(token)));
  const queryTokens = new Set(tokenize(query).filter((token) => !genericTokens.has(token)));
  const allCandidateTokens = new Set(tokenize(candidate?.name));
  const allQueryTokens = new Set(tokenize(query));
  let overlap = 0;
  for (const token of queryTokens) {
    if (candidateTokens.has(token)) overlap += 1;
  }
  let genericOverlap = 0;
  for (const token of allQueryTokens) {
    if (allCandidateTokens.has(token)) genericOverlap += 1;
  }
  const tokenScore = queryTokens.size ? overlap / Math.max(candidateTokens.size, queryTokens.size) : 0;
  const genericTokenScore = allQueryTokens.size ? genericOverlap / Math.max(allCandidateTokens.size, allQueryTokens.size) : 0;
  const bestTokenSimilarity = candidateTokens.size && queryTokens.size
    ? Math.max(...[...queryTokens].flatMap((left) => [...candidateTokens].map((right) => similarity(left, right))))
    : 0;
  const nameSimilarity = similarity(candidateName, queryName);
  const emailMatch = normalizeText(candidate?.email) && normalizeText(candidate?.email) === normalizeText(query) ? 0.98 : 0;
  const phoneMatch = normalizeText(candidate?.phone) && normalizeText(candidate?.phone) === normalizeText(query) ? 0.98 : 0;
  return Math.max(
    tokenScore * 0.9,
    genericTokenScore * 0.7,
    bestTokenSimilarity * (genericTokenScore > 0 ? 0.92 : 0),
    nameSimilarity,
    emailMatch,
    phoneMatch,
  );
}

export function findDuplicateSupplierCandidates(query, suppliers) {
  return [...suppliers]
    .map((supplier) => ({ supplier, score: scoreSupplierMatch(supplier, query) }))
    .filter((item) => item.score >= 0.74)
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
