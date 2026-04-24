# Gold Drop - Extraction Booth SOP Alignment Plan

This document translates the `Extraction Booth Procedure` SOP into concrete application behavior.

The goal is straightforward:

- the extraction app(s) should match the booth SOP
- the app should guide the operator through the required sequence
- required data, control points, and evidence should be captured in-system
- supervisor review should happen on structured records instead of Slack memory or free-text notes

## Scope

This plan covers the booth-side extraction workflow only:

1. primary extraction
2. flush cycle
3. final purge
4. extraction closeout documentation

This plan intentionally stops before the post-extraction THCA / HTE workflow already documented elsewhere.

## Current baseline

Current shipped support already exists for:

- `ExtractionCharge` creation before run finalization
- charge-to-run linkage
- run execution draft fields on `Run`
- tablet-guided progression through:
  - `Start Run`
  - `Start Mixer`
  - `Stop Mixer`
  - `Start Flush`
  - `Stop Flush`
  - `Mark Run Complete`
- downstream handoff after run completion

Current shipped support is not sufficient for full booth-SOP alignment because the app does not yet model:

- vacuum confirmation
- solvent charge checkpoints
- soak steps as first-class timed workflow stages
- nitrogen / burp / pressurization checkpoints
- recovery / filtration / heat-exchanger checkpoints
- critical temperature verification and evidence capture
- decision points such as:
  - flow resumed
  - system clear enough to proceed
- final purge and shutdown checklist

## Product direction

The booth workflow should become a guided, reactor-centered execution record.

That means:

- the standalone extraction app becomes the operator surface for the SOP
- the main run form remains the supervisor correction / audit surface
- the system should guide the operator step-by-step instead of exposing one flat form
- every critical SOP step should become either:
  - a required action
  - a required measurement
  - a required decision
  - a required evidence capture

## Recommended data model

### Keep on `Run`

Keep summary and business outcome fields on `Run`:

- reactor number
- source lot / charge linkage
- biomass input weight
- blend / fill / flush summary counts
- mixer and flush timing summaries
- wet THCA / wet HTE outputs
- post-extraction fields already implemented
- notes

These remain the canonical summary for reporting and downstream use.

### Add a new run-linked booth execution layer

Add a new `ExtractionBoothSession` table linked one-to-one to `Run`.

Purpose:

- hold booth-specific execution state without overloading `Run`
- let the booth SOP evolve without destabilizing downstream reporting fields
- separate "operator execution workflow" from "run business summary"

Recommended fields:

- `id`
- `run_id`
- `charge_id`
- `started_at`
- `completed_at`
- `current_stage_key`
- `operator_user_id`
- `status`
  - `in_progress`
  - `completed`
  - `cancelled`
- `sop_version`
- `created_at`
- `updated_at`

### Add a new booth event / checkpoint table

Add `ExtractionBoothEvent` as an additive audit/event table linked to `ExtractionBoothSession`.

Purpose:

- preserve step history
- support repeat actions when the operator needs to retry or continue
- avoid destructive overwrites of important checkpoints

Recommended fields:

- `id`
- `session_id`
- `run_id`
- `event_key`
- `event_label`
- `stage_key`
- `occurred_at`
- `recorded_by_user_id`
- `decision_value`
- `numeric_value`
- `text_value`
- `payload_json`
- `notes`
- `created_at`

Examples:

- `reactor_vacuum_confirmed`
- `primary_solvent_charged`
- `primary_soak_started`
- `primary_soak_completed`
- `mixer_started`
- `mixer_stopped`
- `basket_filter_cleared`
- `nitrogen_pressurization_started`
- `recovery_flow_started`
- `heat_exchangers_enabled`
- `flush_temp_verified`
- `flush_solvent_charged`
- `flush_soak_started`
- `flush_soak_completed`
- `flow_resumed_decision`
- `final_purge_started`
- `final_purge_completed`
- `clarity_confirmed`
- `shutdown_completed`

### Add booth evidence records

Add `ExtractionBoothEvidence` linked to `ExtractionBoothSession`.

Purpose:

- store required photos and attached proof for control points
- avoid mixing booth evidence with unrelated purchase or run attachments

Recommended fields:

- `id`
- `session_id`
- `run_id`
- `evidence_type`
  - `solvent_chiller_temp_photo`
  - `plate_temp_photo`
  - `other`
- `file_path`
- `captured_at`
- `captured_by_user_id`
- `notes`
- `created_at`

## SOP-to-system mapping

### 1. Primary extraction

