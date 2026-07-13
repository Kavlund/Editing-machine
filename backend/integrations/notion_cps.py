"""Notion CPS integration — match an uploaded video to an EXISTING script card by
name and update it (never creates pages). Uses the Notion REST API via requests.

Workflow (per the client's CPS setup):
  - Their CPS database already has a card per script, titled with the script name.
  - A video uploaded as "Let's go get coffee" is matched to that card by name.
  - On upload  -> mark the card as in-progress (if a Status property is mapped).
  - On finish  -> put the finished-video link on the card + mark it ready.

Everything is best-effort: if Notion isn't configured or a call fails, functions
return None and the caller logs a warning — the render is never blocked.
"""
from __future__ import annotations
import math
from pathlib import Path
import requests

from . import config

API = "https://api.notion.com/v1"
_title_prop_cache: dict[str, str] = {}

_SINGLE_PART_MAX = 20 * 1024 * 1024   # Notion single-part upload limit
_PART_SIZE       = 10 * 1024 * 1024   # chunk size for multi-part (5-20 MB allowed)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": config.NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _title_property() -> str | None:
    """Discover the database's title property name (every DB has exactly one)."""
    db = config.NOTION_CPS_DATABASE_ID
    if db in _title_prop_cache:
        return _title_prop_cache[db]
    r = requests.get(f"{API}/databases/{db}", headers=_headers(), timeout=15)
    r.raise_for_status()
    for name, prop in r.json().get("properties", {}).items():
        if prop.get("type") == "title":
            _title_prop_cache[db] = name
            return name
    return None


def _page_title(page: dict, title_prop: str) -> str:
    parts = page.get("properties", {}).get(title_prop, {}).get("title", [])
    return "".join(p.get("plain_text", "") for p in parts)


def find_page(name: str) -> str | None:
    """Return the page_id of the CPS card whose title matches `name`, or None."""
    if not config.notion_configured():
        return None
    target = config.normalize_name(name)
    title_prop = _title_property()
    if not title_prop:
        return None

    cursor = None
    while True:
        body = {"page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        r = requests.post(f"{API}/databases/{config.NOTION_CPS_DATABASE_ID}/query",
                          headers=_headers(), json=body, timeout=20)
        r.raise_for_status()
        data = r.json()
        for page in data.get("results", []):
            if config.normalize_name(_page_title(page, title_prop)) == target:
                return page["id"]
        if not data.get("has_more"):
            return None
        cursor = data.get("next_cursor")


def _patch_page(page_id: str, properties: dict) -> bool:
    r = requests.patch(f"{API}/pages/{page_id}", headers=_headers(),
                       json={"properties": properties}, timeout=20)
    r.raise_for_status()
    return True


def _upload_headers() -> dict:
    # No Content-Type here — requests sets the multipart boundary for file sends.
    return {
        "Authorization": f"Bearer {config.NOTION_API_KEY}",
        "Notion-Version": config.NOTION_VERSION,
    }


def upload_file(local_path: Path, filename: str, log=lambda m: None) -> str | None:
    """Upload a video file straight into Notion's storage. Returns a file_upload id
    (usable for ~1 hour to attach to a page/property), or None on failure.
    Uses single-part for <=20MB, multi-part otherwise."""
    local_path = Path(local_path)
    size = local_path.stat().st_size
    try:
        if size <= _SINGLE_PART_MAX:
            # 1) create
            r = requests.post(f"{API}/file_uploads", headers=_headers(),
                              json={"filename": filename, "content_type": "video/mp4"}, timeout=30)
            r.raise_for_status()
            fu = r.json(); fu_id = fu["id"]
            # 2) send the bytes
            with open(local_path, "rb") as fh:
                s = requests.post(f"{API}/file_uploads/{fu_id}/send",
                                  headers=_upload_headers(),
                                  files={"file": (filename, fh, "video/mp4")}, timeout=300)
            s.raise_for_status()
            log(f"notion: uploaded '{filename}' ({size/1e6:.1f} MB, single-part)")
            return fu_id

        # multi-part
        nparts = math.ceil(size / _PART_SIZE)
        r = requests.post(f"{API}/file_uploads", headers=_headers(),
                          json={"filename": filename, "content_type": "video/mp4",
                                "mode": "multi_part", "number_of_parts": nparts}, timeout=30)
        r.raise_for_status()
        fu_id = r.json()["id"]
        with open(local_path, "rb") as fh:
            for part in range(1, nparts + 1):
                chunk = fh.read(_PART_SIZE)
                s = requests.post(f"{API}/file_uploads/{fu_id}/send",
                                  headers=_upload_headers(),
                                  data={"part_number": str(part)},
                                  files={"file": (filename, chunk, "video/mp4")}, timeout=300)
                s.raise_for_status()
        c = requests.post(f"{API}/file_uploads/{fu_id}/complete", headers=_headers(),
                          json={}, timeout=60)
        c.raise_for_status()
        log(f"notion: uploaded '{filename}' ({size/1e6:.1f} MB, {nparts} parts)")
        return fu_id
    except Exception as e:
        log(f"notion: file upload failed ({e})")
        return None


