# UX Role And Workflow Implementation Plan

## Purpose

This plan turns `UX_ROLE_WORKFLOW_PLAN.md` into an implementation sequence.

The strategic goal is to reduce product clutter without removing capability.

The practical goal is to make the most common workflows faster to find and safer to use while preserving the advanced supervisory, genealogy, reporting, and admin capabilities the app now supports.

This plan assumes:

- the workflow analysis in `UX_ROLE_WORKFLOW_PLAN.md` is accepted
- the product will continue to support both main-app and standalone-app usage
- the first implementation step should prioritize information architecture, not deep workflow rewrites

## Core Principles

1. Do not remove working capability just to simplify navigation.
2. Change discoverability before changing business logic.
3. Separate daily workflows from specialist and admin workflows.
4. Keep standalone apps narrowly scoped to high-frequency operational work.
5. Treat journey/genealogy as a daily manager workflow.
6. Preserve route stability where possible during the first UX phases.

## Target Product Structure

### Main App

Should become the control plane for:

- extraction oversight
- downstream routing and management
- purchasing and inventory review
- alerts and issue management
- journey / genealogy visibility
- reporting
- admin / maintenance

### Standalone Extraction App

Should remain the primary execution surface for:

- lot scan / charge
- reactor board
- booth SOP workflow
- immediate post-extraction handoff capture

### Standalone Receiving App

Should remain the primary execution surface for:

- receiving queue
- receipt confirmation
- receipt correction while unlocked
- receiving photo capture

### Standalone Purchasing App

Should remain the primary execution surface for:

- buyer/mobile opportunity capture
- field-oriented purchase workflow

## Top-Level Navigation Target

The main app should move toward this top-level structure:

- `Purchasing`
- `Inventory`
- `Extraction`
- `Downstream`
- `Journey`
- `Alerts`
- `Settings` (Super Admin only)
- `More`

This does not require all underlying routes to change immediately.

Future optional enhancement: add `Settings -> Navigation` so Super Admins can configure sidebar group order. First implementation should use simple numeric order fields stored in `SystemSetting`, validate that required groups remain present, and fall back to the default order if the saved value is invalid.

## Phase 1 - Sidebar And Information Architecture Cleanup

### Goal

Reduce sidebar overload without changing workflow logic.

### Scope

- replace the current flat sidebar with grouped top-level navigation
- add a `More` bucket for low-frequency and specialist functions
- add a first-level `Journey` area
- promote `Settings` into its own Super Admin-only group with section links rather than burying it under `More`
- use the default group order `Purchasing`, `Inventory`, `Extraction`, `Downstream`, `Journey`, `Alerts`, `Settings`, `More`
- preserve existing route endpoints
- preserve existing page internals
- preserve permissions and capability gating

### Suggested Navigation Mapping

#### Extraction

- Dashboard extraction lens or landing
- Floor Ops
- Runs
- scan / charge entrypoints where appropriate

#### Downstream

- Downstream Queues
- destination queue pages:
  - GoldDrop
  - Liquid Loud
  - Terp Strip
  - HP Base Oil
  - Distillate

#### Purchasing

- Biomass Purchasing
- Purchases
- Biomass Pipeline
- Field approvals when applicable

#### Inventory

- Inventory
- lot utilities reachable from inventory context

#### Alerts

- supervisor alerts
- genealogy issue queue

#### Journey

- Genealogy Report
- Material Journey Viewer
- purchase / lot / run journey entrypoints

#### More

- Departments
- Suppliers
- Strains
- Costs
- Photo Library
- Import
- Slack imports
- Cross-Site Ops
- Settings

### Out of Scope

- workflow rewrites
- route removals
- page redesigns
- standalone-app scope changes

### Deliverables

- updated sidebar template and supporting nav partials/helpers
- active-state behavior for grouped nav
- role-aware visibility for items that remain gated

### Verification

- all current pages remain reachable
- no role loses existing access unexpectedly
- the sidebar is visibly shorter and clearer
- active/high-frequency workflows are first-level

## Phase 2 - Role-Based Landing And Navigation Defaults

### Goal

Make the product feel tailored without introducing hard silos.

### Scope

- set landing defaults by role group
- highlight the most common workflow cluster first
- preserve cross-role reach to permitted surfaces

### Proposed Landing Defaults

- extractors / floor operators -> `Extraction`
- downstream supervisors -> `Downstream`
- buyers / intake -> `Purchasing`
- managers / analysts -> dashboard or `Journey`
- admins -> dashboard or `More`

### Secondary Navigation Behavior

- remember the last active top-level area per session
- retain contextual back-links:
  - `Back to Floor Ops`
  - `Back to Downstream Queues`
  - future `Back to Journey`

### Out of Scope

