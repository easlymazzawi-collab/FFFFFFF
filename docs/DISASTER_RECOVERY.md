# Disaster Recovery — UpBain Research Platform v2

All durable state lives in `data/` (git-ignored): `auto_config.json` (config +
Telegram session), `platform.db` (SQLite), `backups/*.zip`.

## What a backup contains
Each ZIP (`data/backups/backup-*.zip`, created from the **Backup** tab or the
scheduler) holds:
- `platform.db` — consistent SQLite snapshot (via the SQLite backup API)
- `auto_config.masked.json` — config with secrets masked (NOT a credential file)
- `archive_index.json` — full days + items index

> Backups intentionally contain **no raw media and no plaintext secrets** (spec
> A2). They restore the *index/metadata*, not the Telegram messages themselves.

## Scenario: bot/userbot process died
1. Restart the app: `python run.py` (the userbot session in `auto_config.json`
   persists, so the userbot comes back with **START**; bots restart from the
   **Bots** tab).
2. Delivery resumes automatically — progress is stored per user/day in
   `user_deliveries.last_seq_sent`, so `/today` continues from where it stopped.

## Scenario: restore from a backup ZIP
1. Stop the app.
2. Unzip and put `platform.db` back at `data/platform.db`.
3. Keep your existing `data/auto_config.json` (it holds the live session +
   secrets; the masked copy in the ZIP is only for reference).
4. Start the app; verify the **Kho lưu trữ** and **Users** tabs show the data.

## Scenario: lost the whole VM / fresh machine
1. `pip install -r requirements.txt`.
2. Restore `data/platform.db` from the latest ZIP.
3. Re-enter `api_id`/`api_hash` and re-login Telegram in the web UI (the session
   string cannot be recovered from a masked backup — this is by design).
4. Re-enter bot tokens in the **Bots** tab.

## Rotation
The app keeps the last 10 ZIPs locally and (if `backup_channel` + notify bot are
set) uploads each scheduled backup to Telegram for off-box retention.
