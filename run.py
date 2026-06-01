r"""TopShelf single-process supervisor.

Runs the WHOLE stack in one OS process, on one shared asyncio event loop:

* the FastAPI web app (uvicorn, programmatic, **no** ``--reload``),
* the Telegram bot (python-telegram-bot long-polling), and
* the APScheduler jobs (scrape / daily alert / recurring / weekly digest).

It is **single-instance safe**: before doing anything it grabs a process-wide
lock by binding a localhost TCP socket on a fixed port. If a second copy starts
while the first is alive, the bind fails, we print a clear message and exit 0 —
so we never spin up a duplicate bot poller (the classic
``Conflict: terminated by other getUpdates`` cause).

Run it (production)::

    .\.venv\Scripts\python.exe run.py

Stop it with Ctrl+C — the bot, web server, and scheduler all shut down cleanly.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import sys

# The embedded uvicorn app must NOT start its own scheduler: run.py owns the
# single scheduler. Force this BEFORE app.main is ever imported.
os.environ["ENABLE_SCHEDULER"] = "0"

log = logging.getLogger("topshelf.run")

# Fixed localhost port used purely as a single-instance mutex (overridable).
_LOCK_PORT = int(os.getenv("RUN_LOCK_PORT", "8765"))

# Hold the bound lock socket for the lifetime of the process so it isn't GC'd
# (closing it would release the lock and let a second instance start).
_lock_socket: socket.socket | None = None


def acquire_single_instance_lock(port: int | None = None) -> socket.socket | None:
    """Acquire the process-wide single-instance lock.

    Binds a TCP socket to ``127.0.0.1:<port>``. Binding is atomic and exclusive:
    a second process (or a second in-process call) that tries the same port gets
    ``OSError`` (``WSAEADDRINUSE`` on Windows) and we return ``None``.

    Returns the bound socket on success (kept alive in a module global) or
    ``None`` if the lock is already held. Never raises.
    """
    global _lock_socket
    port = _LOCK_PORT if port is None else port

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Deliberately do NOT set SO_REUSEADDR — we WANT a second bind to fail.
    try:
        sock.bind(("127.0.0.1", port))
        sock.listen(1)
    except OSError:
        sock.close()
        return None

    # Keep a reference so the lock is held for the whole process lifetime.
    if _lock_socket is None:
        _lock_socket = sock
    return sock


def _port() -> int:
    try:
        return int(os.getenv("PORT", "8000"))
    except (TypeError, ValueError):
        return 8000


async def _serve() -> None:
    """Run uvicorn + the Telegram bot + the scheduler on one event loop."""
    import uvicorn

    from app import db
    from app.scheduler import shutdown_scheduler, start_scheduler

    db.run_migrations()

    # --- Web server (programmatic uvicorn, no reload) -----------------------
    config = uvicorn.Config(
        "app.main:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=_port(),
        reload=False,
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info"),
    )
    server = uvicorn.Server(config)

    # --- Telegram bot (built only if a token is configured) -----------------
    application = None
    try:
        from app.bot.bot import TELEGRAM_BOT_TOKEN, build_application

        if TELEGRAM_BOT_TOKEN:
            application = build_application()
        else:
            log.warning("TELEGRAM_BOT_TOKEN unset — running web + scheduler only.")
    except Exception:  # noqa: BLE001 - never let bot wiring kill the web server
        log.exception("failed to build Telegram application; continuing without the bot")
        application = None

    # --- Scheduler (run.py owns the single instance) ------------------------
    start_scheduler()

    # Start the bot exactly once (manual lifecycle so it shares THIS loop).
    if application is not None:
        await application.initialize()
        await application.start()
        await application.updater.start_polling(drop_pending_updates=True)
        log.info("Telegram bot polling started.")

    try:
        # Blocks until Ctrl+C / SIGTERM (uvicorn installs the signal handlers).
        await server.serve()
    finally:
        # Graceful, best-effort teardown in reverse order.
        if application is not None:
            try:
                if application.updater is not None:
                    await application.updater.stop()
                await application.stop()
                await application.shutdown()
            except Exception:  # noqa: BLE001
                log.exception("error during bot shutdown")
        shutdown_scheduler()


def main() -> int:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if acquire_single_instance_lock() is None:
        print(
            f"TopShelf is already running (single-instance lock on "
            f"127.0.0.1:{_LOCK_PORT} is held). Not starting a second instance.",
            file=sys.stderr,
        )
        return 0

    print(
        f"TopShelf supervisor starting — web on :{_port()}, Telegram bot + "
        f"scheduler in-process. Ctrl+C to stop."
    )
    try:
        asyncio.run(_serve())
    except KeyboardInterrupt:
        print("\nShutting down TopShelf…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
