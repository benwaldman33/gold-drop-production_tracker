# Gold Drop — Engineering notes

Developer-facing implementation details. Product behavior belongs in `PRD.md`; operator steps in `USER_MANUAL.md`.

## PRD implementation notes — departments, approvals, aging

Product requirements live in **`PRD.md`** under **Operational departments & shared data model**, **Users & Permissions** (capabilities), **Potential pipeline records — Old Lots and soft deletion**. This section is the **engineering appendix** for that initiative.

### Capabilities vs composite roles

- **Today (`models.py`):** `User.role` is `super_admin` | `user` | `viewer`; **`is_slack_importer`** exists for Slack apply flows; **`is_purchase_approver`** backs pipeline commitment authorization.
- **`User.can_approve_purchase` (property):** `True` if `super_admin` **or** `is_purchase_approver`. Settings: per-user toggle **Approve $** / create-user checkbox; **`user_purchase_approver`** audit action.
- **Guards:** `_save_biomass` requires `can_approve_purchase` to move a biomass row **to or from** `committed` / `delivered` (first transition stamps **`purchase_approved_at`** / **`purchase_approved_by_user_id`**; audit **`purchase_approval`**).

### Purchase approval → commitment

- **Biomass pipeline:** approval is the transition into **`committed` / `delivered`**, which creates/updates the linked **`Purchase`** as before. **`purchase_approval`** audit rows supplement biomass/purchase audit logs.
- **Dashboard — buyer weekly snapshot:** **`weekly_dollar_budget`** (`SystemSetting`); **commitments** = linked purchases for biomass in `committed`/`delivered` whose approval (`purchase_approved_at`) or legacy **`committed_on`** falls in the current ISO week; **purchases** = all non-deleted purchases with **`purchase_date`** in that week. Dollar amount uses **`total_cost`** or **weight × $/lb** via **`_purchase_obligation_dollars`**.

### Potential-lot aging job

- **Settings keys:** `potential_lot_days_to_old` (**N₁**, default 10), `potential_lot_days_to_soft_delete` (**N₂**, default 30). Saved under **Operational Parameters**; if **`N₂` < `N₁`**, **`N₂`** is raised to **`N₁`** with an info flash.
- **Clock:** **`created_at`** only (see PRD). Applies only to **declared** / **testing** rows (not committed/delivered/cancelled).
- **Execution:** **`_apply_biomass_potential_soft_delete()`** runs at the start of **`GET /biomass`** (idempotent; sets **`BiomassAvailability.deleted_at`** when age ≥ **N₂**). Safe to call frequently.
- **List buckets (`_biomass_bucket_filter`):** **Current** (default) — non-deleted; potential rows only if **`created_at` > now − N₁**; committed+ stages ignore age. **Old Lots** — potential rows with N₁ ≤ age < N₂. **All** — all non-deleted (no age filter). **Archived** — **`deleted_at` not null** (Super Admin only). **`BiomassAvailability.deleted_at`** column; **restore** via **`POST /biomass/<id>/restore`** (Super Admin). Edits blocked until restored.

### Department UIs

- **Routes:** `GET /dept/` (`dept_index`) lists all department tiles; `GET /dept/<slug>` (`dept_view`) shows intro, **Quick links** (existing `url_for` targets + optional `#anchor`), and **`_department_stat_sections(slug)`** rollups (same DB as core screens).
- **Slugs:** `finance`, `biomass-purchasing`, `biomass-intake`, `biomass-extraction`, `thca-processing`, `hte-processing`, `liquid-diamonds`, `terpenes-distillation`, `testing`, `bulk-sales` — see `DEPARTMENT_PAGES` in `app.py`.
- **Quick links with query args:** e.g. `url_kwargs={"hte_stage": "awaiting_lab"}` → `GET /runs?hte_stage=awaiting_lab` (Flask `url_for` passes unknown keys as query parameters).
- **Testing / Terpenes rollups:** `_department_stat_sections("testing")` counts **Run** rows with `dry_hte_g > 0` by `hte_pipeline_stage` (plus supplier **`LabTest`** totals). `_department_stat_sections("terpenes-distillation")` reports strip-queue count, stripped count, and last-30-day sums of `hte_terpenes_recovered_g` / `hte_distillate_retail_g` on runs in stage **`terp_stripped`**.
- **Weekly finance snapshot:** `_weekly_finance_snapshot()` shared with Dashboard buyer budget card.
- **Data access:** reuse existing queries and models; no duplicate business rules.

