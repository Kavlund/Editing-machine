"""Delivery orchestrator — the single entry point the app calls.

on_upload(name)              : match the CPS card and mark it in-progress
deliver_finished(name, path) : upload the cut to Drive, link it on the CPS card

Both are fully best-effort and swallow all errors: an integration hiccup must
never break an upload or a render. When nothing is configured, they no-op.
"""
from __future__ import annotations
from pathlib import Path

from . import config, notion_cps, gdrive


def on_upload(name: str, log=lambda m: None):
    """Called the moment a video is uploaded. Marks the matching CPS card editing."""
    if not config.notion_configured():
        return
    notion_cps.mark_editing(name, log=log)


def deliver_finished(name: str, client_name: str, final_path: Path, log=lambda m: None):
    """Called when final.mp4 is ready.
      `name`        -> the video/script name (filename in Drive, CPS match key)
      `client_name` -> the creator, used to pick their Drive subfolder

    Delivery per NOTION_DELIVERY_MODE (default drive_link):
      drive_link    -> upload to <client>/Edited/ in Drive, link on the card if Notion on
      notion_upload -> native video embedded in the Notion card
      both          -> Drive upload + native embed
    """
    if not (config.gdrive_configured() or config.notion_configured()):
        return

    mode = (config.NOTION_DELIVERY_MODE or "drive_link").lower()
    final_path = Path(final_path)

    # Google Drive (for drive_link / both, or as the only target if Notion is off)
    link = None
    if config.gdrive_configured() and mode in ("drive_link", "both"):
        link = gdrive.upload_video(final_path, name, client_name, log=log)

    if config.notion_configured():
        if mode in ("notion_upload", "both"):
            notion_cps.attach_video_file(name, final_path, link or "", log=log)
        else:  # drive_link
            notion_cps.attach_video(name, link or "", log=log)

    # The Drive link (truthy) is our confirmation the finished video is safely
    # stored in Drive — the caller uses it to drop the local copy. The single
    # Slack ping is sent by the pipeline (one message per finished / failed video).
    return link


def on_client_created(client_name: str, log=lambda m: None):
    """Called when a new client is added — provisions their Drive folder up front."""
    if config.gdrive_configured():
        gdrive.provision_client_folder(client_name, log=log)


def is_active() -> bool:
    return config.notion_configured() or config.gdrive_configured()