def attach_video_file(name: str, local_path: Path, video_url: str = "", log=lambda m: None):
    """On finish (notion_upload / both mode): upload the cut into Notion, embed it on
    the matched card as an inline video, optionally also set a Files property and a
    URL link, then mark the card ready."""
    if not config.notion_configured():
        return
    try:
        page_id = find_page(name)
        if not page_id:
            log(f"notion: no CPS card titled '{name}' to upload the video to — skipping")
            return
        filename = f"{name}.mp4" if not str(name).lower().endswith(".mp4") else str(name)
        fu_id = upload_file(Path(local_path), filename, log=log)
        if not fu_id:
            return

        # Embed as an inline, playable video block on the page
        requests.patch(f"{API}/blocks/{page_id}/children", headers=_headers(),
                       json={"children": [{"object": "block", "type": "video",
                             "video": {"type": "file_upload", "file_upload": {"id": fu_id}}}]},
                       timeout=30)

        props: dict = {}
        if config.NOTION_VIDEO_FILES_PROPERTY:
            props[config.NOTION_VIDEO_FILES_PROPERTY] = {"files": [
                {"type": "file_upload", "file_upload": {"id": fu_id}, "name": filename}]}
        if config.NOTION_VIDEO_PROPERTY and video_url:
            props[config.NOTION_VIDEO_PROPERTY] = {"url": video_url}
        if config.NOTION_STATUS_PROPERTY and config.NOTION_STATUS_READY:
            props[config.NOTION_STATUS_PROPERTY] = {"status": {"name": config.NOTION_STATUS_READY}}
        if props:
            _patch_page(page_id, props)
        log(f"notion: embedded finished video on '{name}'")
    except Exception as e:
        log(f"notion: attach_video_file failed ({e})")


def mark_editing(name: str, log=lambda m: None):
    """On upload: flip the matched card's Status to the 'editing' value (if mapped)."""
    if not config.notion_configured():
        return
    try:
        page_id = find_page(name)
        if not page_id:
            log(f"notion: no CPS card titled '{name}' — skipping (only updates existing)")
            return
        if config.NOTION_STATUS_PROPERTY and config.NOTION_STATUS_EDITING:
            _patch_page(page_id, {
                config.NOTION_STATUS_PROPERTY: {"status": {"name": config.NOTION_STATUS_EDITING}}
            })
            log(f"notion: '{name}' matched — status set to '{config.NOTION_STATUS_EDITING}'")
        else:
            log(f"notion: '{name}' matched (status property not mapped yet)")
    except Exception as e:
        log(f"notion: mark_editing failed ({e})")


def attach_video(name: str, video_url: str, log=lambda m: None):
    """On finish: write the finished-video link onto the matched card + mark ready."""
    if not config.notion_configured():
        return
    try:
        page_id = find_page(name)
        if not page_id:
            log(f"notion: no CPS card titled '{name}' to attach the video to — skipping")
            return
        props: dict = {}
        if config.NOTION_VIDEO_PROPERTY and video_url:
            props[config.NOTION_VIDEO_PROPERTY] = {"url": video_url}
        if config.NOTION_STATUS_PROPERTY and config.NOTION_STATUS_READY:
            props[config.NOTION_STATUS_PROPERTY] = {"status": {"name": config.NOTION_STATUS_READY}}
        if props:
            _patch_page(page_id, props)
        # Also drop the link into the page body as a bookmark so it's visible/clickable.
        if video_url:
            requests.patch(f"{API}/blocks/{page_id}/children", headers=_headers(),
                           json={"children": [{"object": "block", "type": "bookmark",
                                               "bookmark": {"url": video_url}}]}, timeout=20)
        log(f"notion: attached finished video to '{name}'")
    except Exception as e:
        log(f"notion: attach_video failed ({e})")
