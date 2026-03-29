# Gold Drop — Engineering notes

Developer-facing implementation details. Product behavior belongs in `PRD.md`; operator steps in `USER_MANUAL.md`.

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
- **Review:** `GET /settings/slack-imports`.

### Sync semantics

- **No watermark:** `oldest = now - sync_days * 86400` (rolling window).
- **With watermark:** `oldest = last_watermark_ts`; after a successful page loop, watermark updates to the **maximum** `ts` observed in that run (or `time.time()` as a string when the channel had no qualifying messages and had no prior cursor).
- Audit log action `slack_channel_sync` uses entity id `multi` and JSON details summarizing per-channel counts and errors.

### Related code (indicative)

- `app.py`: `SLACK_SYNC_CHANNEL_SLOTS`, `_ensure_slack_sync_configs`, `_slack_ingest_channel_history`, `settings_slack_sync_channel`, settings `form_type=slack` handler (includes sync channel rows).
- `models.py`: `SlackChannelSyncConfig`, `SlackIngestedMessage`.
- `templates/settings.html`: Slack card (sync channel form), Maintenance (sync button).

### Slack → field mappings (Phase 1)

- **Storage:** `SystemSetting` key `slack_run_field_mappings`, JSON `{"rules": [ ... ]}`. Seeded in `init_db()` when missing.
- **Rule shape:** `source_key`, `target_field`, `message_kinds`, `transform`; optional **`destination`** (`run` default). Allowed destinations: `run`, `biomass`, `purchase`, `inventory`, `photo_library`, `supplier`, `strain`, `cost`. For `run`, `target_field` must be in `SLACK_MAPPING_ALLOWED_TARGET_FIELDS`; for others, a **snake_case** placeholder string (`SLACK_NON_RUN_TARGET_FIELD_RE`) until that module ships an allowlist.
- **Editor:** `GET/POST /settings/slack-run-mappings` — grid: destination, Slack source, target (Run = select; other = text), message-kind scope, transform + arg. Initial row count is `_slack_mapping_grid_row_count(rules)`; client script grows/shrinks trailing blank rows. Hints update live. POST scans `rule_destination_i`, `rule_target_select_i` / `rule_target_text_i`, etc. **Save mappings** / **Reset** / **Save JSON** as before.
- **Preview:** `GET /settings/slack-imports/<msg_id>/preview` — `_preview_slack_to_run_fields` applies only rules with `destination` **`run`** (or omitted); keys consumed by other destinations are still marked consumed for **unmapped** derivation. **No writes** to `runs`.
- **Helpers:** `_apply_slack_mapping_transform`, `_validate_slack_run_field_rules`, `_load_slack_run_field_rules`, `_slack_non_run_mapping_rule_count`, `_preview_slack_to_run_fields` in `app.py`.

### Gunicorn / multi-worker startup

`init_db()` runs at import time (see bottom of `app.py`). With multiple sync workers, `db.create_all()` can race and one worker may see “table already exists” / duplicate relation. `init_db()` ignores those specific errors and continues; you can also set **`--preload`** on Gunicorn so the app loads once before workers fork (see `golddrop.service` `ExecStart`).
