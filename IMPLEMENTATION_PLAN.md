# Gold Drop - Next Sprint Implementation Plan

The extraction-charge foundation is now live. The next sprint should make `Floor Ops` a stronger extractor control surface before adding another frontend like Slack intake or a standalone extractor app.

## Sprint Focus

Build `Reactor History + Board Filtering` on top of the existing extraction-charge and lifecycle workflow.

The business sequence remains:

1. Buy
2. Receive
3. Charge into reactor / start extraction
4. Run / complete / cancel
5. Testing can occur before buy, after receipt, or after extraction depending on supplier trust and process stage

This sprint is about improving the extractor-facing operational view after a charge exists.

## Product Goal

Give extractors and production leads a clearer reactor board that can answer:

- what is happening in each reactor right now
- what happened in that reactor earlier today
- which charges are pending vs running vs completed
- how to focus the board on the subset of work they care about

without forcing them to open every run or scan through raw lists.

## Why This Is Next

The repo already has the core operational backbone:

- persisted `ExtractionCharge`
- active reactor board
- reactor lifecycle actions
- same-day visibility for completed/cancelled charges
- timestamped charge state history in `AuditLog`
- settings-driven lifecycle requirements

What is still missing is the usability layer:

- a richer per-reactor history view
- board-level filtering / focus controls
- clearer extraction of "what matters right now" from the raw board

## User Stories

### Extractor

- As an extractor, I can filter the board to show only active or relevant reactor states.
- As an extractor, I can see what already happened in a given reactor today before I act on it.
- As an extractor, I can open a run from the board and reliably get back to the floor view.

### Production lead

- As a production lead, I can review today’s reactor activity without opening each run individually.
- As a production lead, I can distinguish pending, running, completed, and cancelled work at a glance.

### Operations / audit

- As an operator or auditor, I can see the time-ordered charge and lifecycle history for each reactor.
- As an operator or auditor, I can understand which actions occurred today vs which records have rolled off into longer-term history.

## Scope For This Sprint

### In scope

- richer same-day reactor history on `Floor Ops`
- board filters / focus mode on `Floor Ops`
- improved state summaries tied to current lifecycle states
- preserving context when navigating from the board into runs and back
- regression coverage for board filters and per-reactor history rendering

### Out of scope

- Slack extraction intake
- standalone extractor app
- connected-scale automation beyond current capture plumbing
- major new extraction data entities beyond the existing `ExtractionCharge`
- batch-journey graph work

## UX Surfaces

### 1. Active Reactor Board

Enhance the board so each reactor card can show:

- current state
- current lot / linked run context
- current queue depth
- same-day state history for that reactor
- same-day recent charges / completed work for that reactor

### 2. Floor Ops filtering

Add lightweight board filters such as:

- all reactors
- active only
- pending only
- running only
- completed / cancelled today

The filters should let extractors focus the page without leaving `Floor Ops`.

### 3. Reactor history section

Add a same-day reactor history surface that answers:

- which charges hit Reactor 1/2/3 today
- when each state change occurred
- which run was linked
- whether a charge completed or was cancelled

### 4. Navigation context

Continue improving board-to-run navigation so operator context is preserved and predictable.

## Backend Changes

### Service boundary

Extend the existing extraction-charge service rather than adding a second reactor-history service.

Likely additions:

- helpers to summarize same-day reactor history
- helpers to filter visible board cards by state/view mode
- helpers to group recent charges by reactor and day

### Query strategy

Use the existing `ExtractionCharge` plus `AuditLog` state history rather than introducing a new table.

Expected data sources:

- `ExtractionCharge`
- `Run`
- `PurchaseLot`
- `AuditLog` entries for `entity_type="extraction_charge"`

## Board Filtering Rules

Default board mode should still be `all`.

Planned filter categories:

- `all`
- `active`
- `pending`
- `running`
- `completed_today`
- `cancelled_today`

Filters should be safe if:

- there are more observed reactors than configured
- there are no current active charges
- only historical same-day charges exist for a reactor

## Reactor History Rules

For this sprint:

- show same-day history directly on `Floor Ops`
- retain timestamp ordering
- include lifecycle labels and linked run references when available

Longer-term history can continue to live in audit records until a dedicated history page is needed.

## Proposed Route / Entry Changes

Likely no new top-level route is needed.

Prefer enhancing:

- `GET /floor-ops`

Possible additions:

- query-string filters for board mode
- reactor-specific expansion or focus controls if needed

## Test Plan

### Targeted tests during implementation

- board filter rendering
- same-day reactor history rendering
- observed-reactor visibility when configuration lags
- preserved `return_to` behavior from `Floor Ops` into runs

### Full-suite closeout before final commit

- full Python suite
- affected standalone app suites only if touched

### New regression scenarios

- board shows Reactor 3 if activity exists there even when settings lag
- board filter hides unrelated states without dropping relevant current reactors
- same-day completed/cancelled history still appears where intended
- `Open Run` from `Floor Ops` preserves a return path back to `Floor Ops`
- preserve exact source lot allocation into the run
- scan flow opens the correct lot and preloads the charge form
- Slack-assisted flow preserves the same canonical allocation semantics

## Documentation To Update When This Ships

Core docs:

- `PRD.md`
- `README.md`
- `FAQ.md`
- `ENGINEERING.md`
- `CHANGELOG.md`

Conditional docs:

- `USER_MANUAL.md`
- API docs if new routes are exposed
- deployment/runbook docs if scan or standalone surfaces change

## Definition Of Done

- operators can start extraction from a specific received lot without using a generic workaround
- partial and full lot charges both work
- the reactor charge records exact source lot, pounds, reactor, time, and operator
- the resulting run context preserves explicit lot allocation
- scan-first workflow lands in the same charge flow
- testing state is visible at charge time without forcing one rigid upstream sequence
- targeted tests pass during development
- full Python suite passes before final commit
- affected docs are updated

## Follow-On Work After This Sprint

1. Standalone extractor app using the same extraction-charge backend
2. Slack confidence buckets and guided manual resolution into extraction charge
3. Connected-scale assisted charge confirmation
4. Richer Batch Journey graph with charge-event nodes and allocation edges
5. Deeper testing and post-extraction department workflows
