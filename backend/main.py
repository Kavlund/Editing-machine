import os, sys, json, uuid, hmac, hashlib, secrets, threading, asyncio, base64, re, shutil
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Make sibling modules (pipeline.py, integrations/) importable regardless of how
# this app is launched — as "main" with cwd=backend/ (local dev) or as
# "backend.main" with cwd=project root (Docker/Railway: `uvicorn backend.main:app`).
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import aiofiles

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env", override=True)
except ImportError:
    pass

from pipeline import run_pipeline

# ── Config from environment ───────────────────────────────────────────────

DASHBOARD_PASSWORD  = os.environ.get("DASHBOARD_PASSWORD", "")
SECRET_KEY          = os.environ.get("SECRET_KEY", secrets.token_hex(32))
ELEVENLABS_API_KEY  = os.environ.get("ELEVENLABS_API_KEY", "")
ANTHROPIC_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "")

# ── White-label branding ──────────────────────────────────────────────────
# One codebase, many deployments. Everything brand-specific comes from env vars
# so the same code serves the client's instance and our own internal one — no
# fork, no drift. BRAND_LOGO points at any file in static/ (or an external URL).
BRAND_NAME = os.environ.get("BRAND_NAME", "Acquisition Empire")
BRAND_LOGO = os.environ.get("BRAND_LOGO", "/logo.png")

app = FastAPI(title="Talking Head Editor")

BASE         = Path(__file__).parent.parent
# All runtime data (clients, uploaded footage, B-roll, style refs) lives under
# DATA_ROOT. On a host with an ephemeral filesystem (e.g. Railway), point
# DATA_ROOT at a mounted persistent Volume (e.g. /data) so nothing is wiped on
# redeploy. Defaults to BASE, so local dev is unchanged.
DATA_ROOT    = Path(os.environ.get("DATA_ROOT", str(BASE)))
DATA_DIR     = DATA_ROOT / "data"
CLIENTS_FILE = DATA_DIR / "clients.json"
JOBS_DIR     = DATA_DIR / "jobs"
UPLOADS_DIR  = DATA_ROOT / "uploads"
BROLL_DIR    = DATA_ROOT / "broll_library"   # broll_library/{client_id}/*.mp4
STYLE_DIR    = DATA_ROOT / "style_refs"      # style_refs/{client_id}/*.mp4 (reference clips)

for d in [DATA_DIR, JOBS_DIR, UPLOADS_DIR, BROLL_DIR, STYLE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

if not CLIENTS_FILE.exists():
    CLIENTS_FILE.write_text("[]")


def _sweep_render_debris():
    """Delete regenerable render intermediates left in job folders by past runs —
    especially failed ones, which used to skip cleanup and piled up on the volume.
    Safe: every one of these is rebuilt on a re-render. Frees disk on boot."""
    files = ("base30.mkv", "base30_zoom.mkv", "composited30.mkv",
             "_seg_offsets.json", "_concat30.txt")
    dirs  = ("clips30", "animations")
    freed = 0
    if not UPLOADS_DIR.exists():
        return
    for job_dir in UPLOADS_DIR.iterdir():
        if not job_dir.is_dir():
            continue
        for name in files:
            p = job_dir / name
            try:
                if p.exists():
                    freed += p.stat().st_size
                    p.unlink()
            except Exception:
                pass
        for name in dirs:
            dp = job_dir / name
            try:
                if dp.is_dir():
                    for sub in dp.rglob("*"):
                        if sub.is_file():
                            try: freed += sub.stat().st_size
                            except Exception: pass
                    shutil.rmtree(dp, ignore_errors=True)
            except Exception:
                pass
    if freed:
        print(f"[startup] swept {freed/1024/1024:.0f} MB of old render intermediates from the volume", flush=True)


@app.on_event("startup")
async def recover_stuck_jobs():
    """On startup, reset any jobs that were mid-pipeline — the thread is dead, they'd be stuck forever."""
    for f in sorted(JOBS_DIR.glob("*.json")):
        try:
            job = json.loads(f.read_text())
            if job.get("status") in _RUNNING_STATUSES:
                job["status"] = "failed"
                job.setdefault("log", []).append({
                    "time": datetime.now().isoformat(),
                    "msg":  "ERROR: Server restarted while this job was running — click Retry to re-run",
                })
                f.write_text(json.dumps(job, indent=2))
        except Exception:
            pass
    try:
        _sweep_render_debris()
    except Exception as e:
        print(f"[startup] debris sweep skipped: {e}", flush=True)


# ── Auth ──────────────────────────────────────────────────────────────────

def _session_token() -> str:
    return hmac.new(SECRET_KEY.encode(), b"session-valid", hashlib.sha256).hexdigest()


def _is_authenticated(request: Request) -> bool:
    if not DASHBOARD_PASSWORD:
        return True  # open in dev when no password is set
    cookie = request.cookies.get("session", "")
    return hmac.compare_digest(cookie, _session_token())


_PUBLIC_PATHS = {"/login", "/api/auth/login", "/logo.png", "/logo-original.png", "/favicon.ico"}
# The branded logo shows on the login page, before auth. BRAND_LOGO is meant to
# be set per-instance as a data: URI (see .env.example) so a brand's logo is a
# config VALUE, never a file committed to this shared repo. A data: URI needs no
# server request at all, so it works pre-auth automatically. If an instance ever
# points BRAND_LOGO at a local path instead, allow that path through too.
if BRAND_LOGO.startswith("/"):
    _PUBLIC_PATHS.add(BRAND_LOGO)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    if request.url.path in _PUBLIC_PATHS:
        return await call_next(request)

    if not _is_authenticated(request):
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "Unauthorized"}, status_code=401)
        return RedirectResponse("/login", status_code=302)

    return await call_next(request)


def _render_page(filename: str) -> HTMLResponse:
    """Serve a page with the brand substituted in. The static mount can't
    template, so every brand-bearing page is served through here instead."""
    html = (BASE / "static" / filename).read_text()
    html = html.replace("__BRAND_NAME__", BRAND_NAME).replace("__BRAND_LOGO__", BRAND_LOGO)
    return HTMLResponse(html)


@app.get("/login")
def login_page():
    return _render_page("login.html")


# These must stay ABOVE the StaticFiles mount at the bottom of this file, or the
# mount would serve the raw, un-branded files instead.
@app.get("/")
def index_page():
    return _render_page("index.html")


@app.get("/index.html")
def index_page_alias():
    return _render_page("index.html")


@app.get("/setup.html")
def setup_page():
    return _render_page("setup.html")


@app.get("/api/brand")
def brand_info():
    return {"name": BRAND_NAME, "logo": BRAND_LOGO}


@app.post("/api/auth/login")
async def do_login(request: Request):
    body = await request.json()
    if not DASHBOARD_PASSWORD:
        response = JSONResponse({"ok": True})
        return response
    if body.get("password") != DASHBOARD_PASSWORD:
        raise HTTPException(401, "Invalid password")
    response = JSONResponse({"ok": True})
    response.set_cookie(
        "session", _session_token(),
        httponly=True, samesite="lax",
        max_age=86400 * 30,
        secure=os.environ.get("HTTPS", "") == "1",
    )
    return response


@app.post("/api/auth/logout")
def do_logout():
    response = JSONResponse({"ok": True})
    response.delete_cookie("session")
    return response


# ── Clients ────────────────────────────────────────────────────────────────

def load_clients() -> list:
    return json.loads(CLIENTS_FILE.read_text())


def save_clients(clients: list):
    CLIENTS_FILE.write_text(json.dumps(clients, indent=2))


def get_client(client_id: str) -> Optional[dict]:
    return next((c for c in load_clients() if c["id"] == client_id), None)


@app.get("/api/clients")
def list_clients():
    return load_clients()


@app.post("/api/clients")
async def create_client(request: Request):
    body = await request.json()
    if not body.get("name", "").strip():
        raise HTTPException(400, "name is required")

    editing = body.get("editing", {})
    brand   = body.get("brand", {})

    client = {
        "id":         str(uuid.uuid4()),
        "name":       body["name"].strip(),
        "created_at": datetime.now().isoformat(),
        "niche":      body.get("niche", "").strip(),
        "tone":       body.get("tone", []),
        "icp":        body.get("icp", "").strip(),
        "cta_text":   body.get("cta_text", "").strip(),
        # Highest-priority hard rules the AI must always obey for this client
        "specific_instructions": body.get("specific_instructions", "").strip(),
        # Rich onboarding data (from the onboarding-doc reader)
        "words_favor":           body.get("words_favor", []),
        "words_avoid":           body.get("words_avoid", []),
        "brand_characteristics": body.get("brand_characteristics", []),
        "inspiration_urls":      body.get("inspiration_urls", []),
        "core_philosophy":       body.get("core_philosophy", "").strip(),
        "brand": {
            "primary_color": brand.get("primary_color", "#ffffff"),
            "accent_color":  brand.get("accent_color",  "#6366f1"),
            "font":          brand.get("font", ""),
        },
        "editing": {
            "language":          editing.get("language", "auto"),   # auto-detect DA/EN/etc per video
            "num_speakers":      int(editing.get("num_speakers", 2)),
            "grade":             editing.get("grade",
                "colorlevels=rimax=0.92:gimax=0.92:bimax=0.88,"
                "eq=saturation=1.0:contrast=1.02,"
                "unsharp=5:5:0.3:5:5:0.0"),
            "caption_font_size": int(editing.get("caption_font_size", 60)),
            "caption_y":         int(editing.get("caption_y", 1300)),
            "caption_max_width": int(editing.get("caption_max_width", 960)),
            "caption_color":     editing.get("caption_color", "#ffffff"),
            "caption_speaker":   editing.get("caption_speaker", "speaker_0"),
            "title":             editing.get("title", None),
        },
    }
    clients = load_clients()
    clients.append(client)
    save_clients(clients)

    # Provision this client's Google Drive folder up front (best-effort, inert until Drive is set up)
    try:
        from integrations import delivery as _delivery
        if _delivery.is_active():
            await asyncio.to_thread(_delivery.on_client_created, client["name"],
                                    lambda m: print(f"[integrations] {m}", flush=True))
    except Exception as e:
        print(f"[integrations] client folder provisioning skipped: {e}", flush=True)

    return client


