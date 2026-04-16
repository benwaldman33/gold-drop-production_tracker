# Gold Drop — What’s Next (Execution Plan)

This is the immediate follow-on plan after Step 1 (test/app startup stabilization).

## Step 2 — Extract first vertical slice (Purchases + Biomass Pipeline)

### Goal
Move the highest-coupling domain into a modular boundary **without changing user-visible behavior**.

### Deliverables
1. Create `purchases` Blueprint module and move purchase/pipeline routes there.
2. Create `services/purchases.py` and move:
   - approval stamping/gates,
   - status transition checks,
   - budget checks,
   - inventory lot maintenance hooks.
3. Create `policies/purchase_status.py` with a single transition matrix used by both single-edit and batch-edit flows.
4. Keep existing URLs/templates working (thin wrappers allowed during migration).

### Definition of done
- All current purchase + biomass pipeline tests pass.
- No route URL changes required by operators.
- One shared transition policy is used by both form save and batch edit paths.

---

## Step 3 — Batch Journey backend (API first)

### Goal
Ship a reliable derived timeline before investing in complex UI.

### Deliverables
1. Add `GET /api/purchases/<id>/journey`.
2. Return normalized stage events:
   - declared, testing, committed, delivered, inventory, extraction, post_processing, sales.
3. Include state + timestamps + metrics + source links per stage.
4. Add unit tests for:
   - unapproved delivered batch,
   - partial lot consumption,
   - soft-deleted/archived behavior.

### Definition of done
- API contract documented and tested.
- Output is sufficient to drive a timeline/stepper UI with no extra business logic in templates.

---

## Step 4 — Journey UI

### Goal
Expose the timeline from Purchases with minimal operator friction.

### Deliverables
1. Add “View Journey” entrypoint on Purchases list and Purchase edit/detail.
2. Build timeline component consuming API payload only.
3. Support “include archived” toggle and source-record drill links.

### Definition of done
- Operators can answer “where is this batch now, and what happened before?” from one screen.

---

## Risk watchlist (during next steps)
- Keep Flask app context concerns out of low-level utility code.
- Avoid duplicating transition logic across routes and templates.
- Track SQLAlchemy legacy `Query.get()` warnings for follow-up modernization.

---

## Progress update (Apr 2026)

- Step 3 + Step 4 are shipped (Journey API/UI/export).
- Follow-up hardening shipped:
  - shared journey purchase-loading/error helpers in `blueprints/purchases.py`
  - explicit Journey export format validation (`json|csv`, otherwise `400`)
  - integration regression test for unknown format requests
- `SystemSetting.get` moved to `db.session.get(...)` to avoid legacy `Query.get()` usage in that path.
