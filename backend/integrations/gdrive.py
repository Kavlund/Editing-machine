"""Google Drive integration — upload the finished cut to the client's Drive and
return a shareable link (which then gets attached to the Notion CPS card).

Uses a service account so it runs unattended on the server. The client shares the
target Drive folder with the service account's email on the setup call.

Requires: google-api-python-client, google-auth  (see requirements.txt).
Imports are guarded so the app still boots if the libs aren't installed yet.
"""
from __future__ import annotations
import json
from pathlib import Path

from . import config

_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _service():
    """Build an authenticated Drive service, or None if libs/creds are missing."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        return None

    if config.GOOGLE_SERVICE_ACCOUNT_FILE and Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).exists():
        creds = service_account.Credentials.from_service_account_file(
            config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
    elif config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        creds = service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    else:
        return None

    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_or_create_folder(svc, name: str, parent_id: str) -> str:
    """Return the id of the subfolder `name` under `parent_id`, creating it if absent."""
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = (f"name = '{safe}' and '{parent_id}' in parents and "
         f"mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    res = svc.files().list(q=q, spaces="drive", fields="files(id, name)",
                           pageSize=1).execute()
    hits = res.get("files", [])
    if hits:
        return hits[0]["id"]
    created = svc.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id").execute()
    return created["id"]


def _resolve_target_folder(svc, client_name: str, log) -> str | None:
    """Where the finished cut should land.
      - root configured -> "<root>/<client>/<Edited>/" (auto-created), isolated per client
      - else finished folder -> that flat folder
    """
    if config.GDRIVE_ROOT_FOLDER_ID:
        client = (client_name or "Unsorted").strip() or "Unsorted"
        client_folder = _find_or_create_folder(svc, client, config.GDRIVE_ROOT_FOLDER_ID)
        edited = _find_or_create_folder(svc, config.GDRIVE_EDITED_SUBFOLDER, client_folder)
        return edited
    if config.GDRIVE_FINISHED_FOLDER_ID:
        return config.GDRIVE_FINISHED_FOLDER_ID
    return None


def provision_client_folder(client_name: str, log=lambda m: None) -> str | None:
    """Create '<root>/<Client>/<Edited>/' the moment a client is added, so their
    Drive folder exists up front (not only after the first render). No-op / safe
    when Drive isn't configured. Returns the client folder id, or None."""
    if not config.gdrive_configured() or not config.GDRIVE_ROOT_FOLDER_ID:
        return None
    try:
        from googleapiclient.discovery import build  # noqa: F401  (ensure libs present)
    except ImportError:
        log("gdrive: google-api-python-client not installed — cannot provision folder")
        return None
    try:
        svc = _service()
        if svc is None:
            return None
        client = (client_name or "Unsorted").strip() or "Unsorted"
        client_folder = _find_or_create_folder(svc, client, config.GDRIVE_ROOT_FOLDER_ID)
        _find_or_create_folder(svc, config.GDRIVE_EDITED_SUBFOLDER, client_folder)
        log(f"gdrive: provisioned Drive folder '{client}/{config.GDRIVE_EDITED_SUBFOLDER}'")
        return client_folder
    except Exception as e:
        log(f"gdrive: could not provision folder for '{client_name}' ({e})")
        return None


def upload_video(local_path: Path, display_name: str, client_name: str = "",
                 log=lambda m: None) -> str | None:
    """Upload a finished video into the client's Edited/ folder. Returns a shareable
    webViewLink, or None on any failure (never raises)."""
    if not config.gdrive_configured():
        return None
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        log("gdrive: google-api-python-client not installed — run pip install")
        return None

    try:
        svc = _service()
        if svc is None:
            log("gdrive: service account not available — check credentials")
            return None

        target_folder = _resolve_target_folder(svc, client_name, log)
        if not target_folder:
            log("gdrive: no destination folder resolved — check GDRIVE_ROOT_FOLDER_ID")
            return None

        filename = f"{display_name}.mp4" if not display_name.lower().endswith(".mp4") else display_name
        meta = {"name": filename, "parents": [target_folder]}
        media = MediaFileUpload(str(local_path), mimetype="video/mp4", resumable=True)
        created = svc.files().create(body=meta, media_body=media,
                                     fields="id, webViewLink").execute()
        file_id = created["id"]

        if config.GDRIVE_SHARE_ANYONE:
            try:
                svc.permissions().create(
                    fileId=file_id,
                    body={"role": "reader", "type": "anyone"},
                    fields="id",
                ).execute()
            except Exception as e:
                log(f"gdrive: could not set link-sharing ({e}) — file uploaded but private")

        link = created.get("webViewLink") or f"https://drive.google.com/file/d/{file_id}/view"
        where = f"{client_name}/{config.GDRIVE_EDITED_SUBFOLDER}" if config.GDRIVE_ROOT_FOLDER_ID else "finished folder"
        log(f"gdrive: uploaded '{filename}' to {where} -> {link}")
        return link
    except Exception as e:
        log(f"gdrive: upload failed ({e})")
        return None
