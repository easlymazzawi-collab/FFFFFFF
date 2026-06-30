#!/usr/bin/env python3
"""Entry point for UpBain Research Platform v2 — Phase 0.

Starts the FastAPI web dashboard. All configuration (api_id, api_hash, Telegram
login, bot token) is done from the browser — there is no ``.env``.

Usage:
    python run.py            # serve on http://127.0.0.1:8080
    HOST=0.0.0.0 PORT=9000 python run.py
"""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    reload = os.environ.get("RELOAD", "0") == "1"
    print(f"UpBain Research Platform v2 (Phase 0) -> http://{host}:{port}")
    uvicorn.run("web.server:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
