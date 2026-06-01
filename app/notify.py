"""Simple synchronous Telegram sender (httpx only).

Deliberately avoids ``python-telegram-bot`` so the scheduler's plain functions
never have to share an event loop with the bot's polling app. Reads
``TELEGRAM_BOT_TOKEN`` + ``TELEGRAM_CHAT_ID`` from the environment (``.env`` via
python-dotenv).

Every function is safe to call with no credentials: missing token/chat_id logs a
warning and returns ``False`` instead of raising, so the scheduler can run in dev
without secrets. Network/API failures are swallowed (logged) and return ``False``.
"""

from __future__ import annotations

import logging
import os

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - dotenv is a soft dependency
    pass

log = logging.getLogger("topshelf.notify")

_API_BASE = "https://api.telegram.org"
_TIMEOUT = 15.0


def _creds() -> tuple[str | None, str | None]:
    """Return ``(token, chat_id)`` from the environment (either may be None)."""
    token = os.getenv("TELEGRAM_BOT_TOKEN") or None
    chat_id = os.getenv("TELEGRAM_CHAT_ID") or None
    return token, chat_id


def is_configured() -> bool:
    """True only when both token and chat id are present."""
    token, chat_id = _creds()
    return bool(token and chat_id)


def send_message(html: str) -> bool:
    """POST ``sendMessage`` with ``parse_mode=HTML``. Never raises.

    Returns ``False`` (and logs a warning) when credentials are missing or the
    Telegram API call fails for any reason.
    """
    token, chat_id = _creds()
    if not token or not chat_id:
        log.warning("Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing); skipping send_message.")
        return False

    payload = {
        "chat_id": chat_id,
        "text": html,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = httpx.post(
            f"{_API_BASE}/bot{token}/sendMessage",
            json=payload,
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            log.warning("sendMessage failed: HTTP %s %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - never crash the scheduler
        log.warning("sendMessage error: %s", exc)
        return False


def send_photo(img_url: str, caption_html: str) -> bool:
    """POST ``sendPhoto`` with an HTML caption. Never raises.

    Returns ``False`` on missing credentials or any failure.
    """
    token, chat_id = _creds()
    if not token or not chat_id:
        log.warning("Telegram not configured; skipping send_photo.")
        return False

    url = f"{_API_BASE}/bot{token}/sendPhoto"
    data = {"chat_id": chat_id, "caption": caption_html, "parse_mode": "HTML"}

    # Download bytes first and upload them (handles extensionless/webp S3 URLs
    # that Telegram often refuses to fetch by URL).
    try:
        img = httpx.get(img_url, follow_redirects=True, timeout=_TIMEOUT)
        if img.status_code == 200 and img.content:
            files = {"photo": ("deal.jpg", img.content)}
            resp = httpx.post(url, data=data, files=files, timeout=_TIMEOUT)
            if resp.status_code == 200:
                return True
            log.warning("sendPhoto (bytes) failed: HTTP %s %s", resp.status_code, resp.text[:300])
    except Exception as exc:  # noqa: BLE001
        log.warning("sendPhoto bytes error: %s", exc)

    # Fallback: let Telegram fetch the URL itself.
    try:
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "photo": img_url, "caption": caption_html, "parse_mode": "HTML"},
            timeout=_TIMEOUT,
        )
        if resp.status_code != 200:
            log.warning("sendPhoto (url) failed: HTTP %s %s", resp.status_code, resp.text[:300])
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - never crash the scheduler
        log.warning("sendPhoto url error: %s", exc)
        return False
