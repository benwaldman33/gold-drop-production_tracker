# Gold Drop - Next Sprint Implementation Plan

The standalone extraction lab app now covers charge creation, scan-first lot entry, structured run execution, and guided run progression through completion. The next sprint should carry the extractor through the end-of-run closeout without falling back to Slack or the admin-heavy main form.

## Sprint Focus

Build `Standalone Extraction Run Closeout` on top of the existing charge, run-execution, and progression workflow.

The business sequence remains:

1. Buy
2. Receive
3. Find or scan the lot
4. Charge into reactor / start extraction
5. Record run execution details and guided progression
6. Capture end-of-run closeout and operator signoff
7. Hand off to downstream review / analytics

## Product Goal

Let extractors finish the normal production loop on the iPad by capturing the last operational details that still tend to live in Slack or memory, while keeping the workflow touch-first and audit-safe.

## Why This Is Next

The repo already has:

- a deployed standalone extraction app
- charge-first and scan-first entry
- an active reactor board with lifecycle transitions and history
- dedicated standalone run-execution screens with defaults and timers
- guided run progression through `Start Run -> Start Mixer -> Stop Mixer -> Start Flush -> Stop Flush -> Mark Run Complete`

What is still missing is the extractor's closeout loop:

- explicit end-of-run review on the tablet
- cleaner capture of any last production notes or corrections before final handoff
- clearer "this run is done" confirmation for the floor team

## User Stories

### Extractor

- As an extractor, I can finish a run on the iPad without jumping back to Slack for end-of-run notes.
- As an extractor, I can see which completion details are still missing before I close the run.
- As an extractor, I can confirm that a run is truly complete and hand it off cleanly.

### Assistant extractor

- As an assistant extractor, I can open the current run and understand whether it is still in execution or already in closeout.
- As an assistant extractor, I can add the final operational details with large controls instead of admin-form fields.

### Operations / audit

- As operations, I keep the same canonical run and charge history while making end-of-run operator data more consistent.
- As operations, I can review completed runs later without reconstructing the operator story from Slack.

## Scope For This Sprint

### In scope

- a dedicated standalone run-closeout step or panel
- clearer `ready to complete` vs `completed` run messaging
- touch-first capture for any remaining end-of-run fields that belong on the floor
- completion review / confirmation before final closeout
- operator-facing run summary after completion
- regression coverage for closeout flow and main-app compatibility

### Out of scope

- full downstream yield accounting
- lab / testing workflow changes
- scale integrations inside closeout
- Slack parser expansion for run-closeout fields

## UX Surfaces

### 1. Standalone run closeout

Extend the existing standalone route:

- `#/runs/charge/<charge_id>`

with a stronger closeout state that:

- summarizes the run before completion
- highlights missing required fields
- makes the final confirmation obvious on the iPad

### 2. Post-complete handoff

After a run is completed, the standalone app should give operators simple next actions:

- `Back to Reactors`
- `Charge Another Lot`
- `Open Completed Run`

### 3. Main-app visibility

The main app should continue to show the completed timestamps and execution details without any separate reconciliation step.

## Backend Changes

### Run closeout support

Reuse the existing charge-linked run endpoints and progression model, extending them only if closeout requires additional structured fields or validation.

### Main-app compatibility

Keep the standard run form and reporting paths readable/editable with any new closeout data captured from the standalone app.

## Test Plan

### Targeted tests during implementation

- standalone run closeout state and validation
- mobile extraction run endpoint compatibility for completed runs
- main-app run editing remains compatible with the saved closeout data

### Full-suite closeout before final commit

- standalone extraction app test suite
- full Python suite

## Definition Of Done

This sprint is done when:

- extractors can complete the practical end-of-run workflow on the tablet
- the completion state is obvious in both the standalone app and the main app
- operator closeout no longer depends on Slack for normal runs
- tests and docs are updated
