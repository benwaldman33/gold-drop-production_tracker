from __future__ import annotations

import re
from difflib import SequenceMatcher


GENERIC_SUPPLIER_TOKENS = {
    "and",
    "co",
    "company",
    "corp",
    "corporation",
    "cultivation",
    "farm",
    "farms",
    "from",
    "group",
    "inc",
    "llc",
    "the",
}


def normalize_supplier_name(value: str | None) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(value or "").lower())).strip()


def supplier_name_tokens(value: str | None, *, include_generic: bool = False) -> list[str]:
    tokens = [part for part in normalize_supplier_name(value).split(" ") if part]
    if include_generic:
        return tokens
    return [token for token in tokens if token not in GENERIC_SUPPLIER_TOKENS]


def _token_overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / max(len(left), len(right))


def _best_token_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return max(SequenceMatcher(None, l, r).ratio() for l in left for r in right)


def supplier_duplicate_candidate(root, query_name: str, supplier) -> dict | None:
    normalized_query = normalize_supplier_name(query_name)
    normalized_name = normalize_supplier_name(getattr(supplier, "name", ""))
    if not normalized_query or not normalized_name:
        return None

    all_query_tokens = set(supplier_name_tokens(query_name, include_generic=True))
    all_name_tokens = set(supplier_name_tokens(supplier.name, include_generic=True))
    informative_query_tokens = set(supplier_name_tokens(query_name))
    informative_name_tokens = set(supplier_name_tokens(supplier.name))

    exact_match = normalized_query == normalized_name
    substring_match = normalized_query in normalized_name or normalized_name in normalized_query
    name_ratio = SequenceMatcher(None, normalized_query, normalized_name).ratio()
    informative_overlap = _token_overlap_score(informative_query_tokens, informative_name_tokens)
    generic_overlap = _token_overlap_score(all_query_tokens, all_name_tokens)
    best_token_similarity = _best_token_similarity(informative_query_tokens, informative_name_tokens)

    if exact_match:
        score = 1.0
    elif substring_match:
        score = 0.95
    else:
        score = max(
            name_ratio,
            informative_overlap * 0.9,
            generic_overlap * 0.7,
            best_token_similarity * 0.92 if generic_overlap > 0 else 0.0,
        )

    reasons: list[str] = []
    if exact_match:
        reasons.append("normalized_name")
    elif substring_match:
        reasons.append("substring_name")
    if informative_overlap >= 0.5:
        reasons.append("token_overlap")
    if best_token_similarity >= 0.88:
        reasons.append("fuzzy_name")
    if name_ratio >= 0.85:
        reasons.append("high_name_similarity")

    if score < 0.74 or not reasons:
        return None

    return {
        "id": supplier.id,
        "name": supplier.name,
        "location": (getattr(supplier, "location", None) or "").strip(),
        "match_reason": reasons,
        "score": round(score, 2),
        "requires_confirmation": True,
    }


def supplier_duplicate_candidates(root, supplier_name: str, *, limit: int = 5) -> list[dict]:
    normalized_query = normalize_supplier_name(supplier_name)
    if not normalized_query:
        return []

    suppliers = (
        root.Supplier.query.filter(
            root.Supplier.is_active.is_(True),
            root.Supplier.merged_into_supplier_id.is_(None),
        )
        .order_by(root.Supplier.name.asc())
        .all()
    )

    candidates: list[dict] = []
    for supplier in suppliers:
        candidate = supplier_duplicate_candidate(root, supplier_name, supplier)
        if candidate:
            candidates.append(candidate)

    candidates.sort(key=lambda item: (-float(item["score"]), item["name"].lower()))
    return candidates[:limit]
