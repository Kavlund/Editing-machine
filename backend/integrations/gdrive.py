"""Google Drive integration — upload the finished cut to the client's Drive and
return a shareable link (which then gets attached to the Notion CPS card).

Uses a service account so it runs unattended on the server. The client shares the
target Drive folder with the service account's email on the setup call.

Requires: google-api-python-client, google-auth  (see requirements.txt).
Imports are guarded so the app still boots if the libs aren't installed yet.
"""
from __future__ import annotations
import os
import json
from pathlib import Path

from . import config

_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _oauth_credentials(log=lambda m: None):
    """User credentials from the stored Google sign-in (Option A). Returns None if
    no token is stored or the login has been revoked. Refreshes and re-saves the
    access token when it has simply expired."""
    if not config.gdrive_oauth_available():
        return None
    if not os.path.exists(config.GDRIVE_OAUTH_TOKEN_FILE):
        return None
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None
    try:
        creds = Credentials.from_authorized_user_file(config.GDRIVE_OAUTH_TOKEN_FILE, _SCOPES)
    except Exception as e:
        log(f"gdrive: stored Google login is unreadable ({e}) — reconnect on the Setup page")
        return None
    try:
        if not creds.valid and creds.refresh_token:
            creds.refresh(Request())
            try:
                with open(config.GDRIVE_OAUTH_TOKEN_FILE, "w") as f:
                    f.write(creds.to_json())
            except Exception:
                pass  # refresh still usable for this run even if we couldn't persist it
    except Exception as e:
        log(f"gdrive: Google login expired ({e}) — reconnect on the Setup page")
        return None
    return creds if creds.valid else None


def _service_account_credentials():
    """Service-account credentials (the alternative to a user sign-in)."""
    try:
        from google.oauth2 import service_account
    except ImportError:
        return None
    if config.GOOGLE_SERVICE_ACCOUNT_FILE and Path(config.GOOGLE_SERVICE_ACCOUNT_FILE).exists():
        return service_account.Credentials.from_service_account_file(
            config.GOOGLE_SERVICE_ACCOUNT_FILE, scopes=_SCOPES)
    if config.GOOGLE_SERVICE_ACCOUNT_JSON:
        info = json.loads(config.GOOGLE_SERVICE_ACCOUNT_JSON)
        return service_account.Credentials.from_service_account_info(info, scopes=_SCOPES)
    return None


