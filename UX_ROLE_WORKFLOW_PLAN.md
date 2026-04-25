# UX Role And Workflow Plan

## Purpose

The product has outgrown a flat navigation model.

The main app currently exposes daily execution workflows, supervisor control surfaces, reporting, master data, imports, and admin tools as peers in the same sidebar. That made sense while the app was smaller. It is now creating decision noise and making the product harder to use.

This plan applies the Pareto principle:

- a small number of users will perform most of the actions
- a small number of workflows will account for most daily usage
- those workflows should be visually primary
- lower-frequency and specialist functions should move to second-level navigation or role-gated utility areas

The goal is not to remove capability. The goal is to make the most common work obvious and make advanced work available without competing for attention.

## Product Direction

The product should split into:

- a focused main app for supervisors, managers, and office users
- focused standalone apps for high-frequency operational work on tablet/phone
- second-level menus for occasional, analytical, and admin-only functions

The app should be organized by:

1. role
2. frequency of use
3. device context
4. workflow clarity

Not by:

- how many features exist
- how many routes exist
- which modules were built first

## Primary User Groups

### 1. Extractors / Floor Operators

Primary device:

- tablet
- shared floor workstation

Primary goals:

- scan a lot
- charge a lot
- open a run
- work the booth SOP
- complete the run

Primary product surfaces:

- standalone extraction app
- `Floor Ops`
- scan / charge flows

Secondary needs:

- quick lot lookup
- quick run open

Low-value for this role as top-level items:

- genealogy
- suppliers
- costs
- strains
- imports
- settings
- departments

### 2. Downstream Supervisors / Production Leads

Primary device:

- desktop
- tablet in production area

Primary goals:

- review completed runs
- route runs into downstream destinations
- work destination queues
- assign owners
- clear bottlenecks
- resolve exceptions

Primary product surfaces:

- `Downstream Queues`
- destination queue pages
- supervisor alerts
- run edit from queue context

Secondary needs:

- inventory lookup
- run details
- booth review

Low-value for this role as top-level items:

- suppliers
- strains
- costs
- import
- photo library

### 3. Buyers / Procurement / Intake

Primary device:

- desktop
- phone/tablet for field or mobile workflows

Primary goals:

- create or review purchase opportunities
- manage purchases
- approve or move batches through pipeline states
- receive material

Primary product surfaces:

- standalone purchasing app
- standalone receiving app
- `Biomass Purchasing`
- `Purchases`
- `Inventory`

Secondary needs:

- suppliers
- field approvals
- purchase journey

Low-value for this role as top-level items:

- genealogy
- downstream queues
- costs
- photo library
- import for runs

### 4. Managers / Analysts

Primary device:

- desktop

Primary goals:

- see operational status
- investigate issues
- review genealogy and audit trail
- understand yield / cost / exceptions

Primary product surfaces:

- dashboard
- supervisor alerts
- genealogy report
- material journey viewer
- issue queue
- downstream reporting

Secondary needs:

- run details
- purchase journey
- cross-site ops

Low-value for this role as top-level items:

- lot scan tools
- charge workflow
- floor execution controls

### 5. Admins / System Maintainers

Primary device:

- desktop

Primary goals:

- user management
- settings
- integrations
- imports
- maintenance
- master data cleanup

Primary product surfaces:

- settings
- imports
- slack imports
- suppliers
- strains
- costs

This is a real role, but it is not the dominant day-to-day usage model. Admin surfaces should not define the primary UX for everyone else.

## Workflow Frequency Classification

### Daily / High Frequency

- `Floor Ops`
- scan / charge lot
- standalone extraction run workflow
- `Downstream Queues`
- destination queue pages
- `Purchases`
- `Inventory`
- standalone receiving
- standalone purchasing
- supervisor alerts

### Weekly / Moderate Frequency

- `Biomass Purchasing`
- `Runs`
- genealogy report
- material journey viewer
- genealogy issue queue
- field approvals
- batch journeys

### Occasional / Specialist

- suppliers
- strains
- costs
- photo library
- import
- slack imports
- departments
- cross-site ops

### Admin / Rare

- settings
- internal API clients
- remote sites
- maintenance
- data migration or import tooling

## Keep In Main App Vs Standalone Apps

### Standalone Extraction App

Should own:

- lot scan / manual tracking entry
- charge creation
- reactor board
- open run
- booth SOP execution
- booth evidence capture
- immediate post-extraction handoff capture

Should keep a limited escape hatch:

- `Open in Main App`

Should not become:

- a general reporting surface
- a genealogy surface
- a purchasing surface
- a heavy admin surface

### Standalone Receiving App

Should own:

- receiving queue
- receipt confirmation
- receipt correction while unlocked
- receiving photos
- receiving location / floor-state capture

Should not require users to live in the main app for normal dock work.

### Standalone Purchasing App

Should own:

- buyer-facing opportunity capture
- mobile buyer workflow
- field-friendly purchase entry

Should not become:

- full supplier administration
- accounting/reporting
- heavy batch-history analysis

### Main App

Should own:

- supervisor workflows
- exception handling
- downstream routing and management
- office purchase review
- inventory overview
- genealogy investigation
- reporting
- admin and maintenance

