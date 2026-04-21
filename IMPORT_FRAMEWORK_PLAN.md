# Gold Drop - Shared Import Framework Plan

This document outlines the proposed product and engineering plan for a shared, interactive import framework that can serve multiple entities instead of continuing to add one-off importers.

## Why This Work Is Needed

Current state:

- `Purchases` has a dedicated spreadsheet importer with a fixed header alias map and a fixed commit path.
- `Runs` has an older import path that follows a different interaction model.
- `Suppliers`, `Strains`, and `Inventory` do not yet have the same guided spreadsheet import experience.
- Slack field mappings technically support multiple destinations, but the current editor still feels engineering-oriented rather than operator-friendly.

This creates three problems:

1. inconsistent operator experience across modules
2. hard-coded field support per importer
3. repeated engineering effort every time a new import surface is added

The correct long-term move is to build one shared import engine with per-entity rules and a common UX.

## Product Goal

Create a reusable import workflow that makes spreadsheet import easy for operators while protecting system-managed fields and preserving traceability.

The shared workflow should feel like:

1. upload a file
2. detect columns
3. suggest mappings
4. let the user adjust mappings interactively
5. validate row-by-row
6. preview creates / updates
7. commit selected rows

This same interaction model should eventually work for:

- Purchases
- Suppliers
- Strains
- Inventory
- Runs

## Design Principles

### 1. One framework, many entity adapters

Do not build a separate custom importer for every module.

Instead, create:

- one shared import controller / UI flow
- one parser layer for spreadsheet files
- one per-entity adapter that defines:
  - allowed fields
  - required fields
  - validation rules
  - create vs update behavior
  - protected fields

### 2. Friendly field names, not internal column names

Operators should see labels like:

- `Supplier Name`
- `Purchase Date`
- `Total Fill Weight`

not:

- `supplier`
- `purchase_date`
- `total_fill_weight_lbs`

Internal field keys can still exist behind the scenes, but the UI should be business-readable.

### 3. Saved mapping profiles

Users should be able to save import profiles for recurring spreadsheets, for example:

- accounting export
- intake spreadsheet
- vendor-specific purchase sheet
- strain master list

Profiles should remember:

- source column -> target field mappings
- ignored columns
- default values
- create/update behavior where applicable

### 4. Strong protection around system-managed fields

Not every database field should be importable.

The framework should explicitly block or hide:

- audit stamps
- approval stamps
- generated tracking ids
- calculated fields that should derive from other inputs
- linkage fields that could corrupt traceability if imported loosely

## Shared UX Proposal

### Step 1. Upload

Common upload page for `.csv`, `.xlsx`, `.xlsm`.

Display:

- drag-and-drop zone
- browse button
- saved profile selector if one exists for that entity

### Step 2. Column detection

System reads headers and proposes mappings using:

- alias dictionaries
- prior saved profile
- optional fuzzy header matching

Display:

- each source column
- suggested target field
- confidence / rationale

### Step 3. Interactive mapping

For each source column, user can:

- accept suggested target
- choose a different target from a dropdown
- ignore the column
- set a default value for missing fields

Show:

- required target fields still missing
- columns that will be ignored
- columns mapped to protected fields should be blocked

### Step 4. Validation preview

Show row-level preview with:

- valid rows
- warnings
- hard errors
- whether row will create or update a record

Support:

- import all valid rows
- select individual rows
- export error report if needed

### Step 5. Commit

Commit should:

- write only selected valid rows
- report create/update counts
- report skipped/failed rows
- preserve audit trail

## Entity Strategy

### Purchases

Priority: high

Reason:

- already has spreadsheet import demand
- current importer is useful but hard-coded
- likely to benefit most from interactive mapping

Importable fields should include operator-meaningful purchase fields and lot seed fields, not every raw database column.

Examples:

- supplier
- purchase date
- delivery date
- batch id
- stated weight
- actual weight
- stated potency
- tested potency
- price per lb
- total cost
- harvest date
- storage note
- license info
- queue placement
- clean/dirty
- indoor/outdoor
- strain
- notes

