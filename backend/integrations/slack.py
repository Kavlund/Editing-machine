"""Slack notifications — post to an Incoming Webhook when a cut is ready.

One-directional and best-effort: a Slack hiccup must never break a render or a
delivery. No-op when SLACK_WEBHOOK_URL isn't configured.

Setup (client, on the call): create a Slack app -> enable Incoming Webhooks ->
add one to the target channel -> paste the webhook URL as SLACK_WEBHOOK_URL.
"""
from __future__ import annotations

from . import config


def notify_finished(client_name: str, video_name: str, link: str = "",
                    log=lambda m: None) -> None:
    """Post '<Client> — "<video>" is done' to the configured Slack channel.
    Never raises; logs and returns quietly on any problem."""
    if not config.slack_configured():
        return
    try:
        import requests
    except ImportError:
        log("slack: requests not installed — cannot send notification")
        return

    client = (client_name or "").strip() or "A client"
    name = (video_name or "video").strip()
    text = f":white_check_mark: *{client}* — \"{name}\" is done. Go have a look."
    if link:
        text += f"\n{link}"

    try:
        r = requests.post(config.SLACK_WEBHOOK_URL, json={"text": text}, timeout=10)
        if r.status_code >= 300:
            log(f"slack: webhook returned {r.status_code} — check SLACK_WEBHOOK_URL")
        else:
            log(f"slack: notified '{client}' channel that '{name}' is ready")
    except Exception as e:
        log(f"slack: could not send notification ({e})")