def _service(log=lambda m: None):
    """Authenticated Drive service. Prefers the user's own Google sign-in (Option A,
    OAuth) and falls back to a service account. None if neither is available."""
    try:
        from googleapiclient.discovery import build
    except ImportError:
        return None
    creds = _oauth_credentials(log) or _service_account_credentials()
    if creds is None:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_or_create_root_by_name(svc, name: str, log) -> str | None:
    """Find (or create) a top-level folder called `name` in the user's My Drive.
    Used with the user sign-in (Option A) so no folder ID is pasted anywhere."""
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = (f"name = '{safe}' and 'root' in parents and "
         f"mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    try:
        res = svc.files().list(q=q, spaces="drive", fields="files(id, name)", pageSize=1,
                               supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
        hits = res.get("files", [])
        if hits:
            return hits[0]["id"]
        created = svc.files().create(
            body={"name": name, "mimeType": "application/vnd.google-apps.folder"},
            fields="id", supportsAllDrives=True).execute()
        log(f"gdrive: created root folder '{name}' in your Drive")
        return created["id"]
    except Exception as e:
        log(f"gdrive: could not resolve root folder '{name}' ({e})")
        return None


def _resolve_root(svc, log) -> str | None:
    """The one root folder everything nests under. A pasted folder ID wins;
    otherwise, when signed in as the user, resolve/create it by name."""
    if config.GDRIVE_ROOT_FOLDER_ID:
        return config.GDRIVE_ROOT_FOLDER_ID
    if config.gdrive_oauth_ready():
        return _find_or_create_root_by_name(svc, config.GDRIVE_ROOT_FOLDER_NAME, log)
    return None


def _find_or_create_folder(svc, name: str, parent_id: str) -> str:
    """Return the id of the subfolder `name` under `parent_id`, creating it if absent."""
    safe = name.replace("\\", "\\\\").replace("'", "\\'")
    q = (f"name = '{safe}' and '{parent_id}' in parents and "
         f"mimeType = 'application/vnd.google-apps.folder' and trashed = false")
    res = svc.files().list(q=q, spaces="drive", fields="files(id, name)",
                           pageSize=1,
                           supportsAllDrives=True,
                           includeItemsFromAllDrives=True).execute()
    hits = res.get("files", [])
    if hits:
        return hits[0]["id"]
    created = svc.files().create(
        body={"name": name, "mimeType": "application/vnd.google-apps.folder",
              "parents": [parent_id]},
        fields="id", supportsAllDrives=True).execute()
    return created["id"]


def _resolve_target_folder(svc, client_name: str, log) -> str | None:
    """Where the finished cut should land.
      - root resolved -> "<root>/<client>/<Edited>/" (auto-created), isolated per client
      - else finished folder -> that flat folder
    """
    root = _resolve_root(svc, log)
    if root:
        client = (client_name or "Unsorted").strip() or "Unsorted"
        client_folder = _find_or_create_folder(svc, client, root)
        edited = _find_or_create_folder(svc, config.GDRIVE_EDITED_SUBFOLDER, client_folder)
        return edited
    if config.GDRIVE_FINISHED_FOLDER_ID:
        return config.GDRIVE_FINISHED_FOLDER_ID
    return None


def provision_client_folder(client_name: str, log=lambda m: None) -> str | None:
    """Create '<root>/<Client>/<Edited>/' the moment a client is added, so their
    Drive folder exists up front (not only after the first render). No-op / safe
    when Drive isn't configured. Returns the client folder id, or None."""
    if not config.gdrive_configured():
        return None
    try:
        from googleapiclient.discovery import build  # noqa: F401  (ensure libs present)
    except ImportError:
        log("gdrive: google-api-python-client not installed — cannot provision folder")
        return None
    try:
        svc = _service(log)
        if svc is None:
            return None
        root = _resolve_root(svc, log)
        if not root:
            return None
        client = (client_name or "Unsorted").strip() or "Unsorted"
        client_folder = _find_or_create_folder(svc, client, root)
        _find_or_create_folder(svc, config.GDRIVE_EDITED_SUBFOLDER, client_folder)
        _find_or_create_folder(svc, config.GDRIVE_BROLL_SUBFOLDER, client_folder)
        _find_or_create_folder(svc, config.GDRIVE_SOURCE_SUBFOLDER, client_folder)
        log(f"gdrive: provisioned Drive folders for '{client}' (Edited, B-roll, Source)")
        return client_folder
    except Exception as e:
        log(f"gdrive: could not provision folder for '{client_name}' ({e})")
        return None


def check_connection(log=lambda m: None) -> dict:
    """Actually call Drive to verify the stored sign-in still works — a token file
    existing proves nothing. Returns {"ok": bool, "email": str, "error": str}.
    Never raises."""
    if not config.gdrive_configured():
        return {"ok": False, "email": "", "error": "Drive is not set up yet"}
    try:
        svc = _service(log)
        if svc is None:
            return {"ok": False, "email": "",
                    "error": "the saved Google sign-in is no longer valid"}
        about = svc.about().get(fields="user(emailAddress,displayName)").execute()
        user = (about or {}).get("user") or {}
        return {"ok": True, "email": user.get("emailAddress", ""), "error": ""}
    except Exception as e:
        return {"ok": False, "email": "", "error": str(e)[:200]}


def _resolve_broll_folder(svc, client_name: str, log):
    """The client's B-roll folder in Drive: <root>/<Client>/<B-roll>/. None if Drive
    has no resolvable root."""
    root = _resolve_root(svc, log)
    if not root:
        return None
    client = (client_name or "Unsorted").strip() or "Unsorted"
    client_folder = _find_or_create_folder(svc, client, root)
    return _find_or_create_folder(svc, config.GDRIVE_BROLL_SUBFOLDER, client_folder)


def _rfc3339_to_epoch(s):
    """Parse a Drive modifiedTime (e.g. '2026-08-07T17:13:10.123Z') to epoch secs."""
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


_BROLL_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}


def download_broll(client_name: str, dest_dir: Path, log=lambda m: None) -> int:
    """Download the client's B-roll clips from their Drive B-roll folder into
    dest_dir. Each file's mtime is set to the Drive modifiedTime so the vision-tag
    cache stays stable across re-downloads (a clip is analysed once, ever). Returns
    the number of clips in dest_dir. No-op / safe when Drive isn't set up."""
    if not config.gdrive_configured():
        return 0
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        return 0
    try:
        svc = _service(log)
        if svc is None:
            return 0
        folder_id = _resolve_broll_folder(svc, client_name, log)
        if not folder_id:
            return 0

        files, page_token = [], None
        q = (f"'{folder_id}' in parents and trashed = false and "
             f"mimeType != 'application/vnd.google-apps.folder'")
        while True:
            res = svc.files().list(
                q=q, spaces="drive",
                fields="nextPageToken, files(id, name, size, modifiedTime)",
                pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True,
                pageToken=page_token).execute()
            files.extend(res.get("files", []))
            page_token = res.get("nextPageToken")
            if not page_token:
                break

        dest_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in files:
            name = f.get("name", "")
            if Path(name).suffix.lower() not in _BROLL_EXTS:
                continue
            local = dest_dir / name
            size  = str(f.get("size", ""))
            try:  # skip if we already have an identical copy in this working folder
                if size and local.exists() and str(local.stat().st_size) == size:
                    count += 1
                    continue
            except Exception:
                pass
            try:
                import io
                req = svc.files().get_media(fileId=f["id"], supportsAllDrives=True)
                with io.FileIO(str(local), "wb") as buf:
                    downloader = MediaIoBaseDownload(buf, req)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                mt = _rfc3339_to_epoch(f.get("modifiedTime"))
                if mt:
                    os.utime(local, (mt, mt))
                count += 1
                log(f"gdrive: pulled B-roll '{name}'")
            except Exception as e:
                log(f"gdrive: could not download B-roll '{name}' ({e})")
        return count
    except Exception as e:
        log(f"gdrive: B-roll pull failed ({e})")
        return 0


_SOURCE_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".mxf", ".webm", ".mts", ".m2ts"}


