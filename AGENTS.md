# UpBain Research Platform v2

Telegram **userbot + web dashboard**. Everything is operated from the browser —
there is **no `.env`**. All settings (api_id, api_hash, Telegram login session,
notify bot token, web password) are entered in the web UI and persisted to
`data/auto_config.json` (git-ignored).

See `PROJECT_PROMPT (3).txt` for the original phased roadmap. The full platform
(Phases 0→5) is implemented: userbot+web, SQLite, archive/days, multi-bot
delivery, membership, VIP/Stars, giftcode, ads, share, backup, rollup.

## Layout
- `run.py` — entry point (starts the FastAPI web app via uvicorn).
- `web/server.py` — all FastAPI routes (auth, config, Telegram login, userbot,
  platform settings, archive, bots, users, VIP, gift, ads, share, backup, rollup, SSE).
- `web/security.py` — web-session password auth (salted hash + signed cookie).
- `web/templates/`, `web/static/` — sidebar dashboard UI (one section per feature).
- `core/config_store.py` — `data/auto_config.json` load/save + secret masking + platform config.
- `core/userbot.py` — Pyrogram userbot manager + web-driven login flow.
- `core/logbus.py` — in-memory log bus streamed to the browser via SSE.
- `research_platform/` — platform package (named `research_platform`, **never**
  `platform/`, which would shadow the stdlib and crash Pyrogram on Windows):
  - `db.py` SQLite (bots/days/day_items/users/deliveries/vip/gift/ads/share) at `data/platform.db`.
  - `dates.py` VN date labels (DD-MM-YYYY, Asia/Ho_Chi_Minh).
  - `archive_index.py` `after_auto_forward` hook + manual ingest.
  - `bot_manager.py` / `bot_delivery.py` / `bot_handlers.py` aiogram delivery bots (max 10).
  - `membership.py` force-join gate (TTL cache, fail-open).
  - `backup.py` ZIP (platform.db + masked config + archive_index.json), rotate.
  - `rollup.py` 30-day catalog; `run_queue.py` sequential multi-bot broadcast.

## Run / build / lint
- Run (dev): `python run.py` → http://127.0.0.1:8080 (override with `HOST`/`PORT`;
  set `RELOAD=1` for autoreload). Uses the venv at `.venv`.
- There is no separate build step (server-rendered templates + static JS).
- No test suite or linter is configured yet in this phase.

## Cursor Cloud specific instructions
- Telegram MTProto library is **pyrofork** (imports as `pyrogram`) plus `tgcrypto`;
  the delivery bots use **aiogram**. `tgcrypto` is a C extension and needs Python
  dev headers (`python3.12-dev`) to build the wheel; the headers are a system
  dependency, not in the update script. Note `aiogram` pins `pydantic<2.10`, which
  is why pydantic resolves to 2.9.x — that is expected and works with FastAPI here.
- DB is plain SQLite at `data/platform.db` (WAL mode), created automatically on
  startup via `db.init_db()`. The whole `data/` dir is git-ignored.
- The platform has 3 ON/OFF layers in the Platform tab (publish_channels /
  archive_index / bot_delivery) gated by a master `enabled`. With real Telegram
  the userbot `after_auto_forward` hook writes day_items; for local testing the
  Archive tab "Ingest" button (and Userbot tab "mô phỏng auto-forward") exercise
  the same indexing path without Telegram.
- Running delivery bots and broadcasting need **real bot tokens** (Bots tab) and
  the bot must be a member of the source chat; without tokens the bot stays
  `stopped`. All non-Telegram management (days, VIP, gift, ads, share, backup,
  rollup) is fully testable in the browser with no credentials.
- A background **scheduler** (`research_platform/scheduler.py`) starts with the
  app and ticks every 30s; it runs auto-forward rounds (when `schedule_enabled` +
  `enabled`) and periodic backups. The forward pipeline (`Lịch & Topic` tab →
  topic_map + publish_channel, or `/runtopic` via "Chạy 1 lượt ngay") needs the
  userbot ONLINE; it copies the latest N source messages to `publish_channel`
  then indexes them. Telegram-dependent actions (run forward, notify, rollup post,
  backup→Telegram, Stars payment) all **fail gracefully** with a clear message
  when creds/targets are not configured, so the dashboard stays usable.
- Telegram login is **fully web-driven** (no terminal prompt): phone → code →
  optional 2FA password, handled by `core/userbot.py`. A successful login exports
  a Pyrogram **session string** saved to `auto_config.json`; the userbot can then
  be (re)started with the START button without logging in again.
- Completing a **real** Telegram login here requires the operator's own
  `api_id`/`api_hash` (from my.telegram.org) **and** the phone that receives the
  code — these cannot be supplied by the agent. Without real credentials,
  `send_code` correctly reaches Telegram and returns `API_ID_INVALID`, which still
  proves the flow is wired. To test the live path, enter real credentials in the
  Telegram tab via the Desktop pane and complete the code/2FA prompt.
- First web visit is a one-time **setup**: the first password you submit on
  `/login` becomes the dashboard password (stored hashed in `auto_config.json`).
  To force the first-run setup screen again, delete `data/auto_config.json`.
- Server binds `127.0.0.1` by default; use `HOST=0.0.0.0` when you need to reach it
  from outside the VM (e.g. the Desktop browser).
