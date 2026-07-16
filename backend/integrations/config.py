"""Integration configuration — all values come from environment variables so the
client's real credentials are dropped in on the setup call and NEVER committed.

Every integration is inert until its required env vars are present. Nothing here
runs a network call; it only reports what is configured.
"""
from __future__ import annotations
import os
import re
from pathlib import Path


# ── Notion (CPS database) ─────────────────────────────────────────────────────
NOTION_API_KEY          = os.environ.get("NOTION_API_KEY", "")
NOTION_CPS_DATABASE_ID  = os.environ.get("NOTION_CPS_DATABASE_ID", "")
NOTION_VERSION          = os.environ.get("NOTION_VERSION", "2022-06-28")
# Optional property mapping — filled in on the call once we see their DB schema.
NOTION_STATUS_PROPERTY  = os.environ.get("NOTION_STATUS_PROPERTY", "")   # e.g. "Status"
NOTION_STATUS_EDITING   = os.environ.get("NOTION_STATUS_EDITING", "")    # e.g. "Editing"
NOTION_STATUS_READY     = os.environ.get("NOTION_STATUS_READY", "")      # e.g. "Ready"
NOTION_VIDEO_PROPERTY   = os.environ.get("NOTION_VIDEO_PROPERTY", "")    # URL property, e.g. "Video"
NOTION_VIDEO_FILES_PROPERTY = os.environ.get("NOTION_VIDEO_FILES_PROPERTY", "")  # Files property, e.g. "Video File"

# How the finished cut is delivered:
#   drive_link    -> upload to Google Drive, put the link on the Notion card (default)
#   notion_upload -> upload the video file straight into the Notion card (needs paid plan)
#   both          -> Drive for a permanent link AND a native Notion copy that plays inline
NOTION_DELIVERY_MODE    = os.environ.get("NOTION_DELIVERY_MODE", "drive_link")


# ── Google Drive ──────────────────────────────────────────────────────────────
# Either point to a service-account JSON file, or paste the JSON inline.
GOOGLE_SERVICE_ACCOUNT_FILE = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
# The ONE shared root folder. The machine auto-creates "<Client>/<Edited>/" under it,
# so each creator's files are isolated and never mixed up.
GDRIVE_ROOT_FOLDER_ID       = os.environ.get("GDRIVE_ROOT_FOLDER_ID", "")
GDRIVE_EDITED_SUBFOLDER     = os.environ.get("GDRIVE_EDITED_SUBFOLDER", "Edited")
# Per-client B-roll folder. The client drops B-roll clips here in their Drive and
# the machine pulls them at render time (no in-app upload needed).
GDRIVE_BROLL_SUBFOLDER      = os.environ.get("GDRIVE_BROLL_SUBFOLDER", "B-roll")
# Per-client Source folder — raw footage lives here in Drive (uploaded through the
# app or dropped in directly), so nothing heavy is stored in the app itself.
GDRIVE_SOURCE_SUBFOLDER     = os.environ.get("GDRIVE_SOURCE_SUBFOLDER", "Source")
# Optional flat fallback: drop everything straight into this one folder (no per-client).
GDRIVE_FINISHED_FOLDER_ID   = os.environ.get("GDRIVE_FINISHED_FOLDER_ID", "")
GDRIVE_SHARE_ANYONE         = os.environ.get("GDRIVE_SHARE_ANYONE", "1") == "1"  # link-shareable


# ── Google Drive · sign-in as the user (OAuth) ───────────────────────────────
# The simplest path for a single operator: the machine signs in AS the user one
# time, then delivers onto THEIR OWN Drive (their storage, their files) with no
# Workspace or Shared Drive needed. The client id/secret come from a one-time
# Google Cloud OAuth client; the long-lived token is minted on the Connect flow
# and saved under DATA_ROOT so it survives redeploys. When a token is present it
# takes precedence over any service account above.
GOOGLE_OAUTH_CLIENT_ID     = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
GOOGLE_OAUTH_REDIRECT_URI  = os.environ.get("GOOGLE_OAUTH_REDIRECT_URI", "")  # optional explicit override
# With OAuth, no folder ID need be pasted anywhere: the machine finds or creates
# one root folder by this name in the user's My Drive and works under it.
GDRIVE_ROOT_FOLDER_NAME    = os.environ.get("GDRIVE_ROOT_FOLDER_NAME", "Editing Machine")

