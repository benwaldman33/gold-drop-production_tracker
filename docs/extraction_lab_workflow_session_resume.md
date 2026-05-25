# Extraction Lab Workflow Session Resume

Date: 2026-05-06

Purpose: preserve the current workflow-document review state so a future session can resume without rediscovering context.

## What Prompted This Work

The production team reviewed the extraction lab app and reported that the process was not easy to follow. The working hypothesis is that the app captures important extraction checkpoints, but the booth team experiences the job as a broader physical workflow with prep, equipment handling, cleaning, labeling, and handoff steps that are not always visible in the app.

## Documents Created In This Session

Generated in `/docs`:

- `extraction_lab_biomass_flow.html`
- `extraction_lab_biomass_flow.pdf`
- `extraction_lab_biomass_flowchart.html`
- `extraction_lab_biomass_flowchart.pdf`
- `extraction_lab_decision_tree.html`
- `extraction_lab_decision_tree.pdf`
- `extraction_lab_workflow_integration_guidance.md`
- `extraction_lab_workflow_session_resume.md`

Additional workflow PDFs/images were later added by the user:

- `extraction_lab high level overview.pdf`
- `extraction_lab phase1.pdf`
- `extraction_lab phase2.pdf`
- `extraction_lab phase3.pdf`
- `extraction_lab phase4.pdf`
- `extraction_lab phase5.pdf`
- `extraction_lab phase6.pdf`
- `extraction_lab phase7_gaps_improvements.pdf`
- `extraction_lab_infographic.pdf`
- `extraction flow chart original.png`

## Current Reviewed Understanding

The current code-backed extraction progression in `services/extraction_run.py` is:

1. `Confirm Vacuum Down`
2. `Record Solvent Charge`
3. `Start Primary Soak`
4. `Start Mixer`
5. `Stop Mixer`
6. `Confirm Filter Clear`
7. `Start Pressurization`
8. `Begin Recovery`
9. `Begin Flush Cycle`
10. `Verify Flush Temps`
11. `Record Flush Solvent Charge`
12. `Start Flush`
13. `Stop Flush`
14. `Confirm Flow Resumed`
15. `Start Final Purge`
16. `Stop Final Purge`
17. `Confirm Final Clarity`
18. `Complete Shutdown`
19. `Mark Run Complete`
20. `Start Post-Extraction`
21. `Confirm Initial Outputs`

Post-extraction handoff is blocked until `run_completed_at` exists. `Start Post-Extraction` requires a selected pathway. `Confirm Initial Outputs` requires both wet THCA and wet HTE values.

## Review Of Newer Workflow PDFs

The phase PDFs and high-level overview mostly comport with the code and the SOP alignment documentation.

Strengths:

- The phase model is much easier to follow than the raw app progression.
- Manual/inferred steps are clearly identified instead of pretending the app captures everything.
- Decision and branch loops for `Flow Resumed?` and `Final Clarity Confirmed?` align with the code's loop states.
- Phase 7 captures the right product gaps: run cards, phase grouping, visual progress rail, prep/cleaning visibility, role initials, and unresolved operating decisions.

Corrections before treating those PDFs as canonical:

- Standardize wording to `4 decision gates`:
  - D1: Lot ready to charge?
  - D2: Flush temps acceptable?
  - D3: Flow resumed?
  - D4: Final clarity confirmed?
- Treat D2 as a hard stop in the app, not an ordinary yes/no branch. The code blocks progression if solvent chiller temperature is above `-40F`.
- Clarify handoff states:
  - pathway selected = ready for downstream handoff
  - `Start Post-Extraction` = handoff started
  - `Confirm Initial Outputs` = initial output handoff confirmed

## Comparison To `extraction flow chart original.png`

The original PNG is an equipment/SOP flow, not an app workflow.

It starts at `Vac Down Reactor`, while the app and newer charts start earlier with:

- scan / enter biomass lot
- confirm lot readiness
- record charge
- select reactor
- link charge to run
- load biomass / baskets

It also ends at booth shutdown, while the current app and newer charts continue through:

- mark run complete
- select post-extraction pathway
- start post-extraction
- record wet HTE and wet THCA grams
- confirm initial outputs
- clean/reset as a visible post-run step

Original PNG details that are more granular than the current app:

- small solvent tank used to burp bottom of reactor
- attach nitrogen line to top of reactor
- turn heat exchangers on/off
- sight glass on dewax vessel clear
- close nitrogen valve in reactor
- close bottom outlet
- close inlet and oily valves on stingers
- close inlets into recovery vessel
- gas level reached for flush
- burp nitrogen first before sending flush solvent
- open recovery valves and filtration valves to lower PSI

Those details should be treated as missing equipment-level context that can be added as checklist/supporting detail under existing app stages.

Specific differences:

- Original has two visual decisions: `Flow Resumed?` and `Everything's Clear?`
- Newer charts/code use four decision gates: lot readiness, flush temperature, flow resumed, final clarity.
- Original says final burp is roughly 30 minutes. Code treats final purge target as optional/settings-driven.
- Original says flush soak is 10 minutes and mixer runs last 5 minutes. Code has flush timing but no separate flush mixer timer.

Best use of original PNG:

- use as source material for equipment-level SOP detail
- do not use as the app workflow source of truth
- integrate selected details into the newer phase model as checklist/context

## Recommended Product Direction

Use the newer phase model as the app integration structure:

1. Charge / Setup
2. Primary Extraction
3. Flush / Purge
4. Pour / Handoff

Near-term app improvements:

1. Add visible phase grouping in the standalone extraction app.
2. Add a compact progress rail showing current phase and upcoming decision gate.
3. Add manual prep/reset checklist items as visible non-blocking steps.
4. Wording: make flush temperature a hard-stop gate.
5. Clarify downstream handoff language in app copy.
6. Later decide whether manual steps become required gates or remain training/checklist aids.

## Current Local State Notes

The `/docs` folder is currently untracked as a whole in Git status because these workflow assets are new. Existing unrelated untracked root files remain:

- `Journey Graphic.png`
- `screenshot Start Extraction Charge.png`

Do not assume those root files should be committed unless explicitly requested.

## 2026-05-25 Update

The next implementation step changed: the app now has a lockstep extraction booth progression and manager-approved bypass path.

Implemented since this note was first written:

- current checkpoint inputs only on the standalone extraction run screen
- future booth actions rejected by the mobile API until the current stage is satisfied
- future-step booth fields ignored by the mobile API before the checkpoint is active
- `Request Manager Bypass` with required operator reason
- supervisor-notification approval path for bypasses
- `Use Approved Bypass` advancing exactly one booth stage with booth event history

Remaining useful follow-up work:

- visible phase headers / progress rail
- equipment-level prep/reset checklist context
- clearer heat-exchanger, valve, and gas-level wait details from the original SOP flow
## Best Resume Point

If asked to resume this work, start from:

1. `docs/extraction_lab_workflow_integration_guidance.md`
2. `docs/extraction_lab_workflow_session_resume.md`
3. `docs/extraction flow chart original.png`
4. `services/extraction_run.py`
5. `standalone-extraction-lab-app/src/app.js`

The next meaningful build step after the lockstep/bypass implementation is to improve operator context in the app UX:

- phase headers/rail
- visible prep and cleaning checklist
- clearer hard-stop/branch labels
- downstream handoff state wording