@app.put("/api/clients/{client_id}")
async def update_client(client_id: str, request: Request):
    body = await request.json()
    clients = load_clients()
    for i, c in enumerate(clients):
        if c["id"] == client_id:
            if "name"     in body: clients[i]["name"]     = body["name"].strip()
            if "niche"    in body: clients[i]["niche"]    = body["niche"].strip()
            if "tone"     in body: clients[i]["tone"]     = body["tone"]
            if "icp"      in body: clients[i]["icp"]      = body["icp"].strip()
            if "cta_text" in body: clients[i]["cta_text"] = body["cta_text"].strip()
            if "specific_instructions" in body: clients[i]["specific_instructions"] = body["specific_instructions"].strip()
            for k in ("words_favor", "words_avoid", "brand_characteristics", "inspiration_urls"):
                if k in body: clients[i][k] = body[k]
            if "core_philosophy" in body: clients[i]["core_philosophy"] = body["core_philosophy"].strip()
            if "brand"    in body: clients[i].setdefault("brand", {}).update(body["brand"])
            if "editing"  in body: clients[i]["editing"].update(body["editing"])
            save_clients(clients)
            return clients[i]
    raise HTTPException(404, "Client not found")


@app.delete("/api/clients/{client_id}")
def delete_client(client_id: str):
    save_clients([c for c in load_clients() if c["id"] != client_id])
    return {"ok": True}


# ── B-roll library ────────────────────────────────────────────────────────

BROLL_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
BROLL_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"} | BROLL_IMAGE_EXTS


def _client_broll_dir(client_id: str) -> Path:
    """Resolve a client's B-roll folder, rejecting unknown ids and any path
    traversal (e.g. a URL-encoded '..'). client_id must be a real client, and
    the resolved folder must sit directly under BROLL_DIR."""
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    folder = (BROLL_DIR / client_id).resolve()
    if folder.parent != BROLL_DIR.resolve():
        raise HTTPException(400, "Invalid client id")
    return folder


@app.get("/api/clients/{client_id}/broll")
def list_broll(client_id: str):
    folder = _client_broll_dir(client_id)
    folder.mkdir(exist_ok=True)
    files = [f for f in sorted(folder.iterdir())
             if f.is_file() and f.suffix.lower() in BROLL_EXTS]
    from pipeline import read_broll_tags
    tags = read_broll_tags(folder, files)
    return [
        {"name": f.name, "size": f.stat().st_size,
         "url": f"/api/clients/{client_id}/broll/{f.name}",
         "tag": tags.get(f.name)}
        for f in files
    ]

@app.post("/api/clients/{client_id}/broll")
async def upload_broll(client_id: str, file: UploadFile = File(...)):
    folder = _client_broll_dir(client_id)
    folder.mkdir(exist_ok=True)
    safe_name = Path(file.filename).name  # strip any directory components
    if not safe_name:
        raise HTTPException(400, "Invalid filename")
    # Only accept recognised video/image files (also blocks writing e.g. ".env" / ".py")
    if Path(safe_name).suffix.lower() not in BROLL_EXTS:
        raise HTTPException(400, "Only video or image files are allowed")
    dest = folder / safe_name
    async with aiofiles.open(dest, "wb") as f:
        await f.write(await file.read())

    # Tag the clip with vision right away so the UI can show what the AI sees.
    # Best-effort: a tagging failure must never fail the upload.
    tag = None
    if ANTHROPIC_API_KEY:
        try:
            from pipeline import tag_broll_clips
            tags = await asyncio.to_thread(
                tag_broll_clips, folder, [dest], ANTHROPIC_API_KEY, lambda m: None)
            tag = tags.get(safe_name)
        except Exception:
            tag = None
    return {"name": safe_name, "size": dest.stat().st_size, "tag": tag}

@app.delete("/api/clients/{client_id}/broll/{filename}")
def delete_broll(client_id: str, filename: str):
    broll_dir = _client_broll_dir(client_id)
    # Strip directory components before joining to prevent traversal
    safe_name = Path(filename).name
    path = (broll_dir / safe_name).resolve()
    if path.parent != broll_dir:
        raise HTTPException(400, "Invalid filename")
    if path.suffix.lower() not in BROLL_EXTS:
        raise HTTPException(400, "Invalid file")
    if not path.exists():
        raise HTTPException(404, "File not found")
    path.unlink()
    return {"ok": True}


# ── Upload ────────────────────────────────────────────────────────────────

@app.post("/api/upload")
async def upload_footage(
    client_id:   str              = Form(...),
    folder_name: str              = Form("untitled"),
    notes:       str              = Form(""),
    files:       List[UploadFile] = File(...),
):
    client = get_client(client_id)
    if not client:
        raise HTTPException(404, "Client not found")

    # Save the uploaded footage to the volume. Simple and reliable — no dependency
    # on Drive being connected. (The Drive-native path is the separate "Pull from
    # Drive" picker, which only appears once Drive is connected.)
    job_id  = str(uuid.uuid4())
    job_dir = UPLOADS_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    saved, total_bytes = [], 0
    for f in files:
        safe_path = Path(f.filename).as_posix().lstrip("/")
        dest = job_dir / safe_path
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(dest, "wb") as out:
            while chunk := await f.read(1024 * 1024):
                await out.write(chunk)
        size = dest.stat().st_size
        total_bytes += size
        saved.append({"path": safe_path, "size": size})

    job = {
        "id":              job_id,
        "client_id":       client_id,
        "client_name":     client["name"],
        "folder_name":     folder_name,
        "notes":           notes,
        "status":          "uploaded",
        "created_at":      datetime.now().isoformat(),
        "files":           saved,
        "total_bytes":     total_bytes,
        "upload_dir":      str(job_dir),
        "client_snapshot": client,
        "elevenlabs_key":  ELEVENLABS_API_KEY,  # passed through to the editor
    }
    (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(job, indent=2))

    # Match this upload to its CPS script card and mark it in-progress (best-effort,
    # inert until the client's Notion credentials are configured).
    try:
        from integrations import delivery as _delivery
        if _delivery.is_active():
            await asyncio.to_thread(_delivery.on_upload, folder_name, lambda m: print(f"[integrations] {m}", flush=True))
    except Exception as e:
        print(f"[integrations] on_upload skipped: {e}", flush=True)

    return job


@app.get("/api/clients/{client_id}/drive-source")
def list_drive_source(client_id: str):
    """Raw clips in the client's Drive Source folder — powers the Pull from Drive picker."""
    c = get_client(client_id)
    if not c:
        raise HTTPException(404, "Client not found")
    try:
        from integrations import config as _icfg, gdrive as _gdrive
        if not _icfg.gdrive_configured():
            return {"available": False, "clips": []}
        clips = _gdrive.list_source(c["name"], log=lambda m: print(f"[drive-source] {m}", flush=True))
        return {"available": True, "clips": [
            {"id": f["id"], "name": f.get("name", ""), "size": int(f.get("size") or 0)} for f in clips]}
    except Exception as e:
        return {"available": False, "clips": [], "error": str(e)}


@app.post("/api/jobs/from-drive")
async def create_job_from_drive(request: Request):
    """Create a job whose source footage is clips already sitting in the client's
    Drive Source folder — no upload needed."""
    body = await request.json()
    c = get_client(body.get("client_id", ""))
    if not c:
        raise HTTPException(404, "Client not found")
    selected = body.get("clips") or []
    source_drive = [{"id": s["id"], "name": s.get("name") or f"{s['id']}.mp4",
                     "size": int(s.get("size") or 0)} for s in selected if s.get("id")]
    if not source_drive:
        raise HTTPException(400, "No Drive clips selected")

    job_id = str(uuid.uuid4())
    job = {
        "id":              job_id,
        "client_id":       c["id"],
        "client_name":     c["name"],
        "folder_name":     (body.get("folder_name") or "untitled").strip() or "untitled",
        "notes":           (body.get("notes") or "").strip(),
        "status":          "uploaded",
        "created_at":      datetime.now().isoformat(),
        "files":           [{"path": s["name"], "size": s["size"]} for s in source_drive],
        "source_drive":    source_drive,
        "total_bytes":     sum(s["size"] for s in source_drive),
        "upload_dir":      str(UPLOADS_DIR / job_id),
        "client_snapshot": c,
        "elevenlabs_key":  ELEVENLABS_API_KEY,
    }
    (JOBS_DIR / f"{job_id}.json").write_text(json.dumps(job, indent=2))
    try:
        from integrations import delivery as _delivery
        if _delivery.is_active():
            await asyncio.to_thread(_delivery.on_upload, job["folder_name"], lambda m: print(f"[integrations] {m}", flush=True))
    except Exception as e:
        print(f"[integrations] on_upload skipped: {e}", flush=True)
    return job


