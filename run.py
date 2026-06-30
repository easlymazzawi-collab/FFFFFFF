#!/usr/bin/env python3
"""Entry point for UpBain Research Platform v2 — Phase 0.

Starts the FastAPI web dashboard. All configuration (api_id, api_hash, Telegram
login, bot token) is done from the browser — there is no ``.env``.

Usage:
    python run.py            # serve on http://127.0.0.1:8080
    HOST=0.0.0.0 PORT=9000 python run.py
"""

from __future__ import annotations

import importlib
import os
import sys

import uvicorn


def _bootstrap_stdlib_platform() -> None:
    """Windows/Pyrogram guard: if a local ``platform`` package shadows the stdlib
    ``platform`` module, force-load the real stdlib one. We deliberately named our
    package ``research_platform`` to avoid this, but this keeps things safe if a
    ``platform/`` folder ever appears on sys.path.
    """
    try:
        mod = importlib.import_module("platform")
        if not hasattr(mod, "system"):
            raise ImportError("shadowed platform module")
    except Exception:
        here = os.path.dirname(os.path.abspath(__file__))
        sys.path[:] = [p for p in sys.path if os.path.abspath(p or ".") != here]
        sys.modules.pop("platform", None)
        importlib.import_module("platform")


def main() -> None:
    _bootstrap_stdlib_platform()
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8080"))
    reload = os.environ.get("RELOAD", "0") == "1"
    print(f"UpBain Research Platform v2 (Phase 0) -> http://{host}:{port}")
    uvicorn.run("web.server:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    main()