### HTE post-extraction pipeline (runs)

Product behavior is summarized in **`PRD.md`** (Runs entity + material flow) and **`USER_MANUAL.md`** (operator steps).

- **Model (`models.py` — `Run`):**
  - `hte_pipeline_stage` — `NULL` / empty = not set; otherwise one of **`awaiting_lab`**, **`lab_clean`**, **`lab_dirty_queued_strip`**, **`terp_stripped`** (see `HTE_PIPELINE_ALLOWED` / `_hte_pipeline_options()` in `app.py`).
  - `hte_lab_result_paths_json` — JSON array of relative static paths (e.g. `uploads/labs/...`) for COA/lab PDFs or images.
  - `hte_terpenes_recovered_g`, `hte_distillate_retail_g` — floats; used when material is stripped and accounted.

- **Persistence:**
  - **SQLite:** `_ensure_sqlite_schema()` adds the four columns to **`runs`** if missing.
  - **PostgreSQL:** `_ensure_postgres_run_hte_columns()` runs from **`init_db()`** and issues `ALTER TABLE runs ADD COLUMN IF NOT EXISTS ...` (because `db.create_all()` does not migrate existing tables).

- **Write path:** `_save_run()` — after `flush()` so `run.id` exists, merges removals (`remove_hte_lab_paths[]`), appends **`_save_lab_files(..., prefix="hte-run-<id>")`**, stores JSON; parses optional terp/distillate floats from the form.

- **Read paths:** `runs_list` — optional **`hte_stage`** query filter; template gets `hte_label_map` / `hte_pipeline_options`. **`export_csv`** entity **`runs`** — extra CSV columns and the same filter when `hte_stage` is present.

### Slack remains authoritative for floor capture

- Ingestion/linking behavior continues to follow **Integrations — Slack** in `PRD.md` and the **Slack channel history sync** section below. Department pages should not assume web forms replace Slack until product changes **Operational input authority** in the PRD.

## Slack channel history sync

### Data model

- **`SlackChannelSyncConfig`** (`slack_channel_sync_configs`): fixed slots `slot_index` 0–5, `channel_hint`, optional `resolved_channel_id`, optional `last_watermark_ts` (string Slack message `ts`, used as `conversations.history` `oldest` on incremental runs).
- **`SlackIngestedMessage`** (`slack_ingested_messages`): one row per ingested message; **unique** on `(channel_id, message_ts)` for deduplication.

SQLite adds the sync config table in `_ensure_sqlite_schema()`; other engines rely on `db.create_all()` plus any existing migration posture.

### Bootstrap

- `_ensure_slack_sync_configs()` ensures six rows exist. If the table was empty, **slot 0**’s `channel_hint` is copied from `SystemSetting` `slack_default_channel`.

### HTTP / UI

- **Save Slack + sync hints:** `POST /settings` with `form_type=slack`, including system settings fields and `sync_ch_0` … `sync_ch_5`. Hint change clears `resolved_channel_id` and `last_watermark_ts` for that row.
- **Run sync:** `POST /settings/slack_sync_channel` with `sync_days` (1–365). Resolves each non-empty hint via `conversations.list` (or passes through channel IDs), then pages `conversations.history` with helper `_slack_ingest_channel_history`.
- **Imports / triage / apply:** `GET /settings/slack-imports` — filtered list (date range, channels, promotion, coverage). `GET /settings/slack-imports/<msg_id>/preview` — Run preview. `GET /settings/slack-imports/<msg_id>/apply-run` — session prefill + redirect to `run_new`; optional `confirm=1` after duplicate interstitial. All three use **`slack_importer_required`** (`User.can_slack_import`: Super Admin or `is_slack_importer`).
- **User flag:** `POST /settings/users/<id>/toggle_slack_importer` (`@admin_required`), audit action `user_slack_importer`. Create-user form optional `new_slack_importer` (ignored for `super_admin` role).

### Sync semantics

- **No watermark:** `oldest = now - sync_days * 86400` (rolling window).
- **With watermark:** `oldest = last_watermark_ts`; after a successful page loop, watermark updates to the **maximum** `ts` observed in that run (or `time.time()` as a string when the channel had no qualifying messages and had no prior cursor).
- Audit log action `slack_channel_sync` uses entity id `multi` and JSON details summarizing per-channel counts and errors.