# ── Jobs ──────────────────────────────────────────────────────────────────

@app.get("/api/jobs")
def list_jobs():
    jobs = []
    for f in sorted(JOBS_DIR.glob("*.json"), reverse=True)[:20]:
        try:
            j = json.loads(f.read_text())
        except Exception as e:
            # A half-written or corrupt job file (e.g. the container died mid-write)
            # must never take down the whole jobs list.
            print(f"[jobs] skipping unreadable {f.name}: {e}", flush=True)
            continue
        j.pop("elevenlabs_key", None)  # never expose keys in list response
        jobs.append(j)
    return jobs


@app.post("/api/jobs/clear")
async def clear_jobs(request: Request):
    """Bulk-delete jobs by status (e.g. every failed one) and their files. A job
    that is still running is never touched. Corrupt/half-written job files get
    cleared too, since those are exactly the junk this is for."""
    body = await request.json()
    statuses = set(body.get("statuses") or ["failed", "cancelled"])
    uploads_root = str(UPLOADS_DIR.resolve())
    deleted = freed = 0
    for f in list(JOBS_DIR.glob("*.json")):
        try:
            j = json.loads(f.read_text())
        except Exception:
            try:
                f.unlink(); deleted += 1      # unreadable job file — clear it
            except Exception:
                pass
            continue
        if j.get("status") in _RUNNING_STATUSES or j.get("status") not in statuses:
            continue
        jid = j.get("id") or f.stem
        d = (UPLOADS_DIR / jid).resolve()
        try:
            if d.is_dir() and str(d).startswith(uploads_root + os.sep):
                freed += _dir_size(d)
                shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
        try:
            f.unlink(); deleted += 1
        except Exception:
            pass
    return {"ok": True, "deleted": deleted, "freed_mb": round(freed / 1e6)}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    """Delete one job and its files. Refuses while it is still running."""
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    try:
        j = json.loads(path.read_text())
        if j.get("status") in _RUNNING_STATUSES:
            raise HTTPException(409, "That job is still running — stop it first")
    except HTTPException:
        raise
    except Exception:
        pass  # corrupt job file — deleting it is exactly what we want
    freed = 0
    d = (UPLOADS_DIR / job_id).resolve()
    try:
        if d.is_dir() and str(d).startswith(str(UPLOADS_DIR.resolve()) + os.sep):
            freed = _dir_size(d)
            shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
    try:
        path.unlink()
    except Exception:
        pass
    return {"ok": True, "freed_mb": round(freed / 1e6)}


_BRIEF_PROMPT = """You are analyzing a client onboarding / personal brandbook document. Extract the information and return ONLY a valid JSON object — no explanation, no markdown, just the raw JSON.

The document may follow a template with numbered parts (content foundation, conviction, story, life stories, branding, core philosophy, tone of voice, brand colors, brand inspiration). Read the whole document and pull real answers the client wrote — ignore unfilled placeholders like "Write here…".

Return exactly these fields (use empty string or empty array if not found or only a placeholder is present):
{
  "name": "brand or client name",
  "niche": "industry or niche (short phrase, e.g. Real estate coaching)",
  "tone": ["choose any that apply from: Professional, Direct, Educational, Casual, Energetic, Inspirational, Authoritative, Storytelling"],
  "icp": "ideal customer profile — who is the target audience (1-2 sentences)",
  "cta_text": "call to action text if mentioned, otherwise empty string",
  "primary_color": "hex code e.g. #1a2b3c — the primary brand color if given, else empty string",
  "accent_color": "hex code for the secondary/accent/highlight color if given, else empty string",
  "caption_color": "hex code for caption/on-screen text color if explicitly given, else the accent_color value, else empty string",
  "font": "font/typography name if the client specified one (Part 8), else empty string",
  "language": "en, da, es, fr, or de — detect the document's language; if mixed or unclear use 'auto'",
  "words_favor": ["words and phrases the client says they USE frequently / niche keywords (Part 7 'Words/Phrases I Use') — verbatim short phrases"],
  "words_avoid": ["words and phrases the client says to AVOID / never be associated with (Part 7 'Words/Phrases to Avoid') — verbatim"],
  "brand_characteristics": ["the client's brand pillars/characteristics (Part 5), each a short phrase"],
  "core_philosophy": "1-3 sentence summary of the client's unique mechanism / core philosophy (Part 6) in their own words, else empty string",
  "inspiration_urls": ["every Instagram / reel / video / carousel URL the client listed as style inspiration (Part 9 'Brand inspiration') — copy each link exactly"]
}"""


def _extract_brief(content: bytes, media_type: str) -> dict:
    try:
        import anthropic as ant
    except ImportError:
        raise HTTPException(500, "anthropic package not installed")

    sdk = ant.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0, max_retries=1)

    if media_type == "application/pdf":
        msg_content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                             "data": base64.standard_b64encode(content).decode()}},
            {"type": "text", "text": _BRIEF_PROMPT},
        ]
    elif media_type.startswith("image/"):
        msg_content = [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                          "data": base64.standard_b64encode(content).decode()}},
            {"type": "text", "text": _BRIEF_PROMPT},
        ]
    else:
        text = content.decode("utf-8", errors="ignore")
        msg_content = [{"type": "text", "text": f"Brand document:\n\n{text}\n\n---\n\n{_BRIEF_PROMPT}"}]

    try:
        resp = sdk.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=2500,   # room for inspiration URLs + word lists
            messages=[{"role": "user", "content": msg_content}],
        )
    except ant.AuthenticationError:
        raise HTTPException(400, "AI key is invalid or expired. Update ANTHROPIC_API_KEY in your .env and restart the server.")
    except Exception as e:
        raise HTTPException(500, f"AI error: {str(e)[:200]}")
    raw = resp.content[0].text.strip()
    match = re.search(r'\{.*\}', raw, re.DOTALL)
    if not match:
        raise HTTPException(500, "Could not parse brand data from document")
    return json.loads(match.group())


@app.post("/api/clients/analyze-brief")
async def analyze_brief(file: UploadFile = File(...)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY not set — add it to your .env to use this feature")

    content = await file.read()
    ext = Path(file.filename or "").suffix.lower()
    media_map = {
        ".pdf":  "application/pdf",
        ".png":  "image/png",
        ".jpg":  "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".txt":  "text/plain",
        ".md":   "text/plain",
    }
    media_type = media_map.get(ext, "text/plain")

    if ext == ".docx":
        try:
            from docx import Document
            import io
            doc = Document(io.BytesIO(content))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            content = text.encode() if text else b"[Document was empty - no text found]"
        except Exception as e:
            content = f"[DOCX parse failed: {str(e)[:200]}. Convert to PDF or plain text and re-upload.]".encode()
        media_type = "text/plain"

    result = await asyncio.to_thread(_extract_brief, content, media_type)
    return result


# ── Reference-clip style analysis ──────────────────────────────────────────

def _resp_text(resp) -> str:
    """Concatenate text blocks from an Anthropic response, skipping thinking blocks."""
    return "".join(b.text for b in resp.content
                   if getattr(b, "type", None) == "text" or hasattr(b, "text")).strip()


_STYLE_PROMPT = """These are frames sampled from a short-form video the creator likes and wants their edits to feel like. Analyze its EDITING / VISUAL STYLE (not the specific content) so another editor could match the vibe. Return ONLY strict JSON:
{
  "caption_style": "one sentence on the captions — placement, size, weight, color, animation feel (or 'none visible')",
  "color_mood": "the colour grade / mood — warm vs cool, contrast, saturation, overall feel",
  "pacing": "slow | medium | fast-cut",
  "energy": "calm | balanced | high-energy",
  "text_overlays": "hook/title/on-screen-text style if any, else 'none visible'",
  "grade_warmth": "warmer | cooler | neutral",
  "grade_contrast": "low | normal | high",
  "grade_saturation": "muted | normal | vivid",
  "caption_size": "small | medium | large",
  "summary": "2-3 sentence overall style description an editor could follow to match this look"
}"""


def _analyze_reference_style(content: bytes) -> dict:
    import tempfile, subprocess, base64
    try:
        import anthropic as ant
    except ImportError:
        raise HTTPException(500, "anthropic package not installed")

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)
        vid = tdp / "ref.mp4"
        vid.write_bytes(content)
        try:
            r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                "-of", "default=noprint_wrappers=1:nokey=1", str(vid)],
                               capture_output=True, text=True, timeout=30)
            dur = float(r.stdout.strip() or 6.0)
        except Exception:
            dur = 6.0

        frames = []
        for frac in (0.2, 0.5, 0.8):
            fp = tdp / f"f_{int(frac*100)}.jpg"
            try:
                subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", f"{max(0.1, dur*frac):.2f}",
                                "-i", str(vid), "-frames:v", "1", "-vf", "scale=480:-1",
                                "-q:v", "4", str(fp)], check=True, timeout=60)
                if fp.exists():
                    frames.append(base64.standard_b64encode(fp.read_bytes()).decode())
            except Exception:
                pass
        if not frames:
            raise HTTPException(400, "Could not read frames from the clip — is it a valid video file?")

        blocks = [{"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b}}
                  for b in frames]
        blocks.append({"type": "text", "text": _STYLE_PROMPT})
        sdk = ant.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0, max_retries=1)
        resp = sdk.messages.create(model="claude-sonnet-5", max_tokens=800,
                                   messages=[{"role": "user", "content": blocks}])
        raw = _resp_text(resp)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if not m:
            raise HTTPException(500, "Could not parse a style profile from the clip")
        return json.loads(m.group())