Should remain protected:

- approval stamps
- audit stamps
- generated tracking fields
- derived lifecycle state that should be system-controlled

### Suppliers

Priority: high

Reason:

- simpler model
- good candidate to validate the shared framework
- lower traceability risk than runs/inventory

Potential import fields:

- supplier name
- legal name
- city
- county
- state
- contact info
- notes
- active/inactive

### Strains

Priority: high

Reason:

- simple import surface
- often managed from external spreadsheets
- low risk relative to inventory and runs

Potential import fields:

- strain name
- canonical label
- supplier association where relevant
- notes / metadata

### Inventory

Priority: medium

Reason:

- operationally important but riskier
- direct inventory import can break traceability if not tightly constrained

Recommendation:

- do not start with a fully free-form inventory importer
- begin with a controlled inventory adjustment import or lot-state update import
- require stricter validation and explicit preview of weight/state impact

### Runs

Priority: medium to low for the first framework wave

Reason:

- most complex
- traceability-sensitive
- linked to lots, allocations, outputs, and analytics

Recommendation:

- eventually migrate the older run import to the shared framework
- do this only after the framework is proven on Purchases / Suppliers / Strains

## Slack Mapping UI Improvement Plan

This is related work, but should be treated as a separate UI redesign inside the same broader data-mapping family.

Current problem:

- the Slack mapping screen exposes raw parsed keys and internal-style target fields
- non-Run destinations still use free-text snake_case labels

Recommended redesign:

1. keep the underlying rule model
2. replace the editor UI with a friendlier mapping assistant
3. use business-readable labels and descriptions
4. group targets by destination and section
5. replace free-text target field labels with dropdowns per destination
6. show live examples or preview snippets for each mapping rule

This can share concepts with the import framework:

- friendly labels
- mapping suggestions
- saved profiles / templates
- preview-first workflow

## Suggested Build Order

### Phase 1. Framework foundation

Build:

- shared spreadsheet upload / parse service
- shared mapping model
- shared validation/preview screen
- per-entity adapter interface

Do not migrate everything at once.

### Phase 2. Migrate Purchases

Replace the current purchase importer with the shared framework.

Goals:

- preserve current alias coverage
- add interactive mapping
- make additional purchase fields importable without code changes for every new column

### Phase 3. Add Suppliers and Strains

Use these as simpler follow-on entities.

Goals:

- prove the framework is reusable
- establish create/update semantics
- validate saved profiles

### Phase 4. Slack mapping UI redesign

Apply the same design discipline to the Slack field-mapping surface:

- friendly labels
- better target pickers
- stronger preview

### Phase 5. Inventory and Runs

Only after the framework is stable:

- add constrained inventory import
- migrate run import to the same interaction model

## Engineering Structure Proposal

Potential module split:

- `services/import_framework.py`
  - file parse orchestration
  - profile loading
  - generic mapping workflow helpers

- `services/import_profiles.py`
  - saved mapping profiles

- `services/import_entities/`
  - `purchases.py`
  - `suppliers.py`
  - `strains.py`
  - `inventory.py`
  - `runs.py`

- `gold_drop/import_module.py`
  - shared routes / controller

- templates:
  - shared upload page
  - shared column-mapping page
  - shared preview/commit page

This keeps entity-specific logic out of the generic UI layer.

## Open Decisions

These need product decisions before implementation:

1. Which entities are create-only vs create-or-update?
2. How should updates match existing records?
   - exact name
   - canonical key
   - batch id
   - user-chosen key field
3. Should profiles be global, per user, or both?
4. How much fuzzy matching is acceptable before confirmation is required?
5. Which importable fields should be locked behind Super Admin only?

## Definition Of Done

This initiative is successful when:

- import UX is consistent across supported entities
- operators can map columns interactively instead of relying on hard-coded headers
- supported fields can grow without rewriting a whole importer each time
- protected fields remain protected
- traceability-sensitive entities still validate aggressively
- Slack mappings become more readable and intuitive as part of the same general data-mapping cleanup