#### Step 1 - Vac Down Reactor

System behavior:

- operator sees `Confirm Vacuum Down`
- action records:
  - timestamp
  - operator
  - optional note

Validation:

- required before solvent can be charged

Audit:

- write `ExtractionBoothEvent(event_key="reactor_vacuum_confirmed")`

#### Step 2 - Charge Solvent

System behavior:

- operator enters solvent charge weight
- default expected value can be prefilled as `500 lbs`
- action button: `Record Solvent Charge`

Recommended fields:

- `primary_solvent_charge_lbs`
- `primary_solvent_charged_at`

Validation:

- required before primary soak can start
- weight must be positive

Audit:

- event row with charge weight in `numeric_value`

#### Step 3 - Initial Soak and Agitation

System behavior:

- guided action `Start Primary Soak`
- guided action `Start Mixer`
- guided action `Stop Mixer`
- guided action `End Primary Soak`

Recommended fields:

- `primary_soak_started_at`
- `primary_soak_completed_at`
- `primary_mixer_started_at`
- `primary_mixer_completed_at`

Validation:

- soak must start after solvent charge
- mixer cannot start before primary soak starts
- mixer cannot stop before it starts
- soak cannot complete before it starts

Recommended policy:

- first release should warn, not hard-block, when duration differs from SOP target
- target durations should be shown:
  - primary soak target `30 minutes`
  - mixer target `5 minutes during soak`

Audit:

- event rows for each step

#### Step 4 - Clear Basket Filter and Pressurize

System behavior:

- guided action `Confirm Basket Filter Cleared`
- guided action `Start Nitrogen Pressurization`

Recommended fields:

- `basket_filter_cleared_at`
- `nitrogen_pressurization_started_at`

Validation:

- must happen after primary soak

Audit:

- separate event rows

#### Step 5 - Send Gas to Filtration and Recovery

System behavior:

- guided action `Begin Flow To Recovery`
- guided action `Turn Heat Exchangers On`

Recommended fields:

- `recovery_flow_started_at`
- `heat_exchangers_enabled_at`

Validation:

- must happen after pressurization begins

Audit:

- separate event rows

#### Step 6 - Shutdown when clear

System behavior:

- operator records a required decision:
  - `Sight Glass Clear?`
  - values:
    - `yes`
    - `not_yet`
- when `yes`, next actions become available:
  - `Nitrogen Closed`
  - `Reactor Outlet Closed`
  - `Heat Exchangers Off`

Recommended fields:

- `dewax_clear_decision`
- `dewax_clear_confirmed_at`
- `nitrogen_closed_at`
- `reactor_outlet_closed_at`
- `heat_exchangers_disabled_at`

Validation:

- clear decision required before closure actions

Audit:

- one decision event plus one event per closure action

#### Step 7-8 - Close oily/inlet valves and recovery vessel inlets

System behavior:

- use a grouped checklist card:
  - `Stinger inlet/oily valves closed`
  - `Recovery vessel inlets closed`

Recommended fields:

- `stinger_valves_closed_at`
- `recovery_vessel_inlets_closed_at`

Validation:

- required before moving into flush cycle

Audit:

- one event per checklist item

### 2. Flush cycle

#### Step 9 - Begin Flush Cycle

System behavior:

- replace the coarse current `Start Flush` step with:
  - `Begin Flush Cycle`

Recommended fields:

- `flush_cycle_started_at`

Validation:

- primary extraction closeout checklist must be complete

Audit:

- event row

#### Step 10 - Verify Solvent Temperature

System behavior:

- show a dedicated critical-control card
- operator enters:
  - solvent chiller temperature
  - plate temperature
- operator uploads:
  - solvent chiller photo
  - plate temperature photo
- operator confirms:
  - `Below -40F verified`

Recommended fields:

- `flush_solvent_chiller_temp_f`
- `flush_plate_temp_f`
- `flush_temp_verified_at`
- `flush_temp_threshold_passed`

Validation:

- temperatures and both photos required before flush solvent can be recorded
- soft-warning or hard-block policy:
  - if temperature is above `-40F`, block continuation unless supervisor override exists later

Audit:

- one event for each measurement
- one evidence record for each photo
- one event for threshold confirmation

Slack note:

- the SOP currently requires Slack posting, but Slack integration is not reliable enough to be a hard dependency right now
- first release should support:
  - `Slack temperature post completed` checkbox
  - optional note field
- do not block the workflow on Slack until Slack is production-reliable again

Recommended field:

- `flush_temp_slack_post_confirmed_at`

#### Step 11 - Send Flush Solvent

System behavior:

- action `Record Flush Solvent Charge`
- capture flush solvent lbs

Recommended fields:

- `flush_solvent_charge_lbs`
- `flush_solvent_charged_at`

Validation:

- requires temperature verification complete

Audit:

- event row with numeric amount

#### Step 12 - Flush Soak

System behavior:

- action `Start Flush Soak`
- action `Start Mixer`
- action `Stop Mixer`
- action `End Flush Soak`

Recommended fields:

- `flush_soak_started_at`
- `flush_soak_completed_at`
- `flush_mixer_started_at`
- `flush_mixer_completed_at`

Validation:

- requires flush solvent charge recorded

Recommended policy:

- show target durations:
  - flush soak target `10 minutes`
  - mixer target `last 5 minutes`

Audit:

- event rows for each step

#### Step 13 - Burp and Re-Pressurize

System behavior:

- action `Confirm Nitrogen Burp`
- action `Restart Pressurization`

Recommended fields:

- `flush_burp_confirmed_at`
- `flush_repressurization_started_at`

Validation:

- required after flush soak

Audit:

- event rows

#### Step 14 - Resume Flow to Recovery

System behavior:

- action `Resume Recovery Flow`
- action `Turn Heat Exchangers On`
- required decision:
  - `Has Flow Resumed?`
  - values:
    - `yes`
    - `no_adjusting`

When flow has not resumed:

- let operator add a valve-adjustment note
- allow repeated `Has Flow Resumed?` decision until `yes`

Recommended fields:

- `flush_recovery_resumed_at`
- `flush_heat_exchangers_enabled_at`
- `flow_resumed_decision`
- `flow_resumed_confirmed_at`
- `flow_adjustment_notes`

Validation:

- run cannot advance to final purge until `flow_resumed_decision=yes`

Audit:

- event rows for action and decision
- repeatable decision history should be preserved

### 3. Final purge

#### Step 15 - Push Nitrogen and Begin Burping

System behavior:

- action `Start Final Purge`

Recommended fields:

- `final_purge_started_at`

Validation:

- requires resumed recovery flow success

Audit:

- event row

#### Step 16 - Final Burp

System behavior:

- action `End Final Purge`
- system computes duration
- required decision:
  - `System Clear Enough To Proceed?`
  - values:
    - `yes`
    - `not_yet`

When `not_yet`:

- keep purge active or allow another purge cycle
- require note if operator continues past one failed clarity check

Recommended fields:

- `final_purge_completed_at`
- `final_purge_duration_minutes`
- `final_clarity_decision`
- `final_clarity_confirmed_at`

Validation:

- run closeout blocked until clarity decision is `yes`

Audit:

- event row for purge completion
- event row for clarity decision

#### Step 17 - Shutdown and Closeout

System behavior:

- grouped final shutdown checklist:
  - `Recovery inlets closed`
  - `Filtration pump-down started`
  - `Nitrogen off`
  - `Dewax inlet closed`
- final button:
  - `Complete Booth Process`

Recommended fields:

- `final_recovery_inlets_closed_at`
- `filtration_pumpdown_started_at`
- `nitrogen_turned_off_at`
- `dewax_inlet_closed_at`
- `booth_process_completed_at`

Validation:

- checklist must be fully complete before booth process can be completed
- booth process completion should set the booth session to `completed`
- run-level `run_completed_at` should represent extraction completion, but after SOP alignment it should be tied to booth closeout rather than the current coarse flush stop flow

Audit:

- one event per checklist item
- one final completion event

## Operator UI design

### Primary surface

Use the standalone extraction app as the primary booth surface.

The booth execution screen should be:

- reactor-centered
- one active run at a time
- top-to-bottom step flow
- tap-first
- very low keyboard dependence

### Layout recommendation

The run screen should be reorganized into workflow cards:

1. `Run Header`
   - reactor
   - lot
   - supplier
   - strain
   - charged lbs
2. `Primary Extraction`
3. `Flush Cycle`
4. `Final Purge`
5. `Required Evidence`
6. `Extraction Summary`
7. `Post-Extraction Handoff`

### Interaction pattern

Each workflow card should show:

- current step label
- short instruction
- required actions
- required measurements
- warnings if a prerequisite is missing
- completed state with timestamp and operator

### Design rule

Do not expose all booth fields as one flat form on the tablet.

The operator should see:

- the current step
- the next allowed action
- supporting measurements for that step
- a compact history of what was already completed

## Supervisor UI design

The main run form remains the fallback and correction surface.

Recommended supervisor additions:

- booth session summary block
- full booth event history
- evidence thumbnails / file links
- explicit control-point pass/fail state
- override capability for authorized roles only

Recommended role boundary:

- operators can execute normal workflow
- supervisors can correct timestamps, annotate deviations, and approve overrides

## Validation rules

### Hard-block validations

These should block progression:

- vacuum confirmation missing before solvent charge
- temp verification missing before flush solvent charge
- required evidence photos missing before flush continuation
- flow-resumed decision not confirmed before final purge
- clarity decision not confirmed before final shutdown
- final shutdown checklist incomplete before booth completion

### Warning-only validations for first release

These should warn but not block in the first implementation:

- primary soak not equal to 30 minutes
- flush soak not equal to 10 minutes
- mixer duration not equal to target window
- final purge duration shorter or longer than expected

Rationale:

- operators need the workflow first
- strict duration policy can be tightened after real production feedback

### Override policy

If hard-blocked SOP exceptions must be allowed, add explicit supervisor override later.

If added, an override must capture:

- overriding user
- reason
- timestamp
- affected checkpoint

## Audit and deviations

The app should support deviations explicitly.

Recommended approach:

- allow operator to add a deviation note on any blocked or warning step
- add `deviation_flag` and `deviation_notes` support to booth events where needed
- add a booth-session summary indicator:
  - `standard`
  - `completed_with_deviation`

This is better than hiding deviations in one generic run note.

## Attachments and evidence

The booth SOP currently calls for:

- solvent chiller temperature photo
- plate temperature photo
- Slack temperature post evidence

Recommended implementation:

- photo capture/upload directly on the booth step
- those files attach to `ExtractionBoothEvidence`
- the supervisor surface shows evidence inline

Do not require Slack as the primary recordkeeping mechanism for booth control points.

The app should become the system of record.

## Recommended implementation phases

### Phase 1 - Booth session foundation

Build:

- `ExtractionBoothSession`
- `ExtractionBoothEvent`
- stage machine for primary extraction / flush / purge
- tablet workflow shell with staged cards

Definition of done:

- current coarse progression is replaced by booth stage progression
- booth session is linked to run and charge

### Phase 2 - Critical control capture

Build:

- vacuum confirmation
- solvent charge amount capture
- soak timers
- temp measurements
- temp evidence upload
- flow / clarity decision nodes

Definition of done:

- all critical SOP controls exist as structured data

### Phase 3 - Final purge and closeout

Build:

- final purge timer
- final shutdown checklist
- booth completion action
- supervisor booth-session summary in main app

Definition of done:

- booth process can be completed end-to-end in-system

### Phase 4 - Deviation and override handling

Build:

- deviation flags
- supervisor override workflow
- deviation reporting

Definition of done:

- SOP exceptions are explicit and auditable

### Phase 5 - Reporting and documentation alignment

Build:

- extraction booth summary views
- exportable booth control history
- evidence review surface

Definition of done:

- supervisors and compliance users can review booth execution without reconstructing it from notes

## Recommended first implementation slice

If work starts immediately, the first slice should be:

1. add `ExtractionBoothSession`
2. add `ExtractionBoothEvent`
3. replace the current coarse progression with:
   - `Confirm Vacuum Down`
   - `Record Solvent Charge`
   - `Start Primary Soak`
   - `Start / Stop Mixer`
   - `Confirm Filter Clear`
   - `Start Pressurization`
   - `Begin Recovery`
   - `Begin Flush Cycle`
4. defer photo upload and final purge checklist to the next slice if needed

This gives the project a real booth-SOP backbone quickly without trying to ship the entire SOP in one jump.

## Open decisions to confirm with operations

These points should be confirmed before implementation hardens:

1. should `run_completed_at` mean:
   - end of current extraction timing flow, or
   - full booth closeout after final purge and shutdown?
2. does the team want strict hard-blocking on `below -40F`, or warning-first rollout?
3. should the operator upload temperature photos directly from the iPad during the run?
4. is Slack confirmation still required as policy, or should the app replace that requirement?
5. does each run always have exactly one booth session, or can a run be paused / resumed across multiple sessions?

## Bottom line

The current app is a usable extraction run tracker.

This plan moves it to what the SOP actually requires:

- a controlled booth execution workflow
- structured critical-control data
- required evidence capture
- explicit decision points
- auditable completion and deviations