_STYLE_SYNTH_PROMPT = """You are given style analyses of several short clips a creator uploaded as inspiration — videos they like and want their OWN edits to match. Synthesize ONE combined style profile that captures their preferred style: find the common thread, and where clips differ pick the dominant / most-repeated look. Return ONLY strict JSON:
{
  "caption_style": "one sentence on the captions they favour",
  "color_mood": "the colour grade / mood they favour",
  "pacing": "slow | medium | fast-cut",
  "energy": "calm | balanced | high-energy",
  "text_overlays": "hook/title/on-screen-text style they favour, or 'minimal'",
  "grade_warmth": "warmer | cooler | neutral",
  "grade_contrast": "low | normal | high",
  "grade_saturation": "muted | normal | vivid",
  "caption_size": "small | medium | large",
  "summary": "2-3 sentence description of the creator's combined preferred style",
  "features": ["3-6 short plain-language bullets stating exactly what EVERY future video for this creator will now use, e.g. 'Bold centred karaoke captions', 'Warm, high-contrast colour grade', 'Fast, punchy cuts', 'Big all-caps hook text'"]
}"""


def _synthesize_style_profile(analyses: list) -> dict:
    """Combine per-clip style reads into one profile with a plain-English feature list."""
    if not analyses:
        return {}
    try:
        import anthropic as ant
    except ImportError:
        return analyses[0]
    sdk = ant.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0, max_retries=1)
    resp = sdk.messages.create(
        model="claude-sonnet-5", max_tokens=900,
        messages=[{"role": "user", "content":
            _STYLE_SYNTH_PROMPT + "\n\nPer-clip analyses:\n" + json.dumps(analyses, indent=2)}])
    raw = _resp_text(resp)
    m = re.search(r'\{.*\}', raw, re.DOTALL)
    return json.loads(m.group()) if m else analyses[0]


def _style_refs_dir(client_id: str) -> Path:
    if not get_client(client_id):
        raise HTTPException(404, "Client not found")
    folder = (STYLE_DIR / client_id).resolve()
    if folder.parent != STYLE_DIR.resolve():
        raise HTTPException(400, "Invalid client id")
    folder.mkdir(exist_ok=True)
    return folder


def _load_style_analyses(client_id: str) -> dict:
    f = STYLE_DIR / client_id / ".analyses.json"
    if f.exists():
        try: return json.loads(f.read_text())
        except Exception: return {}
    return {}


def _save_style_analyses(client_id: str, data: dict):
    (STYLE_DIR / client_id).mkdir(exist_ok=True)
    (STYLE_DIR / client_id / ".analyses.json").write_text(json.dumps(data, indent=2))


def _resynthesize_style(client_id: str):
    """Re-synthesize the combined profile from all a client's reference clips and store it."""
    analyses = list(_load_style_analyses(client_id).values())
    profile = _synthesize_style_profile(analyses) if analyses else None
    clients = load_clients()
    for c in clients:
        if c["id"] == client_id:
            if profile: c["style_profile"] = profile
            else:       c.pop("style_profile", None)
            save_clients(clients)
            break
    return profile


@app.get("/api/clients/{client_id}/style-refs")
def list_style_refs(client_id: str):
    folder = _style_refs_dir(client_id)
    clips = [f.name for f in sorted(folder.iterdir())
             if f.is_file() and f.suffix.lower() in BROLL_EXTS]
    c = get_client(client_id)
    return {"clips": clips, "profile": (c or {}).get("style_profile")}