- permission model rewrite
- removal of existing routes

### Deliverables

- landing-selection logic
- top-level section memory
- improved contextual return links

### Verification

- users land in the section most relevant to their role
- session memory reduces navigation repetition
- back-navigation remains intact

## Phase 3 - Main-App Workflow Rationalization

### Goal

Reduce overlap and ambiguity between similar surfaces.

### Focus Areas

#### Extraction vs Runs

Decide and enforce:

- `Floor Ops` = operational execution / reactor state / quick actions
- `Runs` = administrative detail / broader record management

This distinction should be visible in copy, buttons, and navigation.

#### Downstream Overview vs Destination Pages

Clarify:

- `Downstream Queues` = overview and triage
- destination queue pages = focused work surface

#### Alerts vs Journey

Clarify:

- `Alerts` = action queue
- `Journey` = visibility / tracing / investigation

These should complement each other instead of duplicating the same concept.

### Deliverables

- copy cleanup
- button-label cleanup
- route entrypoint cleanup
- reduced duplicate navigation options

### Verification

- users can tell which page is for overview vs execution vs investigation
- fewer duplicate “ways in” to the same task

## Phase 4 - Standalone App Scope Tightening

### Goal

Use standalone apps as true focused tools, not mini-main-apps.

### Standalone Extraction

Keep:

- charge flow
- reactor board
- booth SOP execution
- immediate post-extraction handoff

Avoid adding:

- genealogy
- full reporting
- admin configuration

### Standalone Receiving

Keep:

- receiving queue
- receipt confirmation / correction
- receiving evidence

Avoid adding:

- heavy purchase review
- supplier administration

### Standalone Purchasing

Keep:

- buyer opportunity creation
- mobile purchase workflow

Avoid adding:

- broad reporting
- master-data maintenance

### Deliverables

- clearer app-purpose copy
- clearer handoff buttons:
  - `Open in Main App`
  - `Open Queue`
  - `Open Purchase Review`
- removal of ambiguous or duplicative entrypoints where needed

### Verification

- each standalone app has a crisp job-to-be-done
- users do not expect the standalone apps to behave like the full main app

## Phase 5 - Journey And Financial Visibility Consolidation

### Goal

Build the manager-facing operating and commercial layer on top of lineage.

### Why This Matters

Journey is not just audit.

It should support:

- daily material-location and status visibility
- cost-to-produce understanding
- revenue projection from material already in process
- value and margin analysis by source, pathway, and destination

### Scope

- make `Journey` a stronger top-level manager area
- consolidate genealogy report, viewer, and issue queue access
- plan the next reporting layer for:
  - cost-to-produce by output type
  - realized value by pathway
  - expected revenue by week / month / quarter
  - loss / rework / low-margin hotspots

### Deliverables

- stronger journey landing structure
- clearer links between lineage and financial reporting
- documented next-phase reporting requirements

### Verification

- managers can answer:
  - where is this material
  - where has it been
  - what did it become
  - what did it cost to produce
  - what revenue is likely still to come from current in-process material

## Recommended Sprint Sequence

### Sprint 1

- implement Phase 1 only
- sidebar / nav cleanup
- no deep workflow rewrites

### Sprint 2

- implement Phase 2
- role-based landing defaults
- contextual navigation improvements

### Sprint 3

- implement extraction / downstream / alerts / journey distinctions from Phase 3

### Sprint 4

- implement standalone-app scope tightening from Phase 4

### Sprint 5

- implement or spec the financial/journey consolidation from Phase 5

## Risk Controls

### Risk 1 - Users Lose Access

Mitigation:

- do not remove routes in early phases
- move items before removing any shortcuts
- keep `More` as a safe fallback

### Risk 2 - Navigation Cleanup Breaks Muscle Memory

Mitigation:

- use transitional labels
- keep section links predictable
- preserve contextual back buttons

### Risk 3 - Over-correcting Into Role Silos

Mitigation:

- role-based landing, not hard role-locking
- preserve permitted access across sections

### Risk 4 - Mixing UX Cleanup With Workflow Rewrites

Mitigation:

- keep Phase 1 mostly structural
- defer workflow logic changes to later phases

## Success Criteria

The implementation is successful when:

- the left sidebar is materially shorter and easier to scan
- daily users can find their primary workflow immediately
- managers can reach journey tools as a first-class area
- specialist/admin functions stop crowding the top-level UX
- standalone apps feel more focused, not more general
- future cost and revenue reporting has a clear home in the product structure

## Immediate Next Coding Sprint Recommendation

Implement Phase 1:

- grouped top-level navigation
- `Journey` as first-level
- `More` bucket
- keep routes and page internals stable

That is the highest-value UX improvement with the lowest operational risk.
