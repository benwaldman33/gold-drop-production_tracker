# Gold Drop - Next Sprint Implementation Plan

The extraction-charge foundation and reactor board are now live. The next sprint should add Slack as an alternate intake path into that same canonical extraction-charge workflow.

## Sprint Focus

Build `Slack Extraction Intake` on top of the existing extraction-charge, run-prefill, and reactor-board workflow.

The business sequence remains:

1. Buy
2. Receive
3. Charge into reactor / start extraction
4. Run / complete / cancel
5. Testing can occur before buy, after receipt, or after extraction depending on supplier trust and process stage

This sprint is about adding another entry channel without creating a second extraction process model.

## Product Goal

Let a structured Slack production message create the same `ExtractionCharge` record that the main app and scan flows already use, then open the run form with that charge attached.

## Why This Is Next

The repo already has:

- Slack production-message parsing
- Slack import preview and apply flows
- persisted `ExtractionCharge`
- run prefill from charge, scan, and Slack sources
- `Floor Ops` surfaces that understand pending / running / completed charge records

What is still missing is a Slack path that creates the charge event itself instead of only pre-filling a generic run.

## User Stories

### Extractor

- As an extractor, I can open a Slack import preview and create an extraction charge directly from that message.
- As an extractor, I can have the charge appear on `Floor Ops` immediately, before the run is saved.

### Slack importer

- As a Slack importer, I can resolve supplier and lot ambiguity on the preview page before creating a charge.
- As a Slack importer, I can still use the existing run flow when one Slack message needs a split allocation across multiple lots.

### Operations / audit

- As an operator or auditor, I can see that the charge source was Slack and trace it back to the ingested message.

## Scope For This Sprint

### In scope

- Slack import preview action to create an extraction charge
- reuse of supplier / lot resolution from the existing Slack preview page
- single-lot enforcement for Slack-created charges
- charge prefill handoff into `runs/new`
- regression coverage for Slack charge creation and multi-lot rejection

### Out of scope

- standalone extractor app
- connected-scale automation beyond current capture plumbing
- multi-lot Slack charge events
- new extraction entities beyond the existing `ExtractionCharge`
- batch-journey graph work

## UX Surfaces

### 1. Slack import preview

Add a second operator action alongside `Create run from Slack`:

- `Create extraction charge from Slack`

This action should only be used when the message has:

- a parsed reactor number
- a parsed biomass weight
- exactly one resolved source lot

### 2. Existing run flow remains

Keep `Create run from Slack` for cases where:

- the operator wants a split allocation across multiple lots
- the Slack message is not ready to become a canonical charge record yet

### 3. Floor Ops continuity

A Slack-created charge should immediately show up in:

- `Active Reactor Board`
- `Reactor Charge Queue`
- `Reactor History Today`

because it is the same persisted `ExtractionCharge`.

## Backend Changes

### Service boundary

Reuse the existing extraction-charge service and Slack preview/apply flow.

Likely additions:

- one new apply route for Slack -> charge
- shared helper logic for selecting supplier ids and candidate lots
- direct population of `SCAN_RUN_PREFILL_SESSION_KEY` from the created Slack charge

### Data rules

- `ExtractionCharge.source_mode = "slack"`
- `ExtractionCharge.slack_ingested_message_id = SlackIngestedMessage.id`
- use the Slack message timestamp as the default `charged_at`

### Allocation rules

Slack charge creation must enforce exactly one lot allocation.

If the operator selects multiple lots, or no single lot can be suggested safely:

- do not create a charge
- tell the operator to use `Create run from Slack` instead

## Proposed Route / Entry Changes

Add:

- `POST /settings/slack-imports/<msg_id>/apply-charge`

Reuse:

- `GET /settings/slack-imports/<msg_id>/preview`
- `POST /settings/slack-imports/<msg_id>/apply-run`

## Test Plan

### Targeted tests during implementation

- Slack preview shows the new charge action when reactor + weight are present
- Slack charge creation creates one `ExtractionCharge`
- Slack charge creation writes run prefill session data
- multi-lot Slack allocations are rejected for charge creation

### Full-suite closeout before final commit

- full Python suite
- affected standalone app suites only if touched

## Definition Of Done

This sprint is done when:

- a Slack preview can create a valid `ExtractionCharge`
- the new run form opens with that charge attached
- the created charge shows on `Floor Ops`
- split allocations are rejected from the charge path with a clear message
- regression tests and docs are updated
