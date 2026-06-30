# UpBain Research Platform v2

Telegram **userbot + web dashboard**. Everything is operated from the browser —
there is **no `.env`**. All settings (api_id, api_hash, Telegram login session,
notify bot token, web password) are entered in the web UI and persisted to
`data/auto_config.json` (git-ignored).

Current state: **Phase 0 — MÓNG (Foundation)**. See `PROJECT_PROMPT (3).txt` for
the full phased roadmap. Do **one phase at a time** and do not jump phases.

## Layout
- `run.py` — entry point (starts the FastAPI web app via uvicorn).
- `web/server.py` — FastAPI routes (auth, config, Telegram login, userbot ctrl, SSE logs).
- `web/security.py` — web-session password auth (salted hash + signed cookie).
- `web/templates/`, `web/static/` — dashboard UI (login + tabs + live log view).
- `core/config_store.py` — `data/auto_config.json` load/save + secret masking.
- `core/userbot.py` — Pyrogram userbot manager + web-driven login flow.
- `core/logbus.py` — in-memory log bus streamed to the browser via SSE.
- `research_platform/` — stub package for later phases (named `research_platform`,
  **never** `platform/`, which would shadow the stdlib and crash Pyrogram on Windows).

## Run / build / lint
- Run (dev): `python run.py` → http://127.0.0.1:8080 (override with `HOST`/`PORT`;
  set `RELOAD=1` for autoreload). Uses the venv at `.venv`.
- There is no separate build step (server-rendered templates + static JS).
- No test suite or linter is configured yet in this phase.

## Cursor Cloud specific instructions
- Telegram MTProto library is **pyrofork** (imports as `pyrogram`) plus `tgcrypto`.
  `tgcrypto` is a C extension and needs Python dev headers (`python3.12-dev`) to
  build the wheel; the headers are a system dependency, not in the update script.
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
