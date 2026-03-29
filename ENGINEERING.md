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

- **Save hints:** `POST /settings` with `form_type=slack_sync_channels`, fields `sync_ch_0` … `sync_ch_5`. Hint change clears `resolved_channel_id` and `last_watermark_ts` for that row.
- **Run sync:** `POST /settings/slack_sync_channel` with `sync_days` (1–365). Resolves each non-empty hint via `conversations.list` (or passes through channel IDs), then pages `conversations.history` with helper `_slack_ingest_channel_history`.
- **Review:** `GET /settings/slack-imports`.

### Sync semantics

- **No watermark:** `oldest = now - sync_days * 86400` (rolling window).
- **With watermark:** `oldest = last_watermark_ts`; after a successful page loop, watermark updates to the **maximum** `ts` observed in that run (or `time.time()` as a string when the channel had no qualifying messages and had no prior cursor).
- Audit log action `slack_channel_sync` uses entity id `multi` and JSON details summarizing per-channel counts and errors.

### Related code (indicative)

- `app.py`: `SLACK_SYNC_CHANNEL_SLOTS`, `_ensure_slack_sync_configs`, `_slack_ingest_channel_history`, `settings_slack_sync_channel`, settings handler `slack_sync_channels`.
- `models.py`: `SlackChannelSyncConfig`, `SlackIngestedMessage`.
- `templates/settings.html`: Slack card (sync channel form), Maintenance (sync button).

### Gunicorn / multi-worker startup

`init_db()` runs at import time (see bottom of `app.py`). With multiple sync workers, `db.create_all()` can race and one worker may see “table already exists” / duplicate relation. `init_db()` ignores those specific errors and continues; you can also set **`--preload`** on Gunicorn so the app loads once before workers fork (see `golddrop.service` `ExecStart`).