@app.post("/api/clients/{client_id}/style-refs")
async def upload_style_ref(client_id: str, file: UploadFile = File(...)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(400, "ANTHROPIC_API_KEY not set — add it to your .env to use this feature")
    folder = _style_refs_dir(client_id)
    safe = Path(file.filename or "").name
    if not safe or Path(safe).suffix.lower() not in BROLL_EXTS:
        raise HTTPException(400, "Only video clips are allowed")
    content = await file.read()
    (folder / safe).write_bytes(content)

    profile1 = await asyncio.to_thread(_analyze_reference_style, content)
    analyses = _load_style_analyses(client_id)
    analyses[safe] = profile1
    _save_style_analyses(client_id, analyses)
    combined = await asyncio.to_thread(_resynthesize_style, client_id)

    clips = [f.name for f in sorted(folder.iterdir())
             if f.is_file() and f.suffix.lower() in BROLL_EXTS]
    return {"clips": clips, "profile": combined}


@app.delete("/api/clients/{client_id}/style-refs/{filename}")
def delete_style_ref(client_id: str, filename: str):
    folder = _style_refs_dir(client_id)
    safe = Path(filename).name
    p = (folder / safe).resolve()
    if p.parent == folder and p.suffix.lower() in BROLL_EXTS and p.exists():
        p.unlink()
    analyses = _load_style_analyses(client_id)
    analyses.pop(safe, None)
    _save_style_analyses(client_id, analyses)
    profile = _resynthesize_style(client_id)
    clips = [f.name for f in sorted(folder.iterdir())
             if f.is_file() and f.suffix.lower() in BROLL_EXTS]
    return {"ok": True, "clips": clips, "profile": profile}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    j = json.loads(path.read_text())
    j.pop("elevenlabs_key", None)
    return j


# ── Pipeline ──────────────────────────────────────────────────────────────

_RUNNING_STATUSES = {"normalizing", "transcribing", "generating_edl", "rendering"}


@app.post("/api/jobs/{job_id}/run")
async def trigger_pipeline(job_id: str, request: Request):
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    job = json.loads(path.read_text())

    if job["status"] in _RUNNING_STATUSES:
        raise HTTPException(409, "Pipeline is already running for this job")

    mock_mode = os.environ.get("MOCK_TRANSCRIBE") == "1"
    if not ELEVENLABS_API_KEY and not mock_mode:
        raise HTTPException(400, "ELEVENLABS_API_KEY is not set. Set it in your environment, or set MOCK_TRANSCRIBE=1 to test without it.")

    # Read optional AI editing instructions from request body
    try:
        body = await request.json()
    except Exception:
        body = {}
    instructions = (body.get("instructions") or "").strip()
    if instructions:
        job["palmier_instructions"] = instructions
    elif "palmier_instructions" in body and not body["palmier_instructions"]:
        job.pop("palmier_instructions", None)  # cleared by user

    # Optional script: the words the client meant to say. Used as ground truth so
    # hesitations and false starts are cut reliably in any language (a spoken word
    # not in the script is a hesitation). Empty string clears a previously set one.
    if "script" in body:
        scr = (body.get("script") or "").strip()
        if scr:
            job["script"] = scr
        else:
            job.pop("script", None)

    # B-roll count for this video: "ai"/None = AI decides, or an integer (0 = none)
    if "broll_count" in body:
        bc = body["broll_count"]
        if bc in (None, "", "ai"):
            job.pop("broll_count", None)
        else:
            try:
                job["broll_count"] = max(0, int(bc))
            except (ValueError, TypeError):
                job.pop("broll_count", None)

    # On re-render, refresh the client snapshot so updated settings take effect
    fresh_client = get_client(job.get("client_id", ""))
    if fresh_client:
        job["client_snapshot"] = fresh_client

    # Reset log and status before starting
    job["status"] = "normalizing"
    job["log"] = []
    path.write_text(json.dumps(job, indent=2))

    thread = threading.Thread(
        target=run_pipeline,
        args=(job_id, JOBS_DIR, UPLOADS_DIR, ELEVENLABS_API_KEY),
        daemon=True,
    )
    thread.start()
    return {"status": "started"}


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    job = json.loads(path.read_text())
    if job["status"] not in _RUNNING_STATUSES:
        raise HTTPException(400, f"Job is not running (status: {job['status']})")
    job["cancelled"] = True
    job["status"]    = "cancelled"
    path.write_text(json.dumps(job, indent=2))
    return {"ok": True}


@app.get("/api/jobs/{job_id}/download")
def download_output(job_id: str):
    path = JOBS_DIR / f"{job_id}.json"
    if not path.exists():
        raise HTTPException(404, "Job not found")
    job = json.loads(path.read_text())

    if job.get("status") != "done":
        raise HTTPException(400, "Job is not complete yet")

    output_path = job.get("output_path") or ""
    if output_path and Path(output_path).exists():
        client_name = job.get("client_name", "client").replace(" ", "_")
        folder_name = job.get("folder_name", "video").replace(" ", "_")
        filename = f"{client_name}_{folder_name}_final.mp4"
        return FileResponse(output_path, media_type="video/mp4", filename=filename)

    # Full Drive backend: no local copy is kept — the finished video lives in
    # Drive. Send the user straight to it.
    if job.get("drive_link"):
        return RedirectResponse(job["drive_link"], status_code=302)

    raise HTTPException(404, "Finished video not found. It may still be delivering to Drive.")


# ── Health ────────────────────────────────────────────────────────────────

@app.get("/api/health")
def health():
    return {"status": "ok", "auth_enabled": bool(DASHBOARD_PASSWORD)}


@app.get("/api/integrations/status")
def integrations_status():
    """What client integrations are wired up. Used to verify setup on the call."""
    try:
        from integrations import config as _icfg
        return _icfg.status()
    except Exception as e:
        return {"error": str(e)}


# ── Google Drive sign-in (OAuth) ────────────────────────────────────────────
# Delivers onto the user's OWN Google Drive by signing in as them once. The
# refresh token is saved under DATA_ROOT so it survives redeploys. These routes
# sit behind the normal login; Google's redirect back carries the Lax session
# cookie, so the callback is authenticated like any same-site navigation.

_GDRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _oauth_redirect_uri(request: Request) -> str:
    """The callback URL Google returns to. Honors an explicit override, else is
    built from the forwarded host so it is correct behind Railway's proxy."""
    from integrations import config as _icfg
    if _icfg.GOOGLE_OAUTH_REDIRECT_URI:
        return _icfg.GOOGLE_OAUTH_REDIRECT_URI
    proto = (request.headers.get("x-forwarded-proto") or request.url.scheme or "https").split(",")[0].strip()
    host  = (request.headers.get("x-forwarded-host") or request.headers.get("host") or request.url.netloc).split(",")[0].strip()
    return f"{proto}://{host}/api/gdrive/oauth/callback"


def _build_gdrive_flow(redirect_uri: str):
    from google_auth_oauthlib.flow import Flow
    from integrations import config as _icfg
    client_config = {"web": {
        "client_id": _icfg.GOOGLE_OAUTH_CLIENT_ID,
        "client_secret": _icfg.GOOGLE_OAUTH_CLIENT_SECRET,
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "redirect_uris": [redirect_uri],
    }}
    return Flow.from_client_config(client_config, scopes=_GDRIVE_SCOPES, redirect_uri=redirect_uri)


@app.get("/api/gdrive/oauth/info")
def gdrive_oauth_info(request: Request):
    """Powers the Connect button, shows the redirect URI to register, and — the
    important bit — actually asks Google whether the stored sign-in still works,
    so a stale token can't keep showing as "connected"."""
    from integrations import config as _icfg
    info = {
        "available":    _icfg.gdrive_oauth_available(),
        "connected":    _icfg.gdrive_oauth_ready(),
        "redirect_uri": _oauth_redirect_uri(request),
        "working":      None,   # None = not checked (no sign-in stored)
        "email":        "",
        "error":        "",
    }
    if info["connected"]:
        try:
            from integrations import gdrive as _gdrive
            chk = _gdrive.check_connection(log=lambda m: print(f"[gdrive-check] {m}", flush=True))
            info["working"] = bool(chk.get("ok"))
            info["email"]   = chk.get("email", "")
            info["error"]   = chk.get("error", "")
        except Exception as e:
            info["working"] = False
            info["error"]   = str(e)[:200]
    return info


@app.get("/api/gdrive/oauth/start")
def gdrive_oauth_start(request: Request):
    """Begin the Google sign-in — redirects the browser to Google's consent screen."""
    from integrations import config as _icfg
    if not _icfg.gdrive_oauth_available():
        return JSONResponse(
            {"detail": "Add GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET in Railway first."},
            status_code=400)
    try:
        flow = _build_gdrive_flow(_oauth_redirect_uri(request))
        auth_url, state = flow.authorization_url(
            access_type="offline", include_granted_scopes="true", prompt="consent")
    except ImportError:
        return JSONResponse({"detail": "google-auth-oauthlib is not installed on the server."}, status_code=500)
    except Exception as e:
        return JSONResponse({"detail": f"Could not start Google sign-in: {e}"}, status_code=500)
    resp = RedirectResponse(auth_url, status_code=302)
    resp.set_cookie("gdrive_oauth_state", state, max_age=600, httponly=True,
                    samesite="lax", secure=os.environ.get("HTTPS", "") == "1")
    return resp


@app.get("/api/gdrive/oauth/callback")
def gdrive_oauth_callback(request: Request):
    """Google returns here after consent. Exchange the code for a token and save it."""
    from integrations import config as _icfg
    if request.query_params.get("error"):
        return RedirectResponse("/setup.html?drive=denied", status_code=302)
    code = request.query_params.get("code", "")
    state = request.query_params.get("state", "")
    cookie_state = request.cookies.get("gdrive_oauth_state", "")
    if not code or not state or not cookie_state or not hmac.compare_digest(state, cookie_state):
        return RedirectResponse("/setup.html?drive=error", status_code=302)
    try:
        flow = _build_gdrive_flow(_oauth_redirect_uri(request))
        flow.fetch_token(code=code)
        creds = flow.credentials
        os.makedirs(os.path.dirname(_icfg.GDRIVE_OAUTH_TOKEN_FILE), exist_ok=True)
        with open(_icfg.GDRIVE_OAUTH_TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
    except Exception:
        return RedirectResponse("/setup.html?drive=error", status_code=302)
    resp = RedirectResponse("/setup.html?drive=connected", status_code=302)
    resp.delete_cookie("gdrive_oauth_state")
    return resp


@app.post("/api/gdrive/oauth/disconnect")
def gdrive_oauth_disconnect():
    """Forget the stored Google sign-in."""
    from integrations import config as _icfg
    try:
        if os.path.exists(_icfg.GDRIVE_OAUTH_TOKEN_FILE):
            os.remove(_icfg.GDRIVE_OAUTH_TOKEN_FILE)
    except Exception as e:
        return JSONResponse({"ok": False, "detail": str(e)}, status_code=500)
    return {"ok": True}


@app.get("/api/admin/storage")
def storage_status():
    """Volume usage, for the Free up space panel."""
    try:
        du = shutil.disk_usage(str(DATA_ROOT))
        return {"total_gb": round(du.total/1e9, 2), "used_gb": round(du.used/1e9, 2),
                "free_gb": round(du.free/1e9, 2)}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/admin/free-space")
def free_space():
    """User-triggered cleanup. Removes only REGENERABLE render leftovers from every
    job folder — the normalized copy (*_v30.mov) and the working intermediates.
    Never touches the raw uploaded footage or the finished videos, so nothing the
    client cares about can be lost. Returns how much was freed."""
    inter_files = ("base30.mkv", "base30_zoom.mkv", "composited30.mkv",
                   "_seg_offsets.json", "_concat30.txt")
    inter_dirs  = ("clips30", "animations")
    freed = 0
    if UPLOADS_DIR.exists():
        for job_dir in UPLOADS_DIR.iterdir():
            if not job_dir.is_dir():
                continue
            for p in job_dir.iterdir():
                try:
                    if p.is_file() and (p.name in inter_files or p.name.endswith("_v30.mov")):
                        freed += p.stat().st_size
                        p.unlink()
                except Exception:
                    pass
            for name in inter_dirs:
                dp = job_dir / name
                try:
                    if dp.is_dir():
                        for sub in dp.rglob("*"):
                            try:
                                if sub.is_file():
                                    freed += sub.stat().st_size
                            except Exception:
                                pass
                        shutil.rmtree(dp, ignore_errors=True)
                except Exception:
                    pass
    free_gb = None
    try:
        free_gb = round(shutil.disk_usage(str(DATA_ROOT)).free / 1e9, 2)
    except Exception:
        pass
    return {"ok": True, "freed_mb": round(freed / 1e6), "free_gb": free_gb}


# ── Files manager — browse and selectively delete what's on the volume ───────
# Deletion is limited to the uploads / B-roll / style-ref areas; the OAuth token,
# job metadata and clients.json are never listed or deletable here.
def _file_roots():
    return [UPLOADS_DIR.resolve(), BROLL_DIR.resolve(), STYLE_DIR.resolve()]


@app.get("/api/admin/files")
def list_stored_files():
    """Everything stored on the volume, grouped by video / client, with sizes."""
    clients = {c["id"]: c["name"] for c in load_clients()}
    jobs = {}
    for f in JOBS_DIR.glob("*.json"):
        try:
            j = json.loads(f.read_text())
            jobs[j["id"]] = {"name": j.get("folder_name", "untitled"), "client": j.get("client_name", "")}
        except Exception:
            pass

    def _rel(p):
        return str(p.relative_to(DATA_ROOT))

    groups = []

    def _collect(root, label_fn, kind):
        if not root.exists():
            return
        for sub in sorted(root.iterdir()):
            if not sub.is_dir():
                continue
            files = []
            for fp in sorted(sub.rglob("*")):
                if fp.is_file():
                    try:
                        sz = fp.stat().st_size
                    except Exception:
                        sz = 0
                    files.append({"path": _rel(fp), "name": fp.name, "size": sz})
            if files:
                groups.append({"kind": kind, "label": label_fn(sub.name),
                               "size": sum(x["size"] for x in files), "files": files})

    def _job_label(jid):
        info = jobs.get(jid)
        if not info:
            return f"Video: {jid[:8]}…"
        return f"Video: {info['name']}" + (f" · {info['client']}" if info['client'] else "")

    _collect(UPLOADS_DIR, _job_label, "job")
    _collect(BROLL_DIR, lambda cid: f"B-roll: {clients.get(cid, cid[:8] + '…')}", "broll")
    _collect(STYLE_DIR, lambda cid: f"Style refs: {clients.get(cid, cid[:8] + '…')}", "style")
    groups.sort(key=lambda g: g["size"], reverse=True)

    total = free = None
    try:
        du = shutil.disk_usage(str(DATA_ROOT))
        total, free = du.total, du.free
    except Exception:
        pass
    return {"groups": groups, "total_bytes": total, "free_bytes": free}


@app.post("/api/admin/files/delete")
async def delete_stored_files(request: Request):
    """Delete the exact files the user selected. Each path is resolved and must sit
    inside the uploads / B-roll / style-ref roots — nothing else can be touched."""
    body = await request.json()
    paths = body.get("paths") or []
    roots = _file_roots()
    freed = deleted = 0
    for rel in paths:
        try:
            p = (DATA_ROOT / rel).resolve()
            if not any(str(p) == str(r) or str(p).startswith(str(r) + os.sep) for r in roots):
                continue  # outside the allowed areas — skip
            if p.is_file():
                freed += p.stat().st_size
                p.unlink()
                deleted += 1
                # tidy up now-empty parent folders
                try:
                    if p.parent not in roots and not any(p.parent.iterdir()):
                        p.parent.rmdir()
                except Exception:
                    pass
        except Exception:
            pass
    free = None
    try:
        free = shutil.disk_usage(str(DATA_ROOT)).free
    except Exception:
        pass
    return {"ok": True, "deleted": deleted, "freed_mb": round(freed / 1e6), "free_bytes": free}


# ── AI Chat ───────────────────────────────────────────────────────────────

def _job_edl_path(job_id: str) -> Optional[Path]:
    p = UPLOADS_DIR / job_id / "edl.json"
    return p if p.exists() else None


_CHAT_SYSTEM = """You are a video editing assistant inside the __BRAND__ Editing Machine — a dashboard that produces vertical social media videos (1080×1920 @30fps) from raw talking-head footage.

You help clients adjust their editing settings using plain English. You can read and write client profiles.

GRADE FILTER — HOW IT WORKS (read carefully, the directions are non-obvious):

  colorlevels=rimax=R:gimax=G:bimax=B
    Each parameter is the INPUT ceiling for that channel. Lower value = that channel gets
    boosted more (because the same 0-to-max input range is stretched to 0-1 output).
    Value range 0.75–1.0. Default neutral: rimax=0.92:gimax=0.92:bimax=0.88.

    TO COOL / remove warmth / reduce orange:
      - RAISE rimax and gimax (less red/green boost), e.g. 0.92 → 0.97
      - AND/OR LOWER bimax (more blue boost), e.g. 0.88 → 0.80
      - Do both for strong cooling effect.

    TO WARM / add golden tone:
      - LOWER rimax/gimax (more red/green boost), e.g. 0.92 → 0.85
      - AND/OR RAISE bimax (less blue boost), e.g. 0.88 → 0.93

  eq=saturation=S:contrast=C
    S: 1.0 = neutral, >1 = more vivid/saturated, <1 = muted/flat. Default 1.0.
    For "too vivid/oversaturated" lower to 0.85–0.95.
    For "flat/washed out" raise to 1.05–1.15.

  unsharp=LX:LY:LA:CX:CY:CA
    LA = luma sharpening amount. 0.4 = subtle (default), 0.8 = sharp, 0.0 = off.

CAPTION SETTINGS:
  caption_font_size: pixel size. Default 60.
  caption_y: vertical pixel position. Default 1300. Higher = lower on screen (max ~1700).

IMPORTANT — HOW TO MAKE CHANGES:
- When someone says "too warm", "orange tint", "too yellow" → raise rimax+gimax by 0.04–0.08 AND lower bimax by 0.05–0.10. Make it dramatic.
- When someone says "way too warm" / "much warmer" — shift values by 0.08–0.12, not 0.02.
- When someone says "too saturated" → lower saturation to 0.85–0.95.
- Always read current settings first, then make targeted changes to the full grade string.
- Return the COMPLETE grade string (colorlevels + eq + unsharp), not just part of it.
- Tell the client exactly what you changed in one sentence, then say to re-run the job.
- Be concise. Do not over-explain.

If no client is currently selected ask which client the user wants to adjust."""

_CHAT_TOOLS = [
    {
        "name": "list_clients",
        "description": "List all client profiles with their IDs and names.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_client_settings",
        "description": "Get the full settings for a specific client.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string", "description": "The client UUID"},
            },
            "required": ["client_id"],
        },
    },
    {
        "name": "update_client_settings",
        "description": "Update editing or brand settings for a client. Pass only the fields to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "client_id": {"type": "string"},
                "editing": {
                    "type": "object",
                    "description": (
                        "Subset of editing fields to update: "
                        "grade (ffmpeg vf string), "
                        "caption_font_size (int 20–120), "
                        "caption_y (int 100–1800), "
                        "caption_max_width (int), "
                        "language (en/da/es/fr/de/auto), "
                        "num_speakers (1 or 2)"
                    ),
                },
                "brand": {
                    "type": "object",
                    "description": "Subset of brand fields: primary_color (hex string), accent_color (hex string)",
                },
            },
            "required": ["client_id"],
        },
    },
]