# The minted user token lives under DATA_ROOT (same convention as main.py) so it
# persists on the mounted volume across redeploys.
_DATA_ROOT = os.environ.get("DATA_ROOT") or str(Path(__file__).resolve().parent.parent.parent)
GDRIVE_OAUTH_TOKEN_FILE = os.path.join(_DATA_ROOT, "gdrive_oauth.json")


# ── Slack (finished-video notifications) ──────────────────────────────────────
# One Incoming Webhook URL. When set, a message is posted to that channel the
# moment a cut is ready ("<Client> — '<video>' is done"). Inert when unset.
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")


def notion_configured() -> bool:
    return bool(NOTION_API_KEY and NOTION_CPS_DATABASE_ID)


def slack_configured() -> bool:
    return bool(SLACK_WEBHOOK_URL)


def gdrive_oauth_available() -> bool:
    """True when an OAuth client is set up (id + secret present), so the Connect
    button can run — even before the user has actually signed in."""
    return bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)


def gdrive_oauth_ready() -> bool:
    """True once the user has completed the Google sign-in (token stored)."""
    return bool(gdrive_oauth_available() and os.path.exists(GDRIVE_OAUTH_TOKEN_FILE))


def gdrive_configured() -> bool:
    # Signed in as the user (OAuth) needs no folder ID — the root folder is
    # auto-created by name — so a stored token alone means "ready".
    if gdrive_oauth_ready():
        return True
    has_creds  = bool(GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON)
    has_target = bool(GDRIVE_ROOT_FOLDER_ID or GDRIVE_FINISHED_FOLDER_ID)
    return bool(has_creds and has_target)


def normalize_name(name: str) -> str:
    """Canonical form for matching a video filename to a CPS script title.
    Drops extension, lowercases, strips punctuation, collapses whitespace.
    'Let'\''s Go Get Coffee.mov'  ->  'lets go get coffee'
    """
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name or "").strip()
    stem = stem.lower()
    stem = re.sub(r"[^\w\s]", "", stem)      # drop apostrophes/punctuation
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def status() -> dict:
    """Machine-readable snapshot of what's wired up — powers /api/integrations/status."""
    missing_notion = [k for k, v in {
        "NOTION_API_KEY": NOTION_API_KEY,
        "NOTION_CPS_DATABASE_ID": NOTION_CPS_DATABASE_ID,
    }.items() if not v]
    if gdrive_oauth_ready():
        gdrive_method, missing_gdrive = "oauth", []
    elif gdrive_oauth_available():
        gdrive_method = "oauth_pending"
        missing_gdrive = ["Click Connect Google Drive to sign in"]
    else:
        gdrive_method = "service_account" if (GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON) else "unset"
        missing_gdrive = []
        if not (GOOGLE_SERVICE_ACCOUNT_FILE or GOOGLE_SERVICE_ACCOUNT_JSON):
            missing_gdrive.append("GOOGLE_OAUTH_CLIENT_ID + GOOGLE_OAUTH_CLIENT_SECRET (then Connect), or a service account")
        if not (GDRIVE_ROOT_FOLDER_ID or GDRIVE_FINISHED_FOLDER_ID):
            missing_gdrive.append("GDRIVE_ROOT_FOLDER_ID")
    return {
        "delivery_mode": NOTION_DELIVERY_MODE,
        "notion": {
            "configured": notion_configured(),
            "missing": missing_notion,
            "status_property_mapped": bool(NOTION_STATUS_PROPERTY),
            "video_url_property_mapped": bool(NOTION_VIDEO_PROPERTY),
            "video_files_property_mapped": bool(NOTION_VIDEO_FILES_PROPERTY),
        },
        "google_drive": {
            "configured": gdrive_configured(),
            "method": gdrive_method,
            "oauth_available": gdrive_oauth_available(),
            "oauth_connected": gdrive_oauth_ready(),
            "missing": missing_gdrive,
            "share_link": GDRIVE_SHARE_ANYONE,
            "layout": "oauth_my_drive" if gdrive_oauth_ready() else ("per_client" if GDRIVE_ROOT_FOLDER_ID else ("flat" if GDRIVE_FINISHED_FOLDER_ID else "unset")),
            "edited_subfolder": GDRIVE_EDITED_SUBFOLDER,
        },
        "slack": {
            "configured": slack_configured(),
            "missing": [] if slack_configured() else ["SLACK_WEBHOOK_URL"],
        },
    }