def _resolve_source_folder(svc, client_name: str, log):
    """<root>/<Client>/<Source>/ — where raw footage lives in Drive."""
    root = _resolve_root(svc, log)
    if not root:
        return None
    client = (client_name or "Unsorted").strip() or "Unsorted"
    client_folder = _find_or_create_folder(svc, client, root)
    return _find_or_create_folder(svc, config.GDRIVE_SOURCE_SUBFOLDER, client_folder)


def upload_source(client_name: str, local_path: Path, display_name: str = "", log=lambda m: None):
    """Upload a raw source clip into the client's Drive Source folder. Returns
    {"id","name","size"} on success, or None. Never raises."""
    if not config.gdrive_configured():
        return None
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        return None
    try:
        svc = _service(log)
        if svc is None:
            return None
        folder_id = _resolve_source_folder(svc, client_name, log)
        if not folder_id:
            return None
        name = display_name or Path(local_path).name
        media = MediaFileUpload(str(local_path), resumable=True)
        created = svc.files().create(
            body={"name": name, "parents": [folder_id]},
            media_body=media, fields="id, name, size",
            supportsAllDrives=True).execute()
        log(f"gdrive: uploaded source '{name}' to {client_name}/{config.GDRIVE_SOURCE_SUBFOLDER}")
        return {"id": created["id"], "name": created.get("name", name), "size": created.get("size")}
    except Exception as e:
        log(f"gdrive: source upload failed ({e})")
        return None