_JOB_CHAT_SYSTEM = """You are a video editing assistant inside the __BRAND__ Editing Machine.

You are editing ONE SPECIFIC VIDEO — not the client's default settings.
Every change you make goes ONLY to this job's EDL and triggers an automatic re-render of this video.
Do NOT call update_client_settings unless the user explicitly says "change for all future videos" or "set as default".

For COLOR / CAPTION changes: call get_job_edl first, then update_job_edl.
For B-ROLL changes: call list_broll first to see what's currently in the video and what clips are
available, then use add_broll / remove_broll. B-roll is auto-matched by the AI, and your edits
fine-tune it — additions and removals persist across re-renders. Use reset_broll to go back to pure
auto-matching. To place a clip, give a short exact quote from the transcript for the moment it should appear.
PHOTOS (still images) can show two ways: a "card" that pops up over the speaker (BAM), or "full" screen.
The AI picks per photo by default; pass style on add_broll to force one. If the user wants every photo to
pop up as a card (e.g. "make all the pictures pop in", "always use the BAM effect"), call set_photo_style
with mode "cards"; use "auto" to hand the choice back to the AI.

For ZOOM changes: a punch-in zoom snaps the frame tighter at a moment, holds, then eases back. When the user
says "zoom at 8 seconds", "punch in at 0:12", or "add a zoom when…", call add_zoom with at_sec in seconds
(convert mm:ss to seconds). Call list_zooms first if they want to move or remove one; use remove_zoom at the
timestamp, or clear_zooms to drop them all. Zoom edits persist across re-renders just like B-roll.

After applying any change, tell the user in one sentence what changed. The re-render starts automatically.

GRADE FILTER — HOW IT WORKS:

  colorlevels=rimax=R:gimax=G:bimax=B
    Lower value = that channel gets boosted more. Range 0.75–1.0.

    TO COOL: RAISE rimax+gimax (e.g. 0.92→0.97) AND/OR LOWER bimax (e.g. 0.88→0.80)
    TO WARM: LOWER rimax/gimax AND/OR RAISE bimax
    "Way too warm" = shift by 0.08–0.12, not 0.02.

  eq=saturation=S:contrast=C   — S: 1.0 neutral, >1 vivid, <1 muted
  unsharp=LX:LY:LA — LA is sharpening amount (0.3 default, 0.8 sharp, 0.0 off)

CAPTION SETTINGS:
  caption_y: vertical pixel position. 1300 = near bottom. Lower number = higher on screen.
  caption_font_size: pixel size. Default 80.
  Return COMPLETE grade string when updating grade."""