### Related code (indicative)

- `app.py`: `SLACK_SYNC_CHANNEL_SLOTS`, `_ensure_slack_sync_configs`, `_slack_ingest_channel_history`, `settings_slack_sync_channel`, settings `form_type=slack` handler (includes sync channel rows).
- `models.py`: `SlackChannelSyncConfig`, `SlackIngestedMessage`.
- `templates/settings.html`: Slack card (sync channel form), Maintenance (sync button).

### Slack apply / Run backlink (Phase 2)

- **Models (`models.py`):** `User.is_slack_importer`; `User.can_slack_import` property. `Run.slack_channel_id`, `Run.slack_message_ts`, `Run.slack_import_applied_at` (set on **new** run save when form includes Slack hidden fields).
- **SQLite:** `_ensure_sqlite_schema()` adds the new columns on existing DBs. **PostgreSQL / other:** ensure equivalent DDL via your migration process (`ALTER TABLE users …`, `ALTER TABLE runs …`).
- **Session prefill:** `SLACK_RUN_PREFILL_SESSION_KEY`; `_slack_run_prefill_put`, `_slack_filled_json_safe`, `_hydrate_run_from_slack_prefill` (ephemeral `Run` for template). Cleared after successful Slack-linked save.
- **Guards:** `slack_importer_required`; `run_new` is `@login_required` with branch logic: GET allows `can_slack_import` + session prefill without `can_edit`; POST and normal new-run GET still require `can_edit` except prefill viewer path.
- **Duplicate policy:** `_first_run_for_slack_message` before `db.session.add(run)`; interstitial template `slack_import_apply_confirm.html`. Hidden field `slack_apply_allow_duplicate`. Confirm path logs `slack_duplicate_apply_confirm` on `slack_ingested_message`.
- **Triage helpers:** `_slack_linked_run_ids_index`, `_slack_coverage_label(preview)` (full / partial / none aligned with PRD heuristic).
- **Audit:** Run `create` with JSON `details` when saved from Slack (`slack_import`, ids, `duplicate_apply`, `prefill_keys`).
- **Templates:** `slack_imports.html`, `slack_import_preview.html`, `slack_import_apply_confirm.html`, `run_form.html` (hidden Slack fields + `can_save_run`). `base.html` sidebar link when `current_user.can_slack_import`.

### Slack → field mappings (Phase 1)

- **Storage:** `SystemSetting` key `slack_run_field_mappings`, JSON `{"rules": [ ... ]}`. Seeded in `init_db()` when missing.
- **Rule shape:** `source_key`, `target_field`, `message_kinds`, `transform`; optional **`destination`** (`run` default). Allowed destinations: `run`, `biomass`, `purchase`, `inventory`, `photo_library`, `supplier`, `strain`, `cost`. For `run`, `target_field` must be in `SLACK_MAPPING_ALLOWED_TARGET_FIELDS`; for others, a **snake_case** placeholder string (`SLACK_NON_RUN_TARGET_FIELD_RE`) until that module ships an allowlist.
- **Editor:** `GET/POST /settings/slack-run-mappings` — grid: destination, Slack source, target (Run = select; other = text), message-kind scope, transform + arg. Initial row count is `_slack_mapping_grid_row_count(rules)`; client script grows/shrinks trailing blank rows. Hints update live. POST scans `rule_destination_i`, `rule_target_select_i` / `rule_target_text_i`, etc. **Save mappings** / **Reset** / **Save JSON** as before.
- **Preview:** `GET /settings/slack-imports/<msg_id>/preview` — `_preview_slack_to_run_fields` applies only rules with `destination` **`run`** (or omitted); keys consumed by other destinations are still marked consumed for **unmapped** derivation. Preview is also used for **apply** prefill; persistence to `runs` happens only via the Run form save path.
- **Helpers:** `_apply_slack_mapping_transform`, `_validate_slack_run_field_rules`, `_load_slack_run_field_rules`, `_slack_non_run_mapping_rule_count`, `_preview_slack_to_run_fields` in `app.py`.

### Gunicorn / multi-worker startup

`init_db()` runs at import time (see bottom of `app.py`). With multiple sync workers, `db.create_all()` can race and one worker may see “table already exists” / duplicate relation. `init_db()` ignores those specific errors and continues; you can also set **`--preload`** on Gunicorn so the app loads once before workers fork (see `golddrop.service` `ExecStart`).
