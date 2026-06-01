"""TopShelf system-tray launcher (Windows).

Double-clicking the desktop icon runs this under ``pythonw.exe``. It:

1. Kills any prior TopShelf processes (old tray app, web server, bot) so every
   launch is a clean, single instance.
2. Waits for port 8000 to free and for Telegram to release the previous bot's
   long-poll (so the new bot never hits a getUpdates ``Conflict``).
3. Starts the FastAPI web server and the Telegram bot in the background (no
   console windows; output goes to ``logs/``).
4. Opens the dashboard in the browser once the server is healthy.
5. Sits in the system tray as a cannabis-leaf icon with Open / Restart / Quit.

The bot also holds its own localhost-port singleton (see ``app/bot/bot.py``), so
even if something double-spawns it, only one instance ever polls Telegram.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
LOG_DIR = REPO_ROOT / "logs"
ASSETS = REPO_ROOT / "assets"

WEB_PORT = 8000
BOT_SINGLETON_PORT = 49217  # must match app/bot/bot.py
DASHBOARD_URL = f"http://127.0.0.1:{WEB_PORT}/TopShelf.html"

# Telegram keeps a killed bot's long-poll open for ~10s; wait a touch longer
# before starting the new poller so it never sees a transient Conflict.
TELEGRAM_RELEASE_WAIT = 12.0

# Markers identifying our processes in their command lines.
WEB_MARKER = "app.main:app"
BOT_MARKER = "app.bot.bot"
TRAY_MARKER = "tray_app.py"

CREATE_NO_WINDOW = 0x08000000  # Windows: no console window for children


# --------------------------------------------------------------------------- #
# Interpreter resolution
# --------------------------------------------------------------------------- #
def _python_exe() -> str:
    """Console python.exe in this venv (children run hidden via CREATE_NO_WINDOW)."""
    exe = Path(sys.executable)
    cand = exe.with_name("python.exe")
    return str(cand if cand.exists() else exe)


PYTHON = _python_exe()


# --------------------------------------------------------------------------- #
# Process management
# --------------------------------------------------------------------------- #
def _iter_topshelf_pids():
    """Yield (pid, cmdline-str) for running TopShelf processes (best effort)."""
    try:
        import psutil
    except ImportError:
        return iter([])  # empty generator if psutil not available
    me = os.getpid()
    try:
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                pid = proc.info["pid"]
                if pid == me:
                    continue
                cmd = " ".join(proc.info["cmdline"] or [])
            except Exception:
                continue
            if any(m in cmd for m in (WEB_MARKER, BOT_MARKER, TRAY_MARKER)):
                yield pid, cmd
    except Exception:
        # If process iteration fails entirely, at least try to continue
        pass


def _kill_tree(pid: int) -> None:
    try:
        import psutil
    except ImportError:
        return
    try:
        proc = psutil.Process(pid)
    except Exception:
        return
    procs = []
    try:
        procs = proc.children(recursive=True)
    except Exception:
        pass
    procs.append(proc)
    for p in procs:
        try:
            p.terminate()
        except Exception:
            pass
    _, alive = psutil.wait_procs(procs, timeout=5)
    for p in alive:
        try:
            p.kill()
        except Exception:
            pass


def _port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        return s.connect_ex(("127.0.0.1", port)) != 0
    finally:
        s.close()


def _wait_port_free(port: int, timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if _port_free(port):
                return
        except Exception as e:
            print(f"Warning checking port {port}: {e}", flush=True)
        time.sleep(0.4)
    print(f"Timeout waiting for port {port} to free", flush=True)


def cleanup() -> float:
    """Kill any prior TopShelf processes. Returns the monotonic time of the kill."""
    try:
        for pid, _cmd in list(_iter_topshelf_pids()):
            try:
                _kill_tree(pid)
            except Exception as e:
                print(f"Warning killing {pid}: {e}")
    except Exception as e:
        print(f"Warning during cleanup: {e}")
    
    try:
        _wait_port_free(WEB_PORT, timeout=15.0)
    except Exception as e:
        print(f"Warning waiting for port {WEB_PORT}: {e}")
    
    try:
        _wait_port_free(BOT_SINGLETON_PORT, timeout=10.0)
    except Exception as e:
        print(f"Warning waiting for singleton port: {e}")
    
    return time.monotonic()


# --------------------------------------------------------------------------- #
# Service control
# --------------------------------------------------------------------------- #
class Services:
    """Owns the web-server and bot subprocesses and their lifecycle."""

    def __init__(self) -> None:
        self.web: subprocess.Popen | None = None
        self.bot: subprocess.Popen | None = None
        self._killed_at = 0.0
        self._lock = threading.Lock()
        self._shutting_down = False

    # -- spawning -----------------------------------------------------------
    def _spawn(self, args: list[str], log_name: str) -> subprocess.Popen:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        log = open(LOG_DIR / log_name, "a", buffering=1, encoding="utf-8")
        return subprocess.Popen(
            [PYTHON, *args],
            cwd=str(REPO_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=CREATE_NO_WINDOW,
        )

    def start_web(self) -> None:
        self.web = self._spawn(
            ["-m", "uvicorn", "app.main:app", "--port", str(WEB_PORT)],
            "web.log",
        )

    def start_bot(self) -> None:
        # Respect the Telegram release window measured from the last kill.
        if self._killed_at:
            elapsed = time.monotonic() - self._killed_at
            remaining = TELEGRAM_RELEASE_WAIT - elapsed
            if remaining > 0:
                time.sleep(remaining)
        self.bot = self._spawn(["-m", "app.bot.bot"], "bot.log")

    # -- health -------------------------------------------------------------
    def wait_web_healthy(self, timeout: float = 30.0) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                s = socket.create_connection(("127.0.0.1", WEB_PORT), timeout=1.0)
                s.close()
                return True
            except OSError:
                time.sleep(0.5)
        return False

    def web_alive(self) -> bool:
        return self.web is not None and self.web.poll() is None

    def bot_alive(self) -> bool:
        return self.bot is not None and self.bot.poll() is None

    # -- lifecycle ----------------------------------------------------------
    def start_all(self) -> None:
        with self._lock:
            self._killed_at = cleanup()
            self.start_web()
        self.wait_web_healthy()
        try:
            webbrowser.open(DASHBOARD_URL)
        except Exception:
            pass
        with self._lock:
            self.start_bot()

    def restart(self) -> None:
        with self._lock:
            self._shutting_down = True
            for p in (self.bot, self.web):
                if p is not None:
                    try:
                        _kill_tree(p.pid)
                    except Exception:
                        pass
            self.bot = self.web = None
            self._shutting_down = False
        self.start_all()

    def stop_all(self) -> None:
        with self._lock:
            self._shutting_down = True
            for p in (self.bot, self.web):
                if p is not None:
                    try:
                        _kill_tree(p.pid)
                    except Exception:
                        pass
            self.bot = self.web = None

    def shutting_down(self) -> bool:
        return self._shutting_down


# --------------------------------------------------------------------------- #
# Tray UI
# --------------------------------------------------------------------------- #
def _load_icon_image():
    from PIL import Image

    for name in ("topshelf.png", "topshelf.ico"):
        p = ASSETS / name
        if p.exists():
            try:
                return Image.open(p)
            except Exception:
                continue
    # Fallback: a plain green square so the tray still shows something.
    from PIL import Image as _I
    return _I.new("RGBA", (64, 64), (28, 107, 57, 255))


# Restart backoff: if a child dies repeatedly within this window we are almost
# certainly in a hard-failure loop (e.g. a stuck port), so we stop hammering and
# wait, instead of respawning every 5s forever (the prior crash-loop bug).
_RESTART_WINDOW_SEC = 60.0
_MAX_RESTARTS_PER_WINDOW = 4
_BACKOFF_SEC = 60.0


def main() -> None:
    print("TopShelf launcher starting services...", flush=True)
    services = Services()

    # Kill any prior TopShelf processes and wait for the web port + bot singleton
    # to free BEFORE starting fresh. Skipping this was the cause of the endless
    # "address already in use" crash-loop: a stale server held :8000, every new
    # child failed to bind, and the monitor loop respawned it forever.
    print("Cleaning up any prior TopShelf processes...", flush=True)
    try:
        services._killed_at = cleanup()
    except Exception as e:
        print(f"Warning: cleanup failed ({e}); continuing", flush=True)

    print("Starting web server...", flush=True)
    services.start_web()
    print("Web server process started", flush=True)

    print("Waiting for web to be healthy...", flush=True)
    if not services.wait_web_healthy():
        print("ERROR: Web server did not become healthy", flush=True)
        services.stop_all()
        return
    print("Web server is healthy", flush=True)

    print(f"Opening browser to {DASHBOARD_URL}", flush=True)
    try:
        webbrowser.open(DASHBOARD_URL)
        # Show Windows notification
        try:
            from win10toast import ToastNotifier
            toaster = ToastNotifier()
            toaster.show_toast("TopShelf", "Web server running at http://127.0.0.1:8000", duration=10, threaded=True)
        except ImportError:
            pass  # win10toast not installed, that's OK
    except Exception as e:
        print(f"Warning: Could not open browser: {e}", flush=True)

    print("Starting bot...", flush=True)
    services.start_bot()
    print("Bot process started", flush=True)

    print("All services running. Monitoring...", flush=True)
    # Sliding-window restart counters so a hard-failing child can't hot-loop.
    web_restarts: list[float] = []
    bot_restarts: list[float] = []

    def _throttled(stamps: list[float]) -> bool:
        """True if we've restarted too many times recently (so we should back off)."""
        now = time.monotonic()
        stamps[:] = [t for t in stamps if now - t < _RESTART_WINDOW_SEC]
        if len(stamps) >= _MAX_RESTARTS_PER_WINDOW:
            return True
        stamps.append(now)
        return False

    try:
        while True:
            time.sleep(5)
            if not services.web_alive():
                if _throttled(web_restarts):
                    print(
                        f"Web crashing repeatedly; backing off {_BACKOFF_SEC:.0f}s "
                        "(check logs/web.log - likely port 8000 still in use)",
                        flush=True,
                    )
                    time.sleep(_BACKOFF_SEC)
                    cleanup()  # try to free the port before the next attempt
                    web_restarts.clear()
                print("Web crashed, restarting...", flush=True)
                services.start_web()
            if not services.bot_alive():
                if _throttled(bot_restarts):
                    print(
                        f"Bot crashing repeatedly; backing off {_BACKOFF_SEC:.0f}s "
                        "(check logs/bot.log - likely singleton port held)",
                        flush=True,
                    )
                    time.sleep(_BACKOFF_SEC)
                    bot_restarts.clear()
                print("Bot crashed, restarting...", flush=True)
                services.start_bot()
    except KeyboardInterrupt:
        print("Shutting down...", flush=True)
        services.stop_all()
    except Exception as e:
        print(f"FATAL error in main loop: {e}", flush=True)
        services.stop_all()


if __name__ == "__main__":
    # Redirect all output to a log file so pystray doesn't try to interact with
    # a non-existent console (happens when run under pythonw or with redirected stdio).
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    tray_log = open(LOG_DIR / "tray.log", "a", buffering=1, encoding="utf-8")
    sys.stdout = tray_log
    sys.stderr = tray_log
    print(f"=== TopShelf Tray Launcher started {time.ctime()} ===")
    try:
        main()
    except Exception as e:
        print(f"FATAL: {e}")
        import traceback
        traceback.print_exc()
    finally:
        tray_log.close()