_JOB_CHAT_TOOLS = [
    {
        "name": "get_job_edl",
        "description": "Read the current grade, caption position, font size, and colors for this specific video.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "update_job_edl",
        "description": "Update this video's settings. Triggers an automatic re-render. Pass only the fields to change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "grade":              {"type": "string",  "description": "Full ffmpeg grade string (colorlevels+eq+unsharp)"},
                "caption_y":          {"type": "integer", "description": "Caption vertical position in pixels (100–1800, lower = higher on screen)"},
                "caption_font_size":  {"type": "integer", "description": "Caption font size in pixels (20–120)"},
                "caption_color":      {"type": "string",  "description": "Caption text color as hex e.g. #ffffff"},
                "highlight_color":    {"type": "string",  "description": "First-word accent color as hex e.g. #F97316"},
                "caption_max_width":  {"type": "integer", "description": "Max caption line width in pixels"},
            },
            "required": [],
        },
    },
    {
        "name": "list_broll",
        "description": "List the B-roll cutaways currently in this video (with their timestamps), plus the clips available in this client's B-roll library to choose from. Call this before adding/removing so you use exact clip filenames and quotes.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_broll",
        "description": "Add a B-roll cutaway to this video, then re-render. Place it at a spoken moment by giving a short exact phrase from the video's transcript.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file":         {"type": "string",  "description": "Exact clip filename from this client's library (see list_broll)"},
                "quote":        {"type": "string",  "description": "2–5 word exact phrase from the transcript where the clip should start"},
                "duration_sec": {"type": "number",  "description": "How long to show it, 1.5–3.5 seconds (default 2.5)"},
                "style":        {"type": "string",  "enum": ["card", "full"], "description": "PHOTO clips only: 'card' pops it up over the speaker (BAM), 'full' fills the screen. Ignored for video clips."},
            },
            "required": ["file", "quote"],
        },
    },
    {
        "name": "set_photo_style",
        "description": "Set how PHOTO B-roll is shown in this whole video. 'cards' forces every photo to pop up on a card over the speaker (the BAM effect). 'auto' lets the AI decide card vs full-frame per photo. Re-renders after.",
        "input_schema": {
            "type": "object",
            "properties": {
                "mode": {"type": "string", "enum": ["cards", "auto"], "description": "'cards' = always pop up as cards; 'auto' = AI decides per photo"},
            },
            "required": ["mode"],
        },
    },
    {
        "name": "remove_broll",
        "description": "Remove a B-roll cutaway from this video, then re-render. Identify it by its clip filename (from list_broll); add the quote too if the same clip appears more than once.",
        "input_schema": {
            "type": "object",
            "properties": {
                "file":  {"type": "string", "description": "Clip filename to remove"},
                "quote": {"type": "string", "description": "Optional: the spoken moment to remove, if the clip is used multiple times"},
            },
            "required": ["file"],
        },
    },
    {
        "name": "reset_broll",
        "description": "Discard all manual B-roll add/remove edits and let the AI re-match B-roll from scratch on the next render.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "list_zooms",
        "description": "List the punch-in zooms currently in this video (each with its timestamp in seconds), so you can add or remove them precisely.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "add_zoom",
        "description": "Add a punch-in-and-hold zoom at a specific moment, then re-render. The frame snaps tighter at 'at_sec', holds, then eases back. Use for 'zoom at 8 seconds' style requests.",
        "input_schema": {
            "type": "object",
            "properties": {
                "at_sec":       {"type": "number", "description": "When to punch in, in seconds from the start of the FINAL video"},
                "duration_sec": {"type": "number", "description": "How long to hold the zoom, 1.5–3.5s (default 2.5)"},
                "strength":     {"type": "number", "description": "How tight, 0.08 (subtle) to 0.20 (strong); default 0.12"},
            },
            "required": ["at_sec"],
        },
    },
    {
        "name": "remove_zoom",
        "description": "Remove the punch-in zoom at (or nearest to) a given timestamp, then re-render.",
        "input_schema": {
            "type": "object",
            "properties": {
                "at_sec": {"type": "number", "description": "The timestamp (seconds) of the zoom to remove"},
            },
            "required": ["at_sec"],
        },
    },
    {
        "name": "clear_zooms",
        "description": "Remove ALL punch-in zooms currently in this video, then re-render with no zooms.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]


def _rerender_job(job: dict, job_id: str):
    """Kick off a background re-render for a job that was edited via chat."""
    job_path = JOBS_DIR / f"{job_id}.json"
    job["status"] = "normalizing"
    job["log"]    = []
    job_path.write_text(json.dumps(job, indent=2))
    threading.Thread(
        target=run_pipeline,
        args=(job_id, JOBS_DIR, UPLOADS_DIR, ELEVENLABS_API_KEY),
        daemon=True,
    ).start()


def _broll_choices(client_id: str, client_name: str) -> tuple:
    """B-roll available to this client's chat: locally-uploaded clips plus the clips
    in the client's Google Drive B-roll folder, each with a description when it has
    already been analysed. Returns (names:set, choices:list of dicts)."""
    from pipeline import read_broll_tags
    local_folder = BROLL_DIR / client_id
    names, choices = set(), []
    local_files = [f for f in sorted(local_folder.iterdir())
                   if f.is_file() and f.suffix.lower() in BROLL_EXTS] if local_folder.exists() else []
    local_tags = read_broll_tags(local_folder, local_files) if local_files else {}
    for f in local_files:
        names.add(f.name)
        choices.append({"file": f.name,
                        "description": (local_tags.get(f.name) or {}).get("description", ""),
                        "source": "upload"})
    try:
        from integrations import config as _icfg, gdrive as _gdrive
        if _icfg.gdrive_configured():
            cache = {}
            cache_path = local_folder / ".tags.json"
            if cache_path.exists():
                try: cache = json.loads(cache_path.read_text())
                except Exception: cache = {}
            for f in _gdrive.list_broll(client_name):
                nm = f.get("name", "")
                if not nm or nm in names:
                    continue
                names.add(nm)
                desc = ""
                mt = _gdrive._rfc3339_to_epoch(f.get("modifiedTime"))
                if mt and f.get("size"):
                    desc = (cache.get(f"{nm}:{f.get('size')}:{int(mt)}") or {}).get("description", "")
                choices.append({"file": nm, "description": desc, "source": "drive"})
    except Exception:
        pass
    return names, choices


def _chat_tool_call(tool_name: str, tool_input: dict, applied: list, job_id: Optional[str] = None) -> dict:
    if tool_name == "get_job_edl":
        if not job_id:
            return {"error": "No job context"}
        edl_path = _job_edl_path(job_id)
        if not edl_path:
            return {"error": "EDL not found — job may not have been rendered yet"}
        edl = json.loads(edl_path.read_text())
        caps = edl.get("style", {}).get("captions", {})
        return {
            "grade":             edl.get("grade", ""),
            "caption_y":         caps.get("y"),
            "caption_font_size": caps.get("font_size"),
            "caption_color":     caps.get("color"),
            "highlight_color":   caps.get("highlight_color"),
            "caption_max_width": caps.get("max_width"),
        }

    if tool_name == "update_job_edl":
        if not job_id:
            return {"error": "No job context"}
        job_path = JOBS_DIR / f"{job_id}.json"
        if not job_path.exists():
            return {"error": "Job not found"}
        job = json.loads(job_path.read_text())
        changes: dict = {}
        # Store overrides in the job JSON — pipeline applies these on top of the
        # regenerated EDL so they survive every re-render for this specific job.
        overrides = job.setdefault("job_overrides", {})
        for key in ("grade", "caption_y", "caption_font_size",
                    "caption_color", "highlight_color", "caption_max_width"):
            if key in tool_input:
                overrides[key] = tool_input[key]
                changes[key] = tool_input[key]
        _rerender_job(job, job_id)
        applied.append({"type": "job_rerendering", "job_id": job_id, "changes": changes})
        return {"ok": True, "changes": changes, "rerendering": True}

    if tool_name in ("list_broll", "add_broll", "remove_broll", "reset_broll", "set_photo_style"):
        if not job_id:
            return {"error": "No job context"}
        job_path = JOBS_DIR / f"{job_id}.json"
        if not job_path.exists():
            return {"error": "Job not found"}
        job = json.loads(job_path.read_text())
        client_id = job.get("client_id", "")
        client_name = job.get("client_name", "")
        folder = BROLL_DIR / client_id

        if tool_name == "list_broll":
            _names, choices = _broll_choices(client_id, client_name)
            return {
                "current_broll_in_video": job.get("broll_last", []),
                "your_manual_additions":  job.get("broll_add", []),
                "your_removals":          job.get("broll_remove", []),
                "available_clips": choices,
            }

        if tool_name == "add_broll":
            fname = Path(tool_input.get("file", "")).name
            quote = (tool_input.get("quote") or "").strip()
            if not fname or not quote:
                return {"error": "Need both a clip 'file' and a 'quote' from the transcript"}
            _names, _ = _broll_choices(client_id, client_name)
            if fname not in _names:
                return {"error": f"Clip '{fname}' is not in this client's B-roll library or Drive folder"}
            entry = {"file": fname, "quote": quote,
                     "duration_sec": max(1.5, min(3.5, float(tool_input.get("duration_sec", 2.5))))}
            _style = (tool_input.get("style") or "").strip().lower()
            if _style in ("card", "full"):
                entry["style"] = _style
            adds = job.setdefault("broll_add", [])
            adds.append(entry)
            # If this clip+quote was previously removed, clear that removal
            job["broll_remove"] = [r for r in job.get("broll_remove", [])
                                   if not (Path(r.get("file","")).name == fname
                                           and (not r.get("quote") or r["quote"].lower() in quote.lower()))]
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id, "changes": {"broll_added": entry}})
            return {"ok": True, "added": entry, "rerendering": True}

        if tool_name == "remove_broll":
            fname = Path(tool_input.get("file", "")).name
            quote = (tool_input.get("quote") or "").strip()
            if not fname:
                return {"error": "Need the clip 'file' to remove"}
            # Drop it from manual additions if present
            before = len(job.get("broll_add", []))
            job["broll_add"] = [a for a in job.get("broll_add", [])
                                if not (Path(a["file"]).name == fname
                                        and (not quote or quote.lower() in a.get("quote","").lower()))]
            # Suppress it from auto-matches via a removal delta
            job.setdefault("broll_remove", []).append({"file": fname, "quote": quote})
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id,
                            "changes": {"broll_removed": fname + (f" @ '{quote}'" if quote else "")}})
            return {"ok": True, "removed": fname, "was_manual": before != len(job.get("broll_add", [])),
                    "rerendering": True}

        if tool_name == "reset_broll":
            job.pop("broll_add", None)
            job.pop("broll_remove", None)
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id, "changes": {"broll": "reset to auto-match"}})
            return {"ok": True, "rerendering": True}

        if tool_name == "set_photo_style":
            mode = (tool_input.get("mode") or "auto").strip().lower()
            mode = "cards" if mode in ("card", "cards", "pop", "bam", "popin", "pop-in") else "auto"
            job["broll_style"] = mode
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id, "changes": {"photo_style": mode}})
            return {"ok": True, "photo_style": mode, "rerendering": True}

    if tool_name in ("list_zooms", "add_zoom", "remove_zoom", "clear_zooms"):
        if not job_id:
            return {"error": "No job context"}
        job_path = JOBS_DIR / f"{job_id}.json"
        if not job_path.exists():
            return {"error": "Job not found"}
        job = json.loads(job_path.read_text())

        if tool_name == "list_zooms":
            return {
                "zooms_in_video":        job.get("zoom_last", []),
                "your_manual_additions": job.get("zoom_add", []),
                "your_removals":         job.get("zoom_remove", []),
            }

        if tool_name == "add_zoom":
            try:
                at = round(float(tool_input.get("at_sec")), 2)
            except (TypeError, ValueError):
                return {"error": "Need a numeric 'at_sec' (seconds into the final video)"}
            if at < 0:
                return {"error": "at_sec must be 0 or more"}
            entry = {
                "at":       at,
                "duration": max(0.8, min(6.0, float(tool_input.get("duration_sec", 2.5) or 2.5))),
                "strength": max(0.06, min(0.30, float(tool_input.get("strength", 0.12) or 0.12))),
            }
            adds = job.setdefault("zoom_add", [])
            adds[:] = [a for a in adds if abs(float(a.get("at", -999)) - at) >= 0.4]  # replace one at same time
            adds.append(entry)
            job["zoom_remove"] = [r for r in job.get("zoom_remove", [])
                                  if abs(float(r.get("at", -999)) - at) >= 0.4]
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id, "changes": {"zoom_added": entry}})
            return {"ok": True, "added": entry, "rerendering": True}

        if tool_name == "remove_zoom":
            try:
                at = round(float(tool_input.get("at_sec")), 2)
            except (TypeError, ValueError):
                return {"error": "Need a numeric 'at_sec' to remove"}
            job["zoom_add"] = [a for a in job.get("zoom_add", [])
                               if abs(float(a.get("at", -999)) - at) >= 0.4]
            job.setdefault("zoom_remove", []).append({"at": at})
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id, "changes": {"zoom_removed_at": at}})
            return {"ok": True, "removed_at": at, "rerendering": True}

        if tool_name == "clear_zooms":
            job.pop("zoom_add", None)
            # Suppress every zoom currently placed so none survive the re-render
            job["zoom_remove"] = [{"at": float(z.get("at", 0))} for z in job.get("zoom_last", [])]
            _rerender_job(job, job_id)
            applied.append({"type": "job_rerendering", "job_id": job_id, "changes": {"zooms": "cleared"}})
            return {"ok": True, "rerendering": True}

    if tool_name == "list_clients":
        return [{"id": c["id"], "name": c["name"]} for c in load_clients()]

    if tool_name == "get_client_settings":
        c = get_client(tool_input["client_id"])
        return c or {"error": "Client not found"}

    if tool_name == "update_client_settings":
        cid = tool_input["client_id"]
        clients = load_clients()
        for i, c in enumerate(clients):
            if c["id"] == cid:
                if "editing" in tool_input:
                    clients[i]["editing"].update(tool_input["editing"])
                if "brand" in tool_input:
                    clients[i]["brand"].update(tool_input["brand"])
                save_clients(clients)
                changes = {**tool_input.get("editing", {}), **tool_input.get("brand", {})}
                applied.append({"type": "settings_updated", "client_name": c["name"], "changes": changes})
                return {"ok": True}
        return {"error": "Client not found"}

    return {"error": f"Unknown tool: {tool_name}"}


