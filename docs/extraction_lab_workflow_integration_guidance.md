# Extraction Lab Workflow Integration Guidance

This note summarizes the review of the granular extraction-lab workflow PDFs against the current app code and existing SOP alignment documentation. It is intended as guidance for integrating the workflow more clearly into the program.

## Overall Assessment

The workflow documents are directionally strong and mostly match the current app architecture.

The phase structure is easier to understand than the raw app sequence:

- Phase 1: charge, reactor prep, and primary extraction
- Phase 2: flush cycle, recovery, and final purge
- Phase 3: booth shutdown and run completion
- Phase 4: wet THCA / HTE pour and handoff
- Phase 5: decision tree overview
- Phase 6: roles, timing, and key controls
- Phase 7: gaps and suggested improvements

This phase model should be used as the product structure for the operator workflow. It gives production staff a mental map before asking them to follow individual buttons.

## What Comports With The Code

The core sequence matches the implemented extraction progression in `services/extraction_run.py`:

1. Confirm vacuum down
2. Record primary solvent charge
3. Start primary soak
4. Start mixer
5. Stop mixer
6. Confirm filter clear
7. Start pressurization
8. Begin recovery
9. Begin flush cycle
10. Verify flush temperatures
11. Record flush solvent charge
12. Start flush
13. Stop flush
14. Confirm flow resumed
15. Start final purge
16. Stop final purge
17. Confirm final clarity
18. Complete shutdown
19. Mark run complete
20. Start post-extraction
21. Confirm initial wet THCA / HTE outputs

The docs also correctly identify several operational steps that are important but not fully modeled as first-class app stages today:

- reactor / tank readiness
- solvent path preparation
- loading biomass / baskets
- flush agitation and valve handling
- receiving container preparation
- post-run cleaning / reset

Those manual/inferred steps are useful because they show where the production team may feel the app is skipping over real work.

## Corrections To Make Before Treating The Docs As Canonical

### 1. Standardize The Decision Count

The documents currently use mixed wording:

- high-level overview says `4 Decision Gates`
- infographic says `3 Decision Branches` / `3 Decision Gates`

The workflow actually has four decision gates:

1. Lot ready to charge?
2. Flush temps acceptable?
3. Flow resumed?
4. Final clarity confirmed?

Recommendation:

- use `4 decision gates` everywhere
- describe only two of them as true loop branches:
  - flow resumed
  - final clarity confirmed

### 2. Treat Flush Temperature As A Hard Stop In The App

Operationally, `Flush Temps Acceptable?` reads like a branch. In the current code, it is stricter than that.

The app blocks progression when solvent chiller temperature is above `-40F`. The operator cannot record the flush solvent charge until temperature verification passes.

Recommendation:

- label this as `Hard Stop: Flush Temps Acceptable?`
- avoid describing it as a normal yes/no branch unless a supervisor override feature is added later
- keep the failed path as: correct temperature / capture evidence / re-check

### 3. Clarify When Handoff Actually Starts

`Select Post-Extraction Pathway` is useful, but it is not the same thing as the downstream team taking ownership.

In the current app:

- post-extraction is blocked until the extraction run is marked complete
- `Start Post-Extraction` requires a selected pathway
- `Confirm Initial Outputs` requires both wet THCA and wet HTE values

Recommendation:

- use `Ready for downstream handoff` after pathway selection
- use `Handoff started` after `Start Post-Extraction`
- use `Initial output handoff confirmed` only after both wet weights are recorded

### 4. Keep The Manual / Inferred Labeling

The manual/inferred labels are accurate and should remain visible. They prevent the workflow from implying that the app currently controls steps that it only implies.

Important manual/inferred steps to keep visible:

- reactor / tank readiness
- solvent tank / solvent path readiness
- physical biomass loading
- flush agitation / valve handling
- receiving containers and labels
- cleaning / reset before next run

These are the most likely areas where operators will say the app is hard to follow, because those steps happen in the room but are not prominent in the app.

## Current Implementation Update - 2026-05-25

The standalone extraction app now implements the most important control-flow recommendation from this review: booth execution is lockstep instead of a broad editable form.

Current behavior:

- the tablet renders only the active checkpoint inputs and the next allowed action
- later booth checkpoints remain hidden until the active predicate is satisfied
- the mobile API rejects future progression actions that do not match the current booth stage
- the mobile API filters operator writes so future-step booth fields cannot be saved early
- operators can request a one-step manager bypass with a reason when equipment/process conditions block a checkpoint
- approved bypasses use the existing supervisor notification override flow and write booth history

Remaining recommendations still apply for phase grouping, equipment-level prep/reset visibility, and selected manual checklist context.
## Product Integration Recommendations

### 1. Use The Four-Phase Operator Model In The App

The tablet should show the extraction run as four big phases:

1. Charge / Setup
2. Primary Extraction
3. Flush / Purge
4. Pour / Handoff

The current app now exposes a lockstep current-checkpoint progression, but the operator still needs phase context. A phase rail or large phase header would make the sequence easier to follow without reopening future-step controls.

### 2. Add Prep And Cleaning Visibility

The app should eventually make these visible as checklist-style steps:

- reactor ready
- solvent path ready
- receiving containers labeled
- post-run clean / reset complete

These do not all need to be hard stops at first. Even a visible checklist would make the workflow feel more complete.

### 3. Use Decision Gates As Training Anchors

The four decision gates are a good training structure:

- D1: Lot ready to charge?
- D2: Flush temps acceptable?
- D3: Flow resumed?
- D4: Final clarity confirmed?

The app should show D3 and D4 as explicit loops because the code already supports those loop states:

- flow adjustment required
- clarity adjustment required

### 4. Keep The Infographic For Managers, Not Operators

The full infographic is useful for supervisor review and training, but it is too dense for booth-side use.

Recommended usage:

- phase PDFs: operator reference / laminated run cards
- decision tree: training and exception handling
- high-level overview: manager orientation
- infographic: supervisor / implementation reference

### 5. Align Button Labels And Printed Step Names

The laminated/process documents should use the same labels as the app buttons wherever possible:

- Confirm Vacuum Down
- Record Solvent Charge
- Start Primary Soak
- Start Mixer
- Stop Mixer
- Confirm Filter Clear
- Start Pressurization
- Begin Recovery
- Begin Flush Cycle
- Verify Flush Temps
- Record Flush Solvent Charge
- Start Flush
- Stop Flush
- Confirm Flow Resumed
- Start Final Purge
- Stop Final Purge
- Confirm Final Clarity
- Complete Shutdown
- Mark Run Complete
- Start Post-Extraction
- Confirm Initial Outputs

This reduces translation friction for operators.

## Suggested Implementation Order

1. Add visible phase grouping to the standalone extraction app.
2. Add a compact progress rail showing current phase and next decision gate.
3. Add manual prep/reset checklist items as visible non-blocking steps.
4. Tighten wording around flush temperature as a hard stop.
5. Clarify post-extraction ownership states in the app copy.
6. Later, decide whether manual steps become required gates or remain training/checklist aids.

## Bottom Line

The workflow documents are a strong starting point and mostly reflect the code and SOP alignment documentation.

The main integration lesson is that the app currently captures the extraction checkpoints, but the production team experiences the job as a broader physical workflow. To make the app easier to follow, the program should show the physical prep, cleaning, ownership, and phase context around the existing app checkpoints.