## Proposed Information Architecture

### Top-Level Navigation

This should become the primary left-nav structure:

- `Extraction`
- `Downstream`
- `Purchasing`
- `Inventory`
- `Alerts`
- `More`

### What Each Top-Level Item Means

#### Extraction

Primary daily-use extraction surfaces:

- dashboard extraction summary or operator landing
- `Floor Ops`
- `Runs`
- quick links into scan / charge / reactor board

This is the extraction control area in the main app, while the standalone extraction app remains the primary execution surface on tablet.

#### Downstream

Primary daily-use post-extraction surfaces:

- `Downstream Queues`
- GoldDrop queue
- Liquid Loud queue
- Terp Strip queue
- HP Base Oil hold
- Distillate hold

This should likely become a section with an overview plus destination subpages.

#### Purchasing

Primary purchasing / intake surfaces:

- `Biomass Purchasing`
- `Purchases`
- `Biomass Pipeline`
- `Field approvals` when applicable

This becomes the office control plane that complements the standalone buying and receiving apps.

#### Inventory

Primary material lookup surfaces:

- `Inventory`
- lot edit / lot label / lot scan utilities

This should stay easy to access because it is cross-functional.

#### Alerts

Cross-cutting operational attention surface:

- supervisor alerts
- genealogy issue queue
- possibly later unresolved queue blocks / stale work

This should become a true operational inbox, not just a dashboard anchor.

#### More

Second-level / specialist functions:

- genealogy report
- material journey viewer
- departments
- suppliers
- strains
- costs
- photos
- imports
- slack imports
- cross-site ops
- settings

This is where most current sidebar crowding should go.

## Immediate Navigation Cleanup Recommendation

### Phase 1

Do not redesign every screen yet.

First:

- collapse current sidebar into fewer top-level buckets
- move rare/specialist items under `More`
- keep route structure mostly intact
- change discoverability before changing workflow internals

This is the highest-value, lowest-risk cleanup.

### Phase 2

Add role-based landing behavior:

- extractors land in `Extraction`
- downstream supervisors land in `Downstream`
- buyers land in `Purchasing`
- managers land in dashboard / alerts

This can be done without removing cross-role access.

### Phase 3

Rationalize overlapping surfaces:

- decide whether `Runs` is primarily admin/detail while `Floor Ops` is operational
- reduce duplicate paths to the same action
- make run access contextual rather than central for operators

### Phase 4

Refine second-level navigation and reporting clusters:

- `Genealogy`
- `Reports`
- `Admin`

That may ultimately replace the single `More` bucket once the first cleanup is stable.

## Specific UX Decisions Recommended

### Items That Should Stay First-Level

- extraction / floor operations
- downstream queues
- purchasing
- inventory
- alerts

### Items That Should Move Under `More`

- genealogy report
- departments
- suppliers
- strains
- costs
- photos
- imports
- slack imports
- cross-site ops
- settings

### Items That Should Be Contextual, Not Nav-Primary

- material journey viewer
- individual destination queue pages
- field approvals for users who do not use them
- purchase journey
- raw JSON and specialist detail routes

### Items That Should Be Hidden By Role

- settings for non-admins
- slack imports except importer/admin roles
- field approvals except buyer/approver roles
- cross-site ops unless enabled and relevant

## Workflow Ownership Summary

### Main App

Best for:

- supervisors
- managers
- office purchasing
- analysts
- admins

### Standalone Extraction

Best for:

- extractors
- assistant extractors

### Standalone Receiving

Best for:

- receiving staff
- dock users

### Standalone Purchasing

Best for:

- buyers
- field/mobile purchasing users

## First Implementation Sprint Recommendation

The first UX cleanup sprint should be:

1. replace the current flat sidebar with grouped top-level navigation
2. add `More`
3. move low-frequency items under `More`
4. keep routes unchanged
5. keep page content unchanged
6. avoid workflow rewrites in the same sprint

That gives a major usability win without mixing:

- information architecture work
- visual redesign
- workflow logic changes

## Second Implementation Sprint Recommendation

After navigation cleanup:

1. define role-based landing pages
2. simplify the extraction vs runs relationship
3. simplify the downstream supervisor flow
4. make alerts a clearer unified queue

## Third Implementation Sprint Recommendation

After the main app navigation is cleaned up:

1. tighten standalone app scopes
2. remove duplicated “general app” expectations from standalone surfaces
3. make main-app handoff links explicit:
   - `Open in Main App`
   - `Open Queue`
   - `Open Purchase Review`

## Success Criteria

This UX direction is successful when:

- operators can identify their primary action in one or two seconds
- supervisors do not need to scan a long sidebar to find queue work
- buyers and receivers can live mostly in their dedicated workflows
- managers can still reach reporting and genealogy without making those surfaces primary for everyone
- rare/admin tasks remain available but stop crowding the day-to-day product

## Recommended Next Build Sequence

1. implement sidebar / navigation cleanup
2. add role-based landing defaults
3. rationalize extraction execution vs run administration
4. rationalize downstream overview vs destination detail navigation
5. tighten standalone-app scope and handoff language
