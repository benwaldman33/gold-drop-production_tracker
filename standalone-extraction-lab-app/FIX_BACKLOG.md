# Standalone Extraction Lab — Fix Backlog

Tracked UX and workflow fixes for `standalone-extraction-lab-app/`, plus **cross-app** extraction items that also touch the main app and shared mobile API.  
**Quick fixes** ship as soon as they unblock operators. **Full fixes** are intentional follow-ups once the foundation is stable.

## Status key

| Status | Meaning |
|--------|---------|
| `open` | Not started |
| `in_progress` | Active work |
| `done` | Shipped |

---

## Done — Post-extraction quick fix (2026-06-14)

**Status:** `done`

- Operator post-extraction workflow moved into the same `run-execution` form (no separate downstream form).
- Persistent `post_extraction_pathway` hidden field on supervisor and operator forms.
- Pathway choice auto-saves to the server on tap.
- `Start Post-Extraction` payload falls back to `state.run.post_extraction_pathway` when collapsed steps omit the field.
- Page-level **Save** / **Save Run** hidden after `run_completed_at`; operators use guided step actions.

---

## Full fix — Post-extraction uniform step workflow

**Status:** `open`  
**Priority:** High (operator clarity)  
**Deferred after:** post-extraction quick fix (single form, auto-save pathway, hide global Save)

### Problem

Post-extraction still mixes patterns: some fields use manual datetime entry, some steps rely on progression buttons, and copy says “save as you move.” Booth extraction uses **one primary action per step that saves inline**; post-extraction should match.

### Scope

1. **One primary action per step** — each guided step saves and advances from the bottom of that step only; no separate page-level Save during post-extraction.
2. **Server-set timestamps** — where SOP allows, set `post_extraction_started_at`, `post_extraction_initial_outputs_recorded_at`, etc. when the step button is clicked (not orphan `datetime-local` fields).
3. **Remove orphan datetime pickers** — replace with Start/Now stamps where manual override is still required; confirm SOP with operators before removing backdate capability.
4. **Supervisor parity** — same step-action model on the supervisor run screen (not only operator view).
5. **Copy update** — replace “Work top to bottom and save as you move” with “Complete each step in order.”
6. **Regression tests** — add frontend or API tests for pathway persist + Start Post-Extraction + Confirm Initial Outputs without a global Save.

### Acceptance criteria

- Operator never scrolls away from the active step to persist post-extraction data.
- Pathway, handoff start, and initial outputs work without using a top-of-page Save button.
- Supervisor and operator views follow the same save semantics.
- Documented in `USER_MANUAL.md` and `standalone-extraction-lab-app/README.md`.

---

## Cross-app — Reactor available when physically emptied (pour out)

**Status:** `done` (2026-06-14)

### Shipped

- New charge lifecycle state **`cleared`** (`Reactor emptied`) after `completed`.
- **`charge_visible_on_board`** hides cleared charges immediately — reactor card shows **Empty**.
- **`Reactor Emptied`** action on completed charges in:
  - standalone extraction lab **Reactors** board
  - standalone extraction lab **Open Run** (after post-extraction)
  - main app **Floor Ops → Active Reactor Board**
- Settings include **Reactor emptied** under reactor lifecycle controls.
- Shared mobile API transition: `POST .../charges/{id}/transition` with `target_state: "cleared"`.

- **Done (2026-06-14):** Form draft sync — checkpoint and settings inputs keep typed values across screen refreshes, toasts, and step actions. See `CHANGELOG.md` 2026-06-14.

---

## Open items (other)

_Add future extraction-lab fixes here as they are identified._