def download_file(file_id: str, dest_path: Path, log=lambda m: None) -> bool:
    """Download a Drive file by id to dest_path. Returns True on success."""
    if not config.gdrive_configured() or not file_id:
        return False
    try:
        from googleapiclient.http import MediaIoBaseDownload
    except ImportError:
        return False
    try:
        svc = _service(log)
        if svc is None:
            return False
        import io
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        req = svc.files().get_media(fileId=file_id, supportsAllDrives=True)
        with io.FileIO(str(dest_path), "wb") as buf:
            downloader = MediaIoBaseDownload(buf, req)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        return True
    except Exception as e:
        log(f"gdrive: download of {file_id} failed ({e})")
        return False


def list_source(client_name: str, log=lambda m: None) -> list:
    """List raw clips in the client's Drive Source folder. Returns
    [{"id","name","size","modifiedTime"}]. Safe [] if unset."""
    if not config.gdrive_configured():
        return []
    try:
        svc = _service(log)
        if svc is None:
            return []
        folder_id = _resolve_source_folder(svc, client_name, log)
        if not folder_id:
            return []
        out, page_token = [], None
        q = (f"'{folder_id}' in parents and trashed = false and "
             f"mimeType != 'application/vnd.google-apps.folder'")
        while True:
            res = svc.files().list(
                q=q, spaces="drive",
                fields="nextPageToken, files(id, name, size, modifiedTime)",
                pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True,
                pageToken=page_token).execute()
            for f in res.get("files", []):
                if Path(f.get("name", "")).suffix.lower() in _SOURCE_EXTS:
                    out.append(f)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return out
    except Exception as e:
        log(f"gdrive: could not list source ({e})")
        return []


def list_broll(client_name: str, log=lambda m: None) -> list:
    """List the client's B-roll clips in their Drive folder — metadata only, no
    download. Returns [{"name","id","size","modifiedTime"}]. Safe [] if unset."""
    if not config.gdrive_configured():
        return []
    try:
        svc = _service(log)
        if svc is None:
            return []
        folder_id = _resolve_broll_folder(svc, client_name, log)
        if not folder_id:
            return []
        out, page_token = [], None
        q = (f"'{folder_id}' in parents and trashed = false and "
             f"mimeType != 'application/vnd.google-apps.folder'")
        while True:
            res = svc.files().list(
                q=q, spaces="drive",
                fields="nextPageToken, files(id, name, size, modifiedTime)",
                pageSize=100, supportsAllDrives=True, includeItemsFromAllDrives=True,
                pageToken=page_token).execute()
            for f in res.get("files", []):
                if Path(f.get("name", "")).suffix.lower() in _BROLL_EXTS:
                    out.append(f)
            page_token = res.get("nextPageToken")
            if not page_token:
                break
        return out
    except Exception as e:
        log(f"gdrive: could not list B-roll ({e})")
        return []


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
        svc = _service(log)
        if svc is None:
            log("gdrive: not connected — sign in on the Setup page (or check the service account)")
            return None

        target_folder = _resolve_target_folder(svc, client_name, log)
        if not target_folder:
            log("gdrive: no destination folder resolved — check GDRIVE_ROOT_FOLDER_ID")
            return None

        filename = f"{display_name}.mp4" if not display_name.lower().endswith(".mp4") else display_name
        meta = {"name": filename, "parents": [target_folder]}
        media = MediaFileUpload(str(local_path), mimetype="video/mp4", resumable=True)
        created = svc.files().create(body=meta, media_body=media,
                                     fields="id, webViewLink",
                                     supportsAllDrives=True).execute()
        file_id = created["id"]

        if config.GDRIVE_SHARE_ANYONE:
            try:
                svc.permissions().create(
                    fileId=file_id,
                    body={"role": "reader", "type": "anyone"},
                    fields="id",
                    supportsAllDrives=True,
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
