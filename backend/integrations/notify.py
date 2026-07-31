"""Finished-video notifications to the creator's chosen channel(s).

Configured in the Control Center UI (saved to DATA_ROOT/notify.json), so an
instance can pick Telegram, Slack and/or Discord without touching env vars.
Legacy SLACK_WEBHOOK_URL still works as a fallback Slack channel.

Best-effort and one-directional: a channel hiccup must never break a render or a
delivery. Uses urllib (no third-party dependency) so it works even where
`requests` isn't installed.
"""
from __future__ import annotations

import html
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

_DATA_ROOT = os.environ.get("DATA_ROOT") or str(Path(__file__).resolve().parent.parent.parent)
_CFG = Path(_DATA_ROOT) / "notify.json"

# Channel registry. `secret` = the sensitive field (never echoed back to the UI);
# `target` = an extra non-secret field a channel needs (Telegram's chat id).
CHANNELS = {
    "telegram": {"label": "Telegram", "secret": "bot_token", "target": "chat_id"},
    "slack":    {"label": "Slack",    "secret": "webhook",    "target": None},
    "discord":  {"label": "Discord",  "secret": "webhook",    "target": None},
}


def stored() -> dict:
    """Raw saved config (no env fallback folded in) — the base for edits/saves."""
    try:
        return json.loads(_CFG.read_text()) if _CFG.exists() else {}
    except Exception:
        return {}


def load() -> dict:
    """Config for SENDING: the saved file plus the legacy SLACK_WEBHOOK_URL env as
    a Slack fallback when the UI hasn't set one."""
    cfg = stored()
    env_slack = os.environ.get("SLACK_WEBHOOK_URL", "").strip()
    if env_slack and not (cfg.get("slack") or {}).get("webhook"):
        s = cfg.setdefault("slack", {})
        s["webhook"] = env_slack
        s.setdefault("enabled", True)
    return cfg


def save(cfg: dict) -> None:
    _CFG.parent.mkdir(parents=True, exist_ok=True)
    _CFG.write_text(json.dumps(cfg, indent=2))


def _post_json(url: str, payload: dict, timeout: int = 8) -> int:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        # The API's error body carries the real reason (e.g. Telegram's
        # "chat not found"); surface it instead of a bare "400 Bad Request".
        desc = ""
        try:
            body = e.read().decode("utf-8", "replace")
            j = json.loads(body)
            desc = j.get("description") or j.get("message") or j.get("error") or body[:200]
        except Exception:
            desc = ""
        raise ValueError(f"{e.code}: {desc}".strip().rstrip(":") if desc else f"HTTP {e.code}") from None


def _send_telegram(c: dict, text_html: str) -> None:
    token = (c.get("bot_token") or "").strip()
    chat = (c.get("chat_id") or "").strip()
    if not token or not chat:
        raise ValueError("missing bot token or chat id")
    # Telegram HTML parse mode (Drive URLs with underscores break Markdown).
    _post_json(f"https://api.telegram.org/bot{token}/sendMessage",
               {"chat_id": chat, "text": text_html, "parse_mode": "HTML",
                "disable_web_page_preview": False})


def _send_slack(c: dict, text_md: str) -> None:
    wh = (c.get("webhook") or "").strip()
    if not wh:
        raise ValueError("missing webhook url")
    _post_json(wh, {"text": text_md})


def _send_discord(c: dict, text_plain: str) -> None:
    wh = (c.get("webhook") or "").strip()
    if not wh:
        raise ValueError("missing webhook url")
    _post_json(wh, {"content": text_plain})


_SENDERS = {"telegram": _send_telegram, "slack": _send_slack, "discord": _send_discord}


def _fmt(channel: str, done: bool, client: str, video: str, link: str = "", err: str = "") -> str:
    client = (client or "A client").strip()
    video = (video or "video").strip()
    if channel == "telegram":
        c, v = html.escape(client), html.escape(video)
        if done:
            return f"✅ <b>{c}</b> — {v} is done." + (f"\n{link}" if link else "")
        return f"❌ <b>{c}</b> — {v} failed.\n{html.escape((err or '')[:180])}"
    if channel == "slack":
        if done:
            return f":white_check_mark: *{client}* — `{video}` is done." + (f"\n{link}" if link else "")
        return f":x: *{client}* — `{video}` failed. {(err or '')[:180]}"
    # discord + any fallback: plain markdown
    if done:
        return f"✅ **{client}** — {video} is done." + (f"\n{link}" if link else "")
    return f"❌ **{client}** — {video} failed. {(err or '')[:180]}"


def _dispatch(done: bool, client: str, video: str, link: str, err: str, log) -> None:
    cfg = load()
    for ch in CHANNELS:
        c = cfg.get(ch) or {}
        if not c.get("enabled"):
            continue
        try:
            _SENDERS[ch](c, _fmt(ch, done, client, video, link, err))
            log(f"notify: {'done' if done else 'failed'} sent via {ch}")
        except Exception as e:  # never let a channel break the pipeline
            log(f"notify: {ch} send failed ({e})")


def send_finished(client: str, video: str, link: str = "", log=lambda m: None) -> None:
    _dispatch(True, client, video, link, "", log)


def send_failed(client: str, video: str, err: str = "", log=lambda m: None) -> None:
    _dispatch(False, client, video, "", err, log)


def test(channel: str, override: dict | None = None) -> tuple[bool, str]:
    """Send a test message on `channel`, using `override` values (unsaved edits
    from the UI) on top of the saved config. Returns (ok, error)."""
    if channel not in CHANNELS:
        return False, "unknown channel"
    c = dict(load().get(channel) or {})
    for k, v in (override or {}).items():
        if str(v or "").strip():
            c[k] = str(v).strip()
    try:
        _SENDERS[channel](c, _fmt(channel, True, "Acquisition Empire", "a test notification", ""))
        return True, ""
    except Exception as e:
        return False, str(e)


def status() -> dict:
    """Per-channel {enabled, configured} for the Control Center pills."""
    cfg = load()
    out = {}
    for ch, meta in CHANNELS.items():
        c = cfg.get(ch) or {}
        secret_ok = bool((c.get(meta["secret"]) or "").strip())
        target_ok = True if not meta["target"] else bool((c.get(meta["target"]) or "").strip())
        out[ch] = {"enabled": bool(c.get("enabled")), "configured": secret_ok and target_ok}
    out["any"] = any(v["enabled"] and v["configured"] for v in out.values())
    return out