def _run_chat(messages: list, client_id: Optional[str], job_id: Optional[str] = None) -> dict:
    try:
        import anthropic as ant
    except ImportError:
        return {"reply": "The anthropic package is not installed. Run: pip install anthropic", "actions": []}

    sdk = ant.Anthropic(api_key=ANTHROPIC_API_KEY, timeout=120.0, max_retries=1)

    if job_id:
        # Job-scoped mode: only edit this video's EDL
        system = _JOB_CHAT_SYSTEM.replace("__BRAND__", BRAND_NAME)
        job_path = JOBS_DIR / f"{job_id}.json"
        if job_path.exists():
            j = json.loads(job_path.read_text())
            system += f"\n\nJob: {j.get('folder_name','untitled')} | Client: {j.get('client_name','')}"
        tools = _JOB_CHAT_TOOLS
    else:
        # Global mode: edit client default settings
        system = _CHAT_SYSTEM.replace("__BRAND__", BRAND_NAME)
        if client_id:
            c = get_client(client_id)
            if c:
                lines = [f"\n\nCurrently selected client: {c['name']} (ID: {c['id']})"]
                if c.get("niche"):  lines.append(f"Niche: {c['niche']}")
                if c.get("tone"):   lines.append(f"Tone: {', '.join(c['tone'])}")
                if c.get("icp"):    lines.append(f"ICP: {c['icp']}")
                if c.get("cta_text"): lines.append(f"CTA: {c['cta_text']}")
                system += "\n".join(lines)
        tools = _CHAT_TOOLS

    applied: list = []
    loop_msgs = list(messages)

    for _ in range(8):
        try:
            resp = sdk.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=1024,
                system=system,
                tools=tools,
                messages=loop_msgs,
            )
        except ant.AuthenticationError:
            return {"reply": "AI key is invalid or expired. Update ANTHROPIC_API_KEY in your .env and restart the server.", "actions": []}
        except ant.RateLimitError:
            return {"reply": "Rate limit reached. Wait a moment and try again.", "actions": []}
        except Exception as e:
            return {"reply": f"AI error: {str(e)[:200]}", "actions": []}

        if resp.stop_reason == "end_turn":
            reply = "".join(b.text for b in resp.content if hasattr(b, "text"))
            return {"reply": reply, "actions": applied}

        if resp.stop_reason == "tool_use":
            tool_results = []
            for block in resp.content:
                if block.type == "tool_use":
                    result = _chat_tool_call(block.name, block.input, applied, job_id)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    })
            loop_msgs = loop_msgs + [
                {"role": "assistant", "content": [b.model_dump() for b in resp.content]},
                {"role": "user", "content": tool_results},
            ]
        else:
            # Any other stop reason (e.g. the reply ran out of token room): return
            # whatever text we have rather than a blank generic error.
            reply = "".join(b.text for b in resp.content if hasattr(b, "text")).strip()
            return {"reply": reply or "I couldn't finish that one. Try rephrasing it a bit more specifically.",
                    "actions": applied}

    return {"reply": "That needed too many steps. Try one change at a time, and be specific about what to adjust.",
            "actions": applied}


@app.post("/api/chat")
async def chat_endpoint(request: Request):
    if not ANTHROPIC_API_KEY:
        return JSONResponse({
            "reply": "AI assistant is not configured yet. Add ANTHROPIC_API_KEY to your .env file to enable it.",
            "actions": [],
        })
    body = await request.json()
    message = (body.get("message") or "").strip()
    if not message:
        raise HTTPException(400, "message is required")
    client_id = body.get("client_id") or None
    job_id    = body.get("job_id") or None
    history   = body.get("history") or []
    messages  = history + [{"role": "user", "content": message}]
    result    = await asyncio.to_thread(_run_chat, messages, client_id, job_id)
    return result


# ── Static (must be last) ─────────────────────────────────────────────────

app.mount("/", StaticFiles(directory=str(BASE / "static"), html=True), name="static")
