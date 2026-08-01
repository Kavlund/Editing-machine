"""Full editing pipeline: normalize → transcribe → auto-EDL → decay → compose → final.mp4"""

from __future__ import annotations
import json, os, random, re, shutil, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

MAX_JOB_MINUTES = 45  # hard wall-clock limit per job

BROLL_VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
BROLL_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
BROLL_EXTS = BROLL_VIDEO_EXTS | BROLL_IMAGE_EXTS

def _is_broll_image(p) -> bool:
    from pathlib import Path as _P
    return _P(p).suffix.lower() in BROLL_IMAGE_EXTS


def _decodable_image(path, log_fn=None):
    """The container's ffmpeg can't read HEIC/HEIF (iPhone's default photo format),
    so a raw .HEIC B-roll photo makes the render fail. Convert those to a sibling
    JPEG that every downstream stage (vision tagging + ffmpeg compositing) can read.
    Returns the path to use — the .jpg for HEIC/HEIF, the original otherwise, or
    None if it can't be decoded at all (so the caller drops just that one photo)."""
    from pathlib import Path as _P
    path = _P(path)
    if path.suffix.lower() not in (".heic", ".heif"):
        return path
    out = path.with_suffix(".jpg")
    if out.exists():
        return out
    try:
        from PIL import Image
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except Exception:
            pass  # if unavailable, PIL may still open it; otherwise the except below fires
        with Image.open(path) as im:
            im.convert("RGB").save(out, "JPEG", quality=90)
        # Carry the source's mtime onto the JPEG so the vision-tag cache (keyed on
        # name+size+mtime) stays hit across renders instead of re-tagging every time.
        try:
            import os as _os
            st = path.stat()
            _os.utime(out, (st.st_atime, st.st_mtime))
        except Exception:
            pass
        if log_fn:
            log_fn(f"B-roll: converted {path.name} → {out.name} (HEIC isn't ffmpeg-readable)")
        return out
    except Exception as e:
        if log_fn:
            log_fn(f"B-roll: couldn't read {path.name} ({e}) — skipping that photo")
        return None

MOCK_TRANSCRIBE     = os.environ.get("MOCK_TRANSCRIBE", "") == "1"
SLACK_WEBHOOK_URL   = os.environ.get("SLACK_WEBHOOK_URL", "")


def _slack(text: str):
    if not SLACK_WEBHOOK_URL:
        return
    try:
        data = json.dumps({"text": text}).encode()
        req  = urllib.request.Request(SLACK_WEBHOOK_URL, data=data,
                                      headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass

# Allow direct imports from the editor module directory
EDITOR_DIR = Path(__file__).resolve().parent.parent / "editor"
# Render scratch lives on the container's EPHEMERAL disk, never on the mounted
# data volume, so a render's heavy temporary files (normalized clips, segments,
# the composite) never consume the small persistent volume. Wiped after each job.
SCRATCH_ROOT = Path(os.environ.get("RENDER_SCRATCH_ROOT", "/tmp/ee_render"))
sys.path.insert(0, str(EDITOR_DIR))

from normalize import normalize
from transcribe import transcribe_one

VIDEO_EXTS = {".mov", ".mp4", ".avi", ".mkv", ".mxf", ".m4v", ".webm", ".mts", ".m2ts"}


# ── Font resolution ────────────────────────────────────────────────────────────

def _looks_like_font(path: str) -> bool:
    """True only for a real TTF/OTF/TTC. Guards against a download that silently
    saved an HTML/404 page as a .ttf: the file then EXISTS, gets picked, and the
    render dies later with PIL's 'unknown file format'."""
    try:
        with open(path, "rb") as fh:
            return fh.read(4) in (b"\x00\x01\x00\x00", b"true", b"ttcf", b"OTTO")
    except Exception:
        return False


def _font(kind: str) -> list:
    """Return [path, ttc_index] for a font, preferring macOS then Docker paths.
    A candidate must be a VALID font file, not merely present — otherwise a bad
    download would win over the good system fallbacks below it."""
    candidates = {
        "handwritten": [
            ("/System/Library/Fonts/Noteworthy.ttc", 1),
            ("/app/fonts/Caveat.ttf", 0),
            ("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 0),
        ],
        "impact": [
            ("/System/Library/Fonts/Supplemental/Impact.ttf", 0),
            ("/app/fonts/Oswald.ttf", 0),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
        ],
        "caption": [
            ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
            ("/app/fonts/Poppins-SemiBold.ttf", 0),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
        ],
        # Soft geometric rounded face — the look most Reels/Shorts captions use.
        # Nunito is downloaded into /app/fonts at image build; Arial Rounded is the
        # macOS local-dev fallback.
        "rounded": [
            ("/System/Library/Fonts/Supplemental/Arial Rounded Bold.ttf", 0),
            ("/app/fonts/Nunito.ttf", 0),
            ("/app/fonts/Poppins-SemiBold.ttf", 0),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
        ],
    }
    for path, idx in candidates.get(kind, []):
        if Path(path).exists() and _looks_like_font(path):
            return [path, idx]
    # Return first even if not found — will fail at render with a clear message
    first = candidates.get(kind, [("/tmp/missing.ttf", 0)])[0]
    return list(first)


# ── Job logging ────────────────────────────────────────────────────────────────

def _log(job_path: Path, msg: str):
    job = json.loads(job_path.read_text())
    job.setdefault("log", []).append({"time": datetime.now().isoformat(), "msg": msg})
    job_path.write_text(json.dumps(job, indent=2))
    print(f"[pipeline] {msg}", flush=True)


def _set_status(job_path: Path, status: str):
    job = json.loads(job_path.read_text())
    job["status"] = status
    job_path.write_text(json.dumps(job, indent=2))


def _check_cancelled(job_path: Path):
    job = json.loads(job_path.read_text())
    if job.get("cancelled"):
        raise RuntimeError("__CANCELLED__")
    started = job.get("started_at")
    if started and (time.time() - started) > MAX_JOB_MINUTES * 60:
        raise RuntimeError(f"__TIMEOUT__: job exceeded {MAX_JOB_MINUTES}-minute limit")


# ── Mock transcription (for local testing without ElevenLabs) ─────────────────

def _mock_transcribe(video: Path, edit_dir: Path) -> Path:
    """
    Generate a fake transcript for pipeline testing.
    Uses ffprobe to get real duration, then fills it with plausible word timestamps.
    """
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(video)],
        capture_output=True, text=True,
    )
    duration = float(result.stdout.strip() or "10.0")

    vocab = ["this", "is", "a", "test", "video", "for", "the", "editing", "pipeline",
             "hello", "world", "speaking", "now", "content", "goes", "here", "great"]
    words = []
    t, i = 0.5, 0
    while t < duration - 1.5:
        end = round(t + 0.28, 3)
        words.append({
            "text":       vocab[i % len(vocab)],
            "type":       "word",
            "start":      round(t, 3),
            "end":        end,
            "speaker_id": "speaker_0",
        })
        t = round(end + 0.12, 3)
        i += 1

    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out = transcripts_dir / f"{video.stem}.json"
    out.write_text(json.dumps(
        {"words": words, "text": " ".join(w["text"] for w in words)},
        indent=2,
    ))
    return out


# ── Script runner ──────────────────────────────────────────────────────────────

def _run(script: str, *args: str, timeout: int = 1800) -> str:
    env = {**os.environ, "ELEVENLABS_API_KEY": os.environ.get("ELEVENLABS_API_KEY", "")}
    try:
        result = subprocess.run(
            [sys.executable, str(EDITOR_DIR / script), *args],
            capture_output=True, text=True, env=env,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"{script} timed out after {timeout // 60} minutes — process killed")
    if result.returncode != 0:
        raise RuntimeError(f"{script} failed:\n{(result.stderr or result.stdout)[-3000:]}")
    return result.stdout


# ── AI feature planning ────────────────────────────────────────────────────────

def _resp_text(resp) -> str:
    """Extract concatenated text from an Anthropic response, skipping thinking blocks."""
    parts = []
    for block in resp.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
        elif hasattr(block, "text"):
            parts.append(block.text)
    return "".join(parts).strip()


def _full_transcript(source_map: dict) -> str:
    all_words = []
    for s in source_map.values():
        if s["trans"].exists():
            tr = json.loads(s["trans"].read_text())
            all_words += [w.get("text", "") for w in tr.get("words", []) if w.get("type") == "word"]
    return " ".join(all_words).strip()


def _interpret_directives(spec: str, anthropic_key: str, log_fn) -> dict:
    """Turn the client's free-text 'Specific Instructions' (hard rules that must
    ALWAYS be obeyed) into concrete, highest-priority editing overrides."""
    spec = (spec or "").strip()
    if not spec:
        return {}
    import anthropic as ant
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=4)
    system = (
        "You convert a client's MANDATORY editing rules into concrete overrides. These rules "
        "OUTRANK every other setting. Only fill a field when the rules clearly require it; otherwise null.\n"
        "Return STRICT JSON only:\n"
        "{\n"
        '  "caption_color": "#RRGGBB hex if a caption/subtitle colour is mandated (e.g. only red -> #FF0000), else null",\n'
        '  "highlight_color": "#RRGGBB hex if the emphasised/keyword word colour is mandated, else null",\n'
        '  "caption_size": "small | medium | large | null",\n'
        '  "grade_warmth": "warmer | cooler | neutral | null",\n'
        '  "grade_contrast": "low | normal | high | null",\n'
        '  "grade_saturation": "muted | normal | vivid | null",\n'
        '  "hook": "force (always add a hook) | off (never add a hook) | null",\n'
        '  "zoom": "force | off | null",\n'
        '  "broll": "off (never add b-roll) | null",\n'
        '  "notes": "any other must-follow guidance, short, that should steer the hook/wording/style, else empty string"\n'
        "}\n"
        "Map colour names to hex (red #FF0000, blue #1E90FF, green #22C55E, yellow #FBBF24, white #FFFFFF, "
        "black #000000, orange #F97316). If a specific hex is given, use it exactly."
    )
    try:
        resp = sdk.messages.create(
            model="claude-sonnet-5", max_tokens=500, system=system,
            messages=[{"role": "user", "content": f"Client's mandatory rules:\n{spec}\n\nJSON overrides:"}],
        )
        raw = _resp_text(resp)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        directives = json.loads(m.group()) if m else {}
        # keep only meaningful values
        directives = {k: v for k, v in directives.items() if v not in (None, "", "null")}
        if directives:
            log_fn(f"AI: specific instructions applied (highest priority): {', '.join(directives.keys())}")
        return directives
    except Exception as e:
        log_fn(f"AI: could not interpret specific instructions ({e}) — proceeding without them")
        return {}


# The graphic templates the Remotion engine can render (Hook is handled separately).
_GRAPHIC_TEMPLATES = ("ListCard", "Stat", "LowerThird", "QuoteCard", "Comparison",
                      "SubscribePrompt", "Callout", "Counter", "Emphasis",
                      "Steps", "Checklist", "ProgressBar", "KeyTakeaway", "Definition",
                      "Warning", "PriceCard", "Testimonial", "Countdown", "Divider",
                      "QuestionCard", "SharePrompt", "SwipeUp", "CommentPrompt", "SaveThis",
                      "Takeover", "Lottie")


def _lottie_catalog() -> list:
    """The Lottie animation library the model may choose from. Reads the manifest at
    remotion/public/lottie/index.json -> [{file, description, keywords}]. Empty if none,
    which omits the Lottie option from the plan entirely (so no file can be invented)."""
    try:
        rd = os.environ.get("REMOTION_DIR") or str(Path(__file__).resolve().parent.parent / "remotion")
        idx = Path(rd) / "public" / "lottie" / "index.json"
        if not idx.exists():
            return []
        data = json.loads(idx.read_text())
        out = []
        for fn, meta in (data.items() if isinstance(data, dict) else []):
            if not str(fn).lower().endswith(".json") or str(fn).lower() == "index.json":
                continue
            m = meta if isinstance(meta, dict) else {}
            out.append({"file": str(fn),
                        "description": str(m.get("description", "")),
                        "keywords": [str(k).lower() for k in (m.get("keywords") or [])]})
        return out
    except Exception:
        return []


def _generate_edit_plan(source_map: dict, instructions: str, client: dict,
                        anthropic_key: str, log_fn) -> dict:
    """One Claude call turns per-video instructions + transcript into a concrete plan.

    This is the personalization layer — every video gets its own plan from ITS
    instructions, so no two edits are templated the same.

    Returns:
      {
        "hook": {"text": str, "start_sec": float, "duration_sec": float} | None,
        "keywords": [str, ...],          # words to emphasize in captions
        "zoom": {"enabled": bool, "strength": float},
        "zoom_events": [{"at": float, "duration": float, "strength": float}, ...]
      }
    """
    plan = {"hook": None, "keywords": [], "zoom": {"enabled": False, "strength": 0.08},
            "zoom_events": [], "graphics": []}
    transcript = _full_transcript(source_map)
    if not transcript:
        return plan

    # On-screen motion-graphic cards are only offered when this instance has the
    # Remotion engine enabled — otherwise the model must not propose graphics that
    # cannot render.
    graphics_on = os.environ.get("REMOTION_GRAPHICS") == "1"
    _lot = _lottie_catalog() if graphics_on else []
    graphics_schema = (
        ',\n  "graphics": [   // OPTIONAL on-screen cards; add 0-3 only where they clearly help\n'
        '    {"template": "one of the template names listed in the graphics rules below", "quote": "2-5 word EXACT phrase from the transcript where it appears", "duration_sec": 3.0, "props": { }}\n'
        '  ]'
    ) if graphics_on else ""
    _lot_rule = ""
    if _lot:
        _lot_lines = "\n".join(
            f'      - "{c["file"]}": {c["description"]} (keywords: {", ".join(c["keywords"])})' for c in _lot)
        _lot_rule = (
            '  * Lottie — an animated motion graphic from the LIBRARY below; choose ONLY when a file\'s keywords '
            'clearly match the spoken concept. props: {"file": "<EXACT filename from the LIBRARY>"}.\n'
            "    LOTTIE LIBRARY (only these files exist):\n" + _lot_lines + "\n"
        )
    graphics_rules = (
        "\n- graphics: on-screen motion-graphics, each anchored to a spoken moment by an EXACT short "
        "quote from the transcript. Add graphics GENEROUSLY — 3 to 6 across a normal video wherever a "
        "moment could land harder: a list, a number, a key line, a name, a comparison, a definition, a "
        "call to action. ERR TOWARD INCLUDING a graphic: the editor removes any extra in one click, so a "
        "useful-but-imperfect graphic is better than a bare stretch. Just never put one on every single "
        "line and never stack two back to back.\n"
        "There are TWO kinds, and this is the most important choice. A TAKEOVER fills the WHOLE screen "
        "(the video cuts to an animated brand-coloured background and the content sits on it, nothing over "
        "the speaker). An OVERLAY card sits on top of the live video. Overlay cards look BAD when they land "
        "on the speaker's face or on the captions, so:\n"
        "  - Whenever the speaker NAMES SEVERAL THINGS in a row (e.g. 'magnesium, aromatherapy, hormones, a "
        "night routine'), or delivers a list / set of steps / a key statement, use a TAKEOVER — never a "
        "small card. Put EACH thing she names as its own item, and set duration_sec to roughly how long she "
        "keeps talking about them (up to 8 seconds) so the list BUILDS ON SCREEN as she speaks each one.\n"
        "  - Reserve overlay cards for a quick single beat (one number, one short callout) that genuinely "
        "reads fine tucked in a corner or the very top. When in real doubt, choose the Takeover.\n"
        "Pick the template that fits the moment:\n"
        "  * Takeover — the DEFAULT for any list, steps, comparison, key statement, or anything the speaker "
        "talks through for more than a moment. Full-screen animated brand background, the content builds on "
        "it as she speaks. "
        'props: {"kicker": "optional 1-3 word label like FOR BETTER SLEEP, or omit", "title": "the headline, a few words", "items": ["each thing she names, 2-5 SHORT words each — omit only for a single-statement takeover"]}.\n'
        "  * ListCard — a small overlay list over the live video (use Takeover instead when the speaker "
        "fills the frame). props: {\"title\": \"optional short header or omit\", \"items\": [\"2-5 SHORT lines, 2-5 words each\"]}.\n"
        "  * Stat — when the speaker states a striking number/metric worth spotlighting. "
        'props: {"value": "90%" or "10x" or "$1.4B", "label": "short caption of what it means"}.\n'
        "  * LowerThird — to name a person or brand the first time they are introduced. "
        'props: {"name": "the name", "subtitle": "role or tagline"}.\n'
        "  * QuoteCard — for a memorable line, as a pull-quote. "
        'props: {"quote": "the sentence in normal sentence case", "attribution": "who said it, or omit"}.\n'
        "  * Comparison — when the speaker contrasts two sides (before vs after, myth vs truth). "
        'props: {"leftLabel": "MYTH or BEFORE", "leftText": "short", "rightLabel": "TRUTH or AFTER", "rightText": "short"}.\n'
        "  * SubscribePrompt — if the speaker asks viewers to follow/subscribe; at most once, on that ask. "
        'props: {"text": "SUBSCRIBE" or "FOLLOW", "handle": "OMIT unless the speaker actually states their real handle — NEVER invent a placeholder like @yourhandle"}.\n'
        "  * Callout — to punch one short, quotable spoken phrase (3-6 words) onto the screen. "
        'props: {"text": "the exact short phrase, in the transcript language"}.\n'
        "  * Counter — when a specific number lands harder counting up (followers, revenue, %, days). "
        'props: {"value": "10,000" or "87%" or "$1.4B", "label": "short caption of what it counts"}.\n'
        "  * Emphasis — to circle / underline / point at one specific thing the speaker calls out on screen. "
        'props: {"mode": "circle" or "underline" or "arrow", "cx": 0.5, "cy": 0.5}  // cx,cy = 0..1 position on the frame.\n'
        "  * Steps — when the speaker lays out an ordered process (first, then, finally). "
        'props: {"title": "optional", "steps": ["2-4 short ordered steps"]}.\n'
        "  * Checklist — for a short set of must-do / must-have items to tick off. "
        'props: {"title": "optional", "items": ["2-5 short items"]}.\n'
        "  * ProgressBar — when a single proportion or percentage is the point (a share, a completion rate). "
        'props: {"label": "what it measures", "value": "72%" or "7/10", "caption": "optional note"}.\n'
        "  * KeyTakeaway — to lock in the one thing to remember. "
        'props: {"label": "optional, defaults KEY TAKEAWAY", "text": "the one line"}.\n'
        "  * Definition — when the speaker defines a term or piece of jargon. "
        'props: {"term": "the term", "definition": "a short plain explanation"}.\n'
        "  * Warning — to flag a mistake or thing to avoid. "
        'props: {"label": "optional, defaults WATCH OUT", "text": "the pitfall, short"}.\n'
        "  * PriceCard — when a price or offer is stated. "
        'props: {"price": "$49", "was": "optional old price", "label": "optional e.g. TODAY ONLY", "cta": "optional"}.\n'
        "  * Testimonial — for a customer or result quote used as social proof. "
        'props: {"quote": "short quote", "name": "optional", "role": "optional", "stars": 5}.\n'
        "  * Countdown — for genuine urgency or a deadline the speaker states. "
        'props: {"label": "optional e.g. ENDS IN", "value": "24:00:00" or "3 DAYS"}.\n'
        "  * Divider — to mark a clear new section or chapter of the video. "
        'props: {"text": "the section title", "kicker": "optional e.g. PART 2"}.\n'
        "  * QuestionCard — to put a direct question to the viewer on screen. "
        'props: {"question": "the question"}.\n'
        "  * SharePrompt — for a like/comment/share nudge (a specific subscribe ask uses SubscribePrompt). At most once. "
        'props: {"text": "optional", "handle": "OMIT unless the speaker states their real handle — NEVER invent one"}.\n'
        "  * SwipeUp — when pointing to a link in bio or swipe up. At most once. "
        'props: {"text": "optional, defaults LINK IN BIO"}.\n'
        "  * CommentPrompt — when the speaker asks viewers to comment a specific word. "
        'props: {"word": "the word to comment, e.g. YES"}.\n'
        "  * SaveThis — when the content is a reference worth saving. At most once. "
        'props: {"text": "optional, defaults SAVE THIS"}.\n'
        "  Write the props text in the SAME language as the transcript. duration_sec 2.5-4. Aim for at least "
        "one card on a normal video.\n"
        + _lot_rule
    ) if graphics_on else ""

    # Highest-priority: the client's mandatory specific instructions
    spec = (client.get("specific_instructions") or "").strip()
    brand_voice = ""
    if spec:
        brand_voice += ("\n\nMANDATORY CLIENT RULES (highest priority — obey these over everything, "
                        f"including the instructions above):\n{spec}\n")

    # Brand voice from the client's onboarding doc — shapes the generated hook
    tone        = client.get("tone", [])
    words_favor = client.get("words_favor", [])
    words_avoid = client.get("words_avoid", [])
    if tone or words_favor or words_avoid:
        brand_voice = "\n\nBRAND VOICE (respect this in the hook and keyword choices):\n"
        if tone:        brand_voice += f"  - Tone: {', '.join(tone)}\n"
        if words_favor: brand_voice += f"  - Favor these on-brand words/phrases when they fit naturally: {', '.join(words_favor)}\n"
        if words_avoid: brand_voice += f"  - NEVER use these words/phrases in the hook (off-brand, banned): {', '.join(words_avoid)}\n"

    # Style profile from an analyzed reference clip — guides hook energy / movement
    style = client.get("style_profile") or {}
    if style.get("summary"):
        brand_voice += ("\nREFERENCE STYLE to match (from a clip the creator likes): "
                        f"{style.get('summary')} "
                        f"(energy: {style.get('energy','')}, pacing: {style.get('pacing','')}). "
                        "Let this steer the hook's punchiness and whether a zoom/movement fits.\n")

    import anthropic as ant
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=4)
    system = (
        "You are a senior short-form video editor. Read the creator's per-video instructions "
        "and the transcript, then output a concrete edit plan as STRICT JSON (no prose).\n\n"
        "Schema:\n"
        "{\n"
        '  "hook": null OR {\n'
        '    "text": "3-6 word scroll-stopping hook in ALL CAPS, derived from the actual content",\n'
        '    "start_sec": 0,\n'
        '    "duration_sec": 6   // how long the hook stays on screen (5-8 typical); it pops in then out\n'
        "  },\n"
        '  "keywords": ["the","most","important","content","words","to","emphasize"],\n'
        '  "zoom": {"enabled": true/false, "strength": 0.06-0.12},\n'
        '  "zoom_events": [{"at": 8.0, "duration": 2.5, "strength": 0.12}]  // timestamped punch-ins'
        + graphics_schema +
        "\n}\n\n"
        "Rules:\n"
        "- LANGUAGE: write the hook and pick the keywords in the SAME language the speaker uses "
        "in the transcript (e.g. a Danish video gets a Danish hook and Danish keywords). Never translate to English.\n"
        "- Only include a hook if the instructions ask for one (hook / text / title). Otherwise null.\n"
        "- keywords: pick the 15-30 highest-impact CONTENT words across the whole script "
        "(nouns, verbs, numbers, names). These get highlighted as they appear in captions. "
        "Skip filler and function words. Lowercase them.\n"
        "- zoom.enabled is the SLOW global push-in across the whole video — only if the instructions ask "
        "for general movement/energy with no specific time.\n"
        "- zoom_events are SPECIFIC punch-in-and-hold moments. Whenever the instructions name a time "
        "(\"zoom at 8 seconds\", \"punch in at 0:12\", \"zoom when I say the price\"), add an event with "
        "\"at\" = that time in SECONDS from the start of the FINAL video (convert mm:ss to seconds), "
        "\"duration\" 1.5-3.5 (how long it holds, default 2.5), \"strength\" 0.08-0.15 (default 0.12). "
        "List every distinct time mentioned. If no specific time is mentioned, leave zoom_events empty [].\n"
        "- Respect the instructions literally. If they say no hook, hook=null. If they don't mention zoom, zoom.enabled=false and zoom_events=[]."
        + graphics_rules
        + brand_voice
    )
    try:
        resp = sdk.messages.create(
            model="claude-sonnet-5",
            max_tokens=1200,
            system=system,
            messages=[{"role": "user",
                       "content": f'Instructions: "{instructions}"\n\nTranscript:\n{transcript[:6000]}\n\nJSON plan:'}],
        )
        raw = _resp_text(resp)
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group())
            if isinstance(parsed.get("hook"), dict) and parsed["hook"].get("text"):
                h = parsed["hook"]
                plan["hook"] = {
                    "text": str(h["text"]).upper().strip(),
                    "start_sec": float(h.get("start_sec", 0) or 0),
                    "duration_sec": float(h.get("duration_sec", 6) or 6),
                }
            plan["keywords"] = [str(k).lower().strip() for k in parsed.get("keywords", []) if str(k).strip()]
            z = parsed.get("zoom", {})
            plan["zoom"] = {
                "enabled": bool(z.get("enabled")),
                "strength": max(0.04, min(0.15, float(z.get("strength", 0.08) or 0.08))),
            }
            evs = []
            for e in (parsed.get("zoom_events") or []):
                try:
                    evs.append({
                        "at":       max(0.0, float(e.get("at", 0) or 0)),
                        "duration": max(0.8, min(6.0, float(e.get("duration", 2.5) or 2.5))),
                        "strength": max(0.06, min(0.30, float(e.get("strength", 0.12) or 0.12))),
                    })
                except (TypeError, ValueError):
                    continue
            plan["zoom_events"] = evs
            if graphics_on:
                gs = []
                for g in (parsed.get("graphics") or []):
                    if not isinstance(g, dict):
                        continue
                    t = str(g.get("template", "")).strip()
                    if t not in _GRAPHIC_TEMPLATES:
                        continue
                    props = g.get("props") if isinstance(g.get("props"), dict) else {}
                    if t == "Lottie" and not any(str(props.get("file", "")).strip() == c["file"] for c in _lot):
                        continue   # Lottie must name a real library file — never invent one
                    if t in ("SubscribePrompt", "SharePrompt"):
                        # Never burn a made-up placeholder handle like "@yourhandle" into
                        # the video — the model invents one when it doesn't know the real
                        # handle. Keep it only when it looks like a genuine handle.
                        _hl = str(props.get("handle", "")).strip().lower().lstrip("@")
                        if (not _hl) or ("your" in _hl) or _hl in (
                                "handle", "username", "name", "channel", "account", "profile"):
                            props.pop("handle", None)
                    try:
                        dur = max(1.5, min(8.0, float(g.get("duration_sec", 3.0) or 3.0)))
                        at  = float(g.get("at_sec", 0) or 0)
                    except (TypeError, ValueError):
                        dur, at = 3.0, 0.0
                    gs.append({"template": t, "quote": str(g.get("quote", "")).strip(),
                               "at_sec": at, "duration_sec": dur, "props": props})
                plan["graphics"] = gs[:6]   # generous cap — the editor prunes extras in one click
        log_fn(f"AI plan: hook={'yes' if plan['hook'] else 'no'}, "
               f"{len(plan['keywords'])} keyword(s), zoom={plan['zoom']['enabled']}, "
               f"{len(plan['zoom_events'])} timed zoom(s), {len(plan['graphics'])} graphic(s)")
    except Exception as e:
        log_fn(f"AI plan generation failed ({e}) — using safe defaults")
    return plan


def _speaker_words(transcript: dict, speaker: str | None) -> list:
    """Canonical on-camera word list — MUST be identical everywhere indices are shared."""
    return [
        w for w in transcript.get("words", [])
        if w.get("type") == "word"
        and w.get("start") is not None
        and (speaker is None or w.get("speaker_id") == speaker)
    ]


def _identify_filler_words(source_map: dict, speaker: str | None,
                           anthropic_key: str, log_fn, script: str = "") -> dict:
    """Ask Claude which word indices are pure filler / false starts to cut.

    Returns {source_name: set(indices)} aligned to _speaker_words() ordering.
    Conservative by design — only clear fillers, never content words.

    When `script` (the words the client meant to say) is given, it is used as
    ground truth: a hesitation or false start is simply a spoken word that is not
    in the script. This makes the cut reliable in ANY language (e.g. Danish 'øh')
    without having to enumerate every language's fillers.
    """
    import anthropic as ant
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=4)
    result: dict[str, set] = {}
    script = (script or "").strip()
    has_script = bool(script)
    if has_script:
        log_fn("filler: using the provided script as ground truth for a clean, language-safe cut")

    for name, s in source_map.items():
        if not s["trans"].exists():
            continue
        transcript = json.loads(s["trans"].read_text())
        words = _speaker_words(transcript, speaker)
        if not words:
            continue

        numbered = "\n".join(
            f"[{i}] {w.get('text','')}" for i, w in enumerate(words)
        )
        system = (
            "You are a precise video editor removing filler from a talking-head transcript.\n"
            "The transcript may be in ANY language — detect its language and remove that "
            "language's fillers. Return ONLY a JSON array of integer word indices to DELETE. No prose.\n\n"
            "DELETE these (be thorough), in whatever language the speaker uses:\n"
            "  - Filler sounds: English um, uh, er, ah, hmm, mm, eh · Danish øh, øhm, æh, hmm\n"
            "  - Filler words / verbal tics that add NO meaning:\n"
            "      English: 'like', 'you know', 'I mean', 'basically', 'literally', 'sort of', 'kind of'\n"
            "      Danish:  'altså', 'ligesom', 'jo', 'sådan', 'ikke også', 'jamen', 'nå', 'hva' "
            "(only when used as empty verbal tics, not when meaningful)\n"
            "  - Stutters / repeated words: 'the the', 'jeg jeg', 'og-og'\n"
            "  - False starts: an abandoned phrase restarted a different way (delete the abandoned words only)\n\n"
            "NEVER delete:\n"
            "  - Words that carry meaning, even if casual\n"
            "  - A filler word when it is actually meaningful (e.g. Danish 'ikke' as a real negation, "
            "'like' as a comparison)\n"
            "  - A word if deleting it makes the sentence ungrammatical\n\n"
            "When unsure, KEEP the word. Precision over aggression."
        )
        if has_script:
            system += (
                "\n\nGROUND TRUTH — THE INTENDED SCRIPT:\n"
                "You are also given the SCRIPT the speaker meant to say. Treat it as the source of "
                "truth for what belongs in the video. In any language, a hesitation or false start is "
                "simply a spoken run of words that is NOT in the script.\n"
                "  - DELETE spoken words that are absent from the script AND are clearly hesitations, "
                "filler sounds, stutters, or false starts.\n"
                "  - KEEP the spoken words that match the script, even loosely — spelling, accents "
                "and punctuation do not matter.\n"
                "  - The speaker may paraphrase or ad-lib REAL content that is not word-for-word in the "
                "script. Never delete genuine content just because it differs from the script; only "
                "remove true hesitations, filler and false starts.\n\n"
                "RETAKES — THE KEY CASE, GET THIS RIGHT:\n"
                "Speakers often record the SAME scripted line several times in a row until they get it "
                "right, usually with a spoken aside in between ('no wait', 'let me take that again', "
                "'take two', 'sorry', 'again', 'øh nej', 'lige igen'). When the same scripted line "
                "appears more than once in the transcript:\n"
                "  - KEEP ONLY THE LAST complete, clean delivery of that line.\n"
                "  - DELETE every earlier attempt of it, in full (the whole run of words, not just parts).\n"
                "  - DELETE any aside or self-direction spoken between the attempts — it is never in the script.\n"
                "So every scripted line ends up in the finished video EXACTLY ONCE.\n"
                "Worked example — SCRIPT line: 'This is how you get big biceps.'\n"
                "  Transcript: yeah oh so this is how you get big biceps  oh no shit I want to take that "
                "again  oh this is how you get big biceps\n"
                "  DELETE the entire first attempt ('yeah oh so this is how you get big biceps') AND the "
                "aside ('oh no shit I want to take that again').\n"
                "  KEEP only the final clean delivery ('this is how you get big biceps', trimming its "
                "leading filler 'oh'). The line now appears once, matching the script.\n"
                "Precision over aggression still holds for real content, but a repeated take is NOT real "
                "content — remove it."
            )
        user_content = f"Transcript words:\n{numbered}\n\nJSON array of indices to delete:"
        if has_script:
            user_content = (f"Transcript words:\n{numbered}\n\n"
                            f"The intended SCRIPT (ground truth):\n\"\"\"\n{script[:8000]}\n\"\"\"\n\n"
                            "JSON array of indices to delete:")
        try:
            resp = sdk.messages.create(
                model="claude-sonnet-5",
                max_tokens=2000,
                system=system,
                messages=[{"role": "user", "content": user_content}],
            )
            raw = _resp_text(resp)
            m = re.search(r'\[[\d,\s]*\]', raw)
            idxs = set(int(x) for x in json.loads(m.group())) if m else set()
            # Guard against a runaway model. WITHOUT a script, cap deletions at 30%
            # of words. WITH a script, heavy deletion is often CORRECT — three
            # retakes of every line removes two thirds of the footage — so a flat
            # cap would wrongly block it. Instead, check the cut still leaves
            # roughly the script's worth of words; only reject a cut that leaves
            # far LESS than the script (a sign the model mis-aligned).
            if has_script:
                script_words = len(re.findall(r"[^\W\d_]+|\d+", script, flags=re.UNICODE))
                kept = len(words) - len(idxs)
                too_aggressive = script_words > 0 and kept < 0.45 * script_words
                guard_desc = f"kept {kept} words vs script's ~{script_words}"
            else:
                too_aggressive = len(idxs) > 0.30 * len(words)
                guard_desc = f"{len(idxs)}/{len(words)} words over 30%"
            if too_aggressive:
                log_fn(f"filler: cut looks wrong ({guard_desc}) — skipping it for {name} to stay safe")
                idxs = set()
            result[name] = idxs
            if idxs:
                cut_preview = ", ".join(words[i].get("text", "") for i in sorted(idxs)[:12])
                log_fn(f"filler: {name} — cutting {len(idxs)} filler word(s): {cut_preview}{'...' if len(idxs) > 12 else ''}")
            else:
                log_fn(f"filler: {name} — no filler words identified")
        except Exception as e:
            log_fn(f"filler: identification failed for {name} ({e}) — keeping all words")
            result[name] = set()

    return result


def _plan_cuts(source_map: dict, speaker: str | None,
               anthropic_key: str, log_fn, script: str = "") -> list:
    """Claude drives the real edit: it removes whole BAD TAKES as source-time spans.

    The filler pass above snips scattered 'um/øh' words; this pass handles the
    thing that actually makes a raw recording unwatchable — the speaker recording
    the same line two or three times in a row, false starts, and off-topic asides.
    It reads the on-camera transcript (and the intended SCRIPT as ground truth when
    present) and returns [{source, start, end, reason}] in each clip's OWN source
    time. Those spans are applied by _apply_cut_spans — the exact, proven machinery
    the manual Studio "cut this bit out" uses — so an AI cut is as reliable and as
    re-render-stable as a hand cut.

    Returning contiguous WORD ranges that we convert to source time (rather than
    asking the model for raw float seconds, or scattered word indices) is what
    makes it robust: the model only has to point at the first and last word of a
    bad take, and we derive an exact, clampable time span from the transcript we
    already trust.
    """
    if os.environ.get("AI_CUT_ENGINE", "1").strip() in ("0", "false", "off", "no"):
        return []
    script = (script or "").strip()
    has_script = bool(script)
    all_spans: list = []

    system = (
        "You are a senior video editor cutting a raw talking-head recording down to the "
        "clean final take. The transcript may be in ANY language — work in whatever "
        "language the speaker uses.\n\n"
        "Your ONLY job here is to remove whole bad TAKES and dead weight, by pointing at "
        "the first and last word of each run to delete. Remove:\n"
        "  - RETAKES: the speaker records the SAME line more than once (to get it right). "
        "Keep ONLY the LAST clean, complete delivery; delete every earlier attempt of that "
        "line IN FULL.\n"
        "  - ASIDES / SELF-DIRECTION between takes: 'no wait', 'let me do that again', "
        "'take two', 'sorry', 'again', 'øh nej', 'lige igen', 'vent'. Always delete these.\n"
        "  - FALSE STARTS: an abandoned phrase the speaker restarts a different way (delete "
        "the abandoned run only).\n"
        "  - Clear off-topic TANGENTS that are not part of the message.\n\n"
        "Do NOT try to remove single filler sounds here — a separate pass handles those. "
        "NEVER delete real content, and never delete so much that the message stops making "
        "sense. When unsure whether something is a genuine retake, KEEP it.\n\n"
        "Return STRICT JSON only, no prose:\n"
        '{"cuts": [{"start_word": <int index>, "end_word": <int index, inclusive>, '
        '"reason": "retake|aside|false_start|tangent"}]}\n'
        "Each cut is a contiguous run of word indices to delete. If nothing should be cut, "
        'return {"cuts": []}.'
    )
    if has_script:
        system += (
            "\n\nGROUND TRUTH — THE INTENDED SCRIPT:\n"
            "You are given the SCRIPT the speaker meant to say. Treat it as the truth for "
            "what belongs in the finished video. A retake is any scripted line that appears "
            "in the transcript more than once — keep the LAST clean delivery, delete the rest. "
            "Every scripted line must end up in the video EXACTLY ONCE.\n"
            "Worked example — SCRIPT line: 'This is how you get big biceps.'\n"
            "  Transcript: yeah oh so this is how you get big biceps  oh no shit I want to take "
            "that again  oh this is how you get big biceps\n"
            "  Delete the entire first attempt AND the aside 'oh no shit I want to take that "
            "again'. Keep only the final clean delivery, so the line appears once.\n"
            "The speaker may paraphrase or ad-lib REAL content that is not word-for-word in the "
            "script — never delete genuine content just because it differs from the script."
        )

    for name, s in source_map.items():
        if not s["trans"].exists():
            continue
        words = _speaker_words(json.loads(s["trans"].read_text()), speaker)
        if len(words) < 4:
            continue
        numbered = "\n".join(f"[{i}] {w.get('text','')}" for i, w in enumerate(words))
        user_content = f"Transcript words:\n{numbered}\n\n"
        if has_script:
            user_content += f"The intended SCRIPT (ground truth):\n\"\"\"\n{script[:8000]}\n\"\"\"\n\n"
        user_content += 'JSON of the runs to delete (object with a "cuts" array):'

        raw = ""
        for model in ("claude-opus-5", "claude-sonnet-5"):
            try:
                import anthropic as ant
                sdk = ant.Anthropic(api_key=anthropic_key, timeout=180.0, max_retries=3)
                # Stream: adaptive thinking (best for the retake reasoning) plus a
                # generous cap needs streaming to dodge the SDK's timeout guard.
                with sdk.messages.stream(
                    model=model,
                    max_tokens=16000,
                    thinking={"type": "adaptive"},
                    system=system,
                    messages=[{"role": "user", "content": user_content}],
                ) as stream:
                    raw = _resp_text(stream.get_final_message())
                break
            except Exception as e:
                if model == "claude-opus-5":
                    log_fn(f"cut engine: Opus unavailable ({str(e)[:80]}), trying Sonnet")
                    continue
                log_fn(f"cut engine: planning failed for {name} ({str(e)[:100]}) — no AI cuts on this clip")
                raw = ""

        cuts = []
        try:
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if m:
                cuts = (json.loads(m.group()) or {}).get("cuts") or []
        except Exception:
            cuts = []

        spans, removed = [], 0
        for c in cuts:
            if not isinstance(c, dict):
                continue
            try:
                i0 = int(c["start_word"]); i1 = int(c["end_word"])
            except (KeyError, TypeError, ValueError):
                continue
            i0 = max(0, min(i0, len(words) - 1))
            i1 = max(0, min(i1, len(words) - 1))
            if i1 < i0:
                i0, i1 = i1, i0
            t0 = float(words[i0]["start"]) - 0.03
            t1 = float(words[i1].get("end", words[i1]["start"])) + 0.03
            if t1 <= t0:
                continue
            spans.append({"source": name, "start": round(max(0.0, t0), 3),
                          "end": round(t1, 3), "reason": str(c.get("reason", "cut"))[:20]})
            removed += (i1 - i0 + 1)

        # Bound the blast radius. WITH a script, heavy removal is legitimate (three
        # takes of every line keeps only a third) — so validate against the script's
        # length, exactly like the filler guard, not against a flat percentage. WITHOUT
        # a script, retake detection is far less certain, so cap removal conservatively.
        kept = len(words) - removed
        if has_script:
            script_words = len(re.findall(r"[^\W\d_]+|\d+", script, flags=re.UNICODE))
            too_aggressive = script_words > 0 and kept < 0.45 * script_words
            guard = f"kept {kept} words vs script's ~{script_words}"
        else:
            too_aggressive = removed > 0.45 * len(words)
            guard = f"removed {removed}/{len(words)} words"
        if too_aggressive:
            log_fn(f"cut engine: cut looks too heavy ({guard}) — skipping it for {name} to stay safe")
            continue
        if spans:
            reasons = ", ".join(sorted({sp["reason"] for sp in spans}))
            log_fn(f"cut engine: {name} — removing {len(spans)} bad take(s) [{reasons}], "
                   f"{removed} word(s) of {len(words)}")
            all_spans += spans
        else:
            log_fn(f"cut engine: {name} — no retakes or false starts found")

    return all_spans


# ── B-roll AI matching ───────────────────────────────────────────────────────

def _extract_frame(video: Path, out_jpg: Path, t: float | None = None):
    args = ["ffmpeg", "-y", "-v", "error"]
    if t is not None:
        args += ["-ss", f"{t:.2f}"]
    args += ["-i", str(video), "-frames:v", "1", "-vf", "scale=640:-1", "-q:v", "4", str(out_jpg)]
    subprocess.run(args, check=True, timeout=60)


def _detect_active_span(clip: Path, dur: float):
    """Find the ACTIVE (moving) window of a b-roll video via a cheap local motion
    pass, so a cutaway uses the action instead of idle head/tail padding (e.g. a
    training clip that opens on 20s of sitting still). Returns (in_s, out_s) or
    None when there is no clear active region (caller then uses the whole clip).
    Never raises."""
    if not dur or dur <= 0:
        return None
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(clip), "-an",
             "-vf", "scale=64:64,format=gray,tblend=all_mode=difference,signalstats,metadata=print:file=-",
             "-f", "null", "-"],
            capture_output=True, text=True, timeout=90)
        out = r.stdout or ""
    except Exception:
        return None
    series, cur_t = [], None                       # (t, motion), higher = more movement
    for line in out.splitlines():
        m = re.search(r"pts_time:([0-9.]+)", line)
        if m:
            cur_t = float(m.group(1)); continue
        m = re.search(r"lavfi\.signalstats\.YAVG=([0-9.]+)", line)
        if m and cur_t is not None:
            series.append((cur_t, float(m.group(1)))); cur_t = None
    if len(series) < 8:
        return None
    vals = sorted(v for _, v in series)
    n = len(vals); median = vals[n // 2]
    mad = (sorted(abs(v - median) for v in vals)[n // 2]) or 1.0
    thresh = median + 3.0 * mad                     # sustained motion, not flicker
    active = [t for t, v in series if v >= thresh]
    if not active:
        return None
    a_in, a_out = max(0.0, min(active) - 0.3), min(dur, max(active) + 0.3)
    if a_out - a_in < 3.5:                          # too short -> widen around its centre
        c = (a_in + a_out) / 2.0
        a_in, a_out = max(0.0, c - 1.75), min(dur, c + 1.75)
    if a_out <= a_in or a_out - a_in < 1.2:
        return None
    return (round(a_in, 2), round(a_out, 2))


def _broll_tag_key(clip: Path) -> str:
    st = clip.stat()
    return f"{clip.name}:{st.st_size}:{int(st.st_mtime)}"


def read_broll_tags(broll_src: Path, clips: list, cache_dir: Path = None) -> dict:
    """Return {name: tag_info | None} from the cache without re-tagging (for the UI).
    cache_dir (when given) is where the persistent .tags.json lives, separate from
    the working clip folder — used when clips are pulled fresh from Drive each run."""
    cache_path = (cache_dir or broll_src) / ".tags.json"
    cache = {}
    if cache_path.exists():
        try: cache = json.loads(cache_path.read_text())
        except Exception: cache = {}
    return {clip.name: cache.get(_broll_tag_key(clip)) for clip in clips}


def tag_broll_clips(broll_src: Path, clips: list, anthropic_key: str, log_fn, cache_dir: Path = None) -> dict:
    """Vision-tag each B-roll clip so we know what's in it. Cached in .tags.json
    keyed by name+size+mtime so we only pay for the Vision call once per clip.
    cache_dir (when given) keeps that cache on a persistent disk while the clips
    themselves live in an ephemeral working folder (Drive-pulled B-roll)."""
    import anthropic as ant, base64
    cache_dir = cache_dir or broll_src
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / ".tags.json"
    cache = {}
    if cache_path.exists():
        try: cache = json.loads(cache_path.read_text())
        except Exception: cache = {}

    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=4)
    tags: dict = {}
    tmp = broll_src / "_frames"
    tmp.mkdir(exist_ok=True)

    for clip in clips:
        key = _broll_tag_key(clip)
        if key in cache:
            tags[clip.name] = cache[key]
            continue
        try:
            frame = tmp / f"{clip.stem}.jpg"
            _span = None
            # _extract_frame with no seek converts ANY still (jpg/png/webp/heic) to a
            # small jpeg too, so pictures are analysed exactly like a video frame.
            if _is_broll_image(clip):
                _extract_frame(clip, frame, t=None)
                subject = "This is a B-roll photo / still image."
            else:
                dur = 0.0
                try:
                    r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                                        "-of","default=noprint_wrappers=1:nokey=1", str(clip)],
                                       capture_output=True, text=True, timeout=30)
                    dur = float(r.stdout.strip() or 0.0)
                except Exception:
                    pass
                _span = _detect_active_span(clip, dur)   # the moving part of the clip
                _ft = ((_span[0] + _span[1]) / 2.0) if _span else (min(1.0, dur/2) if dur else None)
                _extract_frame(clip, frame, t=_ft)       # describe the ACTION, not the idle head
                subject = "This is a frame from a B-roll video clip."
            b64 = base64.standard_b64encode(frame.read_bytes()).decode()
            resp = sdk.messages.create(
                model="claude-sonnet-5",
                max_tokens=300,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text":
                        subject + " Return STRICT JSON only:\n"
                        '{"description": "one plain sentence of what is shown", '
                        '"keywords": ["6-10 concrete nouns / actions / concepts a script might mention that this clip could illustrate"]}'},
                ]}],
            )
            raw = _resp_text(resp)
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            info = json.loads(m.group()) if m else {"description": "", "keywords": []}
            info["keywords"] = [str(k).lower().strip() for k in info.get("keywords", []) if str(k).strip()]
            if _span:
                info["active_in"], info["active_out"] = _span   # cached with the clip's tags
            tags[clip.name] = info
            cache[key] = info
            log_fn(f"broll tag: {clip.name} — {info.get('description','')[:70]}")
        except Exception as e:
            log_fn(f"broll tag: {clip.name} failed ({e}) — skipping this clip")
            tags[clip.name] = {"description": "", "keywords": []}

    try:
        cache_path.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass
    shutil.rmtree(tmp, ignore_errors=True)
    return tags


def _build_word_timeline(source_map: dict, speaker: str | None, edl: dict) -> list:
    """List of on-camera words in OUTPUT time, matching the final (post-cut) ranges.
    Each entry: {"n": normalized_text, "out": output_start_seconds}."""
    trans_by_src = {}
    for name, s in source_map.items():
        if s["trans"].exists():
            trans_by_src[name] = _speaker_words(json.loads(s["trans"].read_text()), speaker)
    timeline, cum = [], 0.0
    for r in edl["ranges"]:
        ss, se = float(r["start"]), float(r["end"])
        for w in trans_by_src.get(r["source"], []):
            if ss <= w["start"] < se:
                timeline.append({
                    "n": _norm(w.get("text", "")),
                    "out": round((w["start"] - ss) + cum, 3),
                })
        cum += se - ss
    return timeline


def _norm(w: str) -> str:
    return "".join(c for c in w.lower() if c.isalnum())


def _find_quote_time(timeline: list, quote: str) -> float | None:
    """Locate a short quote in the word timeline; return its first word's output time."""
    q = [_norm(x) for x in quote.split() if _norm(x)]
    if not q:
        return None
    nwords = [t["n"] for t in timeline]
    for i in range(len(nwords) - len(q) + 1):
        if nwords[i:i+len(q)] == q:
            return timeline[i]["out"]
    # loose fallback: match just the first distinctive word
    for i, n in enumerate(nwords):
        if n == q[0] and len(q[0]) >= 4:
            return timeline[i]["out"]
    return None


def _apply_cut_spans(ranges: list, cut_spans: list, min_dur: float = 0.3) -> list:
    """Remove SOURCE-time spans from the EDL ranges (Studio 'cut this bit out').

    Each cut is {source, start, end} in the source clip's own timeline, which is
    stable across re-renders. A range that overlaps a cut is trimmed or split; a
    leftover shorter than min_dur is dropped."""
    out = []
    for r in ranges:
        segs = [(float(r["start"]), float(r["end"]))]
        for cs in cut_spans:
            if not isinstance(cs, dict) or cs.get("source") != r.get("source"):
                continue
            try:
                c0, c1 = float(cs["start"]), float(cs["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if c1 <= c0:
                continue
            nxt = []
            for s, e in segs:
                if c1 <= s or c0 >= e:            # no overlap
                    nxt.append((s, e))
                else:
                    if s < c0: nxt.append((s, c0))  # keep the part before the cut
                    if c1 < e: nxt.append((c1, e))  # keep the part after the cut
            segs = nxt
        for s, e in segs:
            if e - s >= min_dur:
                nr = dict(r); nr["start"] = round(s, 3); nr["end"] = round(e, 3)
                out.append(nr)
    return out


def _apply_splits(ranges: list, split_points: list) -> list:
    """Divide EDL ranges at SOURCE-time split points (Studio 'split clip').

    Non-destructive: a split point strictly inside a range breaks it into two
    abutting halves; no footage is removed and no half is dropped. A point at or
    outside a range's edges is a silent no-op. Source coords stay stable across
    re-renders, exactly like cut_spans."""
    if not split_points:
        return ranges
    out = []
    for r in ranges:
        segs = [(float(r["start"]), float(r["end"]))]
        for sp in split_points:
            if not isinstance(sp, dict) or sp.get("source") != r.get("source"):
                continue
            try:
                at = float(sp["at"])
            except (KeyError, TypeError, ValueError):
                continue
            nxt = []
            for s, e in segs:
                if s < at < e:
                    nxt.append((s, at)); nxt.append((at, e))   # abutting halves
                else:
                    nxt.append((s, e))
            segs = nxt
        for s, e in segs:
            nr = dict(r); nr["start"] = round(s, 3); nr["end"] = round(e, 3)
            out.append(nr)
    return out


def _plan_broll(source_map: dict, broll_tags: dict, instructions: str,
                anthropic_key: str, log_fn, desired_count: int | None = None,
                force_cards: bool = False) -> list:
    """Ask Claude where each B-roll clip best illustrates the script.
    Returns [{"file": name, "quote": "...", "duration_sec": float, "style": "card"|"full"}].
    desired_count: exact number of cutaways to return (best-fitting); None = AI decides.
    force_cards: photos always pop up as cards (the AI's per-photo card/full choice is ignored)."""
    transcript = _full_transcript(source_map)
    if not transcript or not broll_tags:
        return []
    import anthropic as ant
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=4)

    catalog = "\n".join(
        f'- "{name}" [{"PHOTO" if _is_broll_image(name) else "VIDEO"}]: '
        f'{info.get("description","")} (keywords: {", ".join(info.get("keywords", []))})'
        for name, info in broll_tags.items()
    )
    has_photos = any(_is_broll_image(n) for n in broll_tags)
    if desired_count and desired_count > 0:
        count_rule = (f"- Place AT MOST {desired_count} cutaway(s) — and ONLY ones that clearly fit. "
                      f"If fewer than {desired_count} strongly match, place fewer (or none). "
                      f"Never pad up to the number with weak matches.\n")
    else:
        count_rule = ("- There is no target number. Place only strong matches, spaced out. Most talking-head "
                      "videos need only a few genuine cutaways — often zero.\n")
    photo_rule = ""
    if has_photos:
        photo_rule = (
            '- "style" applies to PHOTO clips only (VIDEO clips are always full-frame — omit or use "full"):\n'
            '    "card" = the photo snaps up on a small card OVER the speaker (they stay on screen). '
            "Use this when the speaker is listing or pointing to things — "
            "'first the coffee... then the beans... then the machine' — quick punchy BAM inserts that punctuate the words.\n"
            '    "full" = the photo fills the whole screen as a cutaway. Use when the photo IS the moment and the '
            "face isn't needed for a beat (a single strong illustrative image).\n"
            "    Default to \"card\" for punchy list/pointing mentions, \"full\" for one strong standalone image.\n")
    system = (
        "You are a senior video editor placing B-roll cutaways over a talking-head video "
        "(one person speaking to camera). Return STRICT JSON only: a list of placements.\n\n"
        '[{"file": "<exact clip filename>", "quote": "<exact 2-5 word phrase from the transcript where this clip should START>", "duration_sec": 2.5, "style": "card"}]\n\n'
        "THE BAR FOR PLACING A CLIP IS HIGH. Place a clip ONLY when its VISUAL CONTENT literally and "
        "specifically shows the object, action, place, or concept being spoken at that exact moment. "
        "A vague thematic, emotional, or 'kind of related' connection is NOT enough.\n"
        "  GOOD: speaker says 'lifting weights' + clip shows a gym/weights -> place it.\n"
        "  BAD:  speaker says 'boys and girls' + clip is a selfie of a person -> DO NOT place.\n"
        "  BAD:  speaker says 'cutting out dead space' + clip is a generic keyboard -> too loose, DO NOT place.\n\n"
        "HARD RULES:\n"
        "- NEVER use a clip that merely shows a person talking, a face, or a selfie. That is redundant over "
        "talking-head footage and is always wrong as B-roll.\n"
        "- Place a clip wherever its visual content genuinely matches the moment being spoken — use the good "
        "matches in the library, don't leave them on the table. Return [] only when nothing in the library "
        "fits; never force a weak match.\n"
        "- The quote MUST be copied verbatim from the transcript (2-5 consecutive words) so it can be located.\n"
        + count_rule + photo_rule +
        "- duration_sec between 1.5 and 3.5.\n"
        "- A clip may be reused only if it strongly fits multiple distinct moments."
    )
    try:
        resp = sdk.messages.create(
            model="claude-sonnet-5",
            max_tokens=1500,
            system=system,
            messages=[{"role": "user", "content":
                f'Instructions: "{instructions}"\n\nAvailable B-roll clips:\n{catalog}\n\nTranscript:\n{transcript[:6000]}\n\nJSON placements:'}],
        )
        raw = _resp_text(resp)
        m = re.search(r'\[.*\]', raw, re.DOTALL)
        placements = json.loads(m.group()) if m else []
        valid = [p for p in placements if p.get("file") in broll_tags and p.get("quote")]
        log_fn(f"broll plan: {len(valid)} placement(s) proposed")
        return valid
    except Exception as e:
        log_fn(f"broll plan failed ({e}) — no B-roll placed")
        return []


# ── Auto-EDL generation ────────────────────────────────────────────────────────

_DEFAULT_GRADE = ("colorlevels=rimax=0.92:gimax=0.92:bimax=0.88,"
                  "eq=saturation=1.0:contrast=1.02,unsharp=5:5:0.3:5:5:0.0")
_CAPTION_SIZE  = {"small": 60, "medium": 74, "large": 92}
# Caption line width as a FRACTION of frame width, before words wrap. 'narrow'
# forces the short 1-2-word stacked lines many Reels use; 'wide' keeps long lines.
_CAPTION_WIDTH = {"narrow": 0.55, "medium": 0.80, "wide": 0.94}
# Where captions sit vertically, as a FRACTION of frame height so the same
# preset works on 9:16, 1:1 and 16:9 without landing off-screen.
_CAPTION_Y     = {"top": 0.17, "center": 0.50, "middle": 0.50,
                  "lower-third": 0.68, "lower third": 0.68, "lowerthird": 0.68,
                  "bottom": 0.84}
_COLOR_NAMES   = {
    "white": "#ffffff", "black": "#000000", "yellow": "#ffef4a", "gold": "#ffd24a",
    "amber": "#ffbf3a", "red": "#ff4a4a", "orange": "#ff9f43", "green": "#4ade80",
    "lime": "#b6ff3a", "blue": "#46c8ff", "cyan": "#46c8ff", "teal": "#2dd4bf",
    "purple": "#a855f7", "violet": "#7c74ff", "indigo": "#7c74ff",
    "pink": "#ff6ad5", "magenta": "#ff4ae0",
}


def _color_to_hex(v, default: str = "") -> str:
    """Accept a hex ('#fff'/'#ffffff'/'fff'/'ffffff') or a common colour name and
    return a hex string. Unknown / 'none' -> default."""
    if not v:
        return default
    s = str(v).strip().lower()
    if s in ("none", "n/a", "na", ""):
        return default
    if re.fullmatch(r'#?[0-9a-f]{6}', s) or re.fullmatch(r'#?[0-9a-f]{3}', s):
        return s if s.startswith("#") else "#" + s
    for name, hexv in _COLOR_NAMES.items():
        if name in s:
            return hexv
    return default


def _truthy(v) -> bool:
    return str(v).strip().lower() in (
        "true", "1", "yes", "upper", "uppercase", "caps", "all caps", "all-caps", "allcaps")


_FORMAT_PRESETS = {   # only used when the owner explicitly asks to reformat
    "vertical":   (1080, 1920),   # 9:16  — Reels / Shorts / TikTok
    "9:16":       (1080, 1920),
    "square":     (1080, 1080),   # 1:1
    "1:1":        (1080, 1080),
    "landscape":  (1920, 1080),   # 16:9  — YouTube
    "16:9":       (1920, 1080),
}
_LONG_EDGE = 1920   # cap so a 4K source is scaled down, never up


def _probe_dims(path: Path) -> tuple[int, int] | None:
    """Real pixel dimensions of a video, with any rotation flag already applied."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60)
        st = (json.loads(r.stdout or "{}").get("streams") or [{}])[0]
        w, h = int(st.get("width") or 0), int(st.get("height") or 0)
        return (w, h) if w > 0 and h > 0 else None
    except Exception:
        return None


def _target_frame(src: Path, fmt: str = "auto") -> tuple[int, int]:
    """Decide the output frame size.

    DEFAULT IS 'auto' = KEEP THE SOURCE SHAPE. A 16:9 YouTube video stays 16:9,
    a 9:16 phone clip stays 9:16. We only scale so the long edge is _LONG_EDGE,
    never crop or letterbox. Reformatting only happens when the owner explicitly
    picks a format, because silently reshaping someone's footage destroys it.
    """
    fmt = (fmt or "auto").strip().lower()
    dims = _probe_dims(src)
    if fmt in _FORMAT_PRESETS:
        pw, ph = _FORMAT_PRESETS[fmt]
        # Honour the preset ONLY when its orientation matches the source. A client
        # set to "vertical" must NOT box a landscape course video into 9:16 with
        # black bars — that destroys the footage. On an orientation mismatch, keep
        # the source shape instead (the no-reformat rule wins over a stale preset).
        if dims:
            sw, sh = dims
            if abs(sw - sh) < 0.04 * max(sw, sh) or (sw > sh) == (pw > ph):
                return (pw, ph)         # square source, or same orientation -> use preset
            # else: orientation mismatch -> fall through to keep source shape
        else:
            return (pw, ph)             # unreadable source -> trust the preset
    if not dims:
        return (1080, 1920)             # unreadable + no preset: fall back to vertical
    w, h = dims
    scale = _LONG_EDGE / float(max(w, h))
    scale = min(scale, 1.0)            # never upscale
    ow, oh = int(round(w * scale)), int(round(h * scale))
    return (max(2, ow - (ow % 2)), max(2, oh - (oh % 2)))   # even dims for h264


def _grade_from_style(style: dict) -> str:
    """Turn an analyzed reference clip's look into a concrete ffmpeg grade string.

    Stronger and tone-aware: white balance (colorlevels) + a real SPLIT-TONE
    (colorbalance, cool shadows / warm highlights for the cinematic look) + an
    S-curve for contrast + saturation. The old version was a single gentle
    colorlevels+eq pass, so every grade came out looking nearly the same."""
    warmth   = (style.get("grade_warmth") or "neutral").lower()
    contrast = (style.get("grade_contrast") or "normal").lower()
    sat      = (style.get("grade_saturation") or "normal").lower()

    parts = []
    # 1. Overall white balance. Lower channel max = that channel lifted more.
    if "warm" in warmth:   rimax, gimax, bimax = 0.88, 0.90, 0.96
    elif "cool" in warmth: rimax, gimax, bimax = 0.96, 0.95, 0.84
    else:                  rimax, gimax, bimax = 0.92, 0.92, 0.90
    parts.append(f"colorlevels=rimax={rimax}:gimax={gimax}:bimax={bimax}")

    # 2. Contrast as an S-curve (a flat eq contrast can't shape tone the same way).
    if "high" in contrast:
        parts.append("curves=all='0/0 0.25/0.19 0.5/0.5 0.75/0.83 1/1'")
    elif "low" in contrast:
        parts.append("curves=all='0/0.04 0.5/0.5 1/0.96'")

    # 3. Split-tone: this is what makes a grade read as "graded" instead of a
    #    faint tint. Warm = cool shadows + warm highlights (teal/orange);
    #    cool = blue shadows + slightly cool highlights.
    if "warm" in warmth:
        parts.append("colorbalance=rs=-0.04:bs=0.05:rm=0.03:bm=-0.03:rh=0.07:bh=-0.06")
    elif "cool" in warmth:
        parts.append("colorbalance=rs=-0.03:bs=0.07:rm=-0.02:bm=0.03:rh=-0.03:bh=0.06")

    # 4. Saturation (wider range than before so 'vivid' actually pops).
    s = {"muted": 0.80, "normal": 1.03, "vivid": 1.28}.get(sat, 1.03)
    parts.append(f"eq=saturation={s}")

    parts.append("unsharp=5:5:0.3:5:5:0.0")
    return ",".join(parts)


def _beat_zoom_events(edl_ranges: list, total_out: float,
                      cpm, zoom_intensity: str) -> list:
    """Turn the reference's movement level into TIMED punch-in-and-hold zooms.

    The old behaviour was a single imperceptible whole-clip drift; a "punchy"
    reference needs discrete snap zooms on the beat. Cadence and strength come
    from the intensity label, sharpened by the measured cut rate (cpm), and each
    zoom is snapped to a sentence/segment start when one is close so it lands on
    a natural beat. Returns [{at, duration, strength}] in OUTPUT-video seconds."""
    zi = (zoom_intensity or "").strip().lower()
    if zi == "punchy":     strength, iv = 0.15, 4.5
    elif zi == "frequent": strength, iv = 0.11, 6.0
    elif zi == "subtle":   strength, iv = 0.08, 9.0
    else:                  return []
    if isinstance(cpm, (int, float)) and cpm > 0:
        if cpm >= 25:   iv *= 0.70     # very cutty reference -> zoom more often
        elif cpm >= 12: iv *= 0.85
    iv = max(3.0, iv)
    if total_out <= 3.5 or not edl_ranges:
        return []

    seg_starts, acc = [], 0.0
    for r in edl_ranges:
        seg_starts.append(acc)
        acc += max(0.0, float(r["end"]) - float(r["start"]))

    def _snap(t):
        near = [s for s in seg_starts if abs(s - t) <= 1.0 and s >= 1.0]
        return min(near, key=lambda s: abs(s - t)) if near else t

    events, t = [], iv
    while t < total_out - 1.5:
        at = round(_snap(t), 2)
        if at >= 1.0 and (not events or at - events[-1]["at"] >= 2.0):
            dur = round(min(2.2, max(1.2, iv * 0.5)), 2)
            dur = min(dur, max(1.0, total_out - at - 0.3))
            events.append({"at": at, "duration": dur, "strength": strength})
        t += iv
    return events[:14]


def _auto_edl(project_dir: Path, source_map: dict, client: dict,
              hook_plan: dict | None = None,
              keywords: list | None = None,
              zoom_enabled: bool = False,
              zoom_strength: float = 0.08,
              filler_indices: dict | None = None,
              out_w: int = 1080, out_h: int = 1920) -> dict:
    editing = client.get("editing", {})
    speaker = editing.get("caption_speaker", "speaker_0")
    MIN_DUR = 0.3   # ranges shorter than this are discarded

    # Precedence for grade + caption size:
    #   1. Specific-instruction directives (mandatory, highest)
    #   2. Style reference (analyzed clips)
    #   3. Client default settings
    style      = client.get("style_profile") or {}
    directives = client.get("_directives", {})

    # Pacing -> cut density: how long a pause must be before it gets trimmed.
    # Faster style = trim more (shorter GAP); slower = keep natural pauses.
    # Prefer the reference's MEASURED cut rate over a guessed label; clamped so a
    # bad read can never chop mid-word or leave dead air.
    pacing = str(directives.get("pacing") or style.get("pacing") or "").strip().lower()
    cpm = style.get("cuts_per_minute")
    if not directives.get("pacing") and isinstance(cpm, (int, float)) and cpm > 0:
        GAP = 0.32 if cpm >= 25 else 0.45 if cpm >= 10 else 0.72
    elif "fast" in pacing: GAP = 0.30
    elif "slow" in pacing: GAP = 0.80
    else:                  GAP = 0.50
    GAP = max(0.25, min(1.20, GAP))

    # Movement: if nothing explicit turned zoom on, let the reference's movement
    # level enable a gentle global push-in that matches its energy.
    zi = str(style.get("zoom_intensity") or "").strip().lower()
    if not zoom_enabled and directives.get("zoom") != "off" and zi in ("subtle", "frequent", "punchy"):
        zoom_enabled  = True
        zoom_strength = {"subtle": 0.05, "frequent": 0.08, "punchy": 0.11}.get(zi, 0.07)

    def _pick_grade(key, default):
        return directives.get(key) or style.get(key) or default

    if any(directives.get(k) for k in ("grade_warmth", "grade_contrast", "grade_saturation")):
        grade_str = _grade_from_style({
            "grade_warmth":     _pick_grade("grade_warmth", "neutral"),
            "grade_contrast":   _pick_grade("grade_contrast", "normal"),
            "grade_saturation": _pick_grade("grade_saturation", "normal"),
        })
    elif style.get("summary"):
        grade_str = _grade_from_style(style)
    else:
        grade_str = editing.get("grade", _DEFAULT_GRADE)

    cap_size = editing.get("caption_font_size", 60)
    if style.get("caption_size"):
        cap_size = _CAPTION_SIZE.get(style["caption_size"].lower(), cap_size)
    if directives.get("caption_size"):
        cap_size = _CAPTION_SIZE.get(directives["caption_size"].lower(), cap_size)

    # Caption geometry is FRAME-RELATIVE. Client settings and the position presets
    # were both tuned on a 1080x1920 vertical frame, so they are scaled to whatever
    # frame this video actually renders at — otherwise y=1300 lands off-screen on a
    # 1920x1080 landscape edit.
    _vs = out_h / 1920.0
    cap_size = max(18, int(round(cap_size * _vs)))
    cap_y = float(editing.get("caption_y", 1300)) * _vs
    pos = str(directives.get("caption_position") or style.get("caption_position") or "").strip().lower()
    if pos and pos in _CAPTION_Y:
        cap_y = _CAPTION_Y[pos] * out_h          # presets are fractions of frame height
    cap_y = int(max(0.10 * out_h, min(0.92 * out_h, cap_y)))
    # Caption line width: the reference's look (narrow stacked lines vs wide lines)
    # wins over the client default. narrow -> forces the short 1-2-word Reels stack.
    _lw = str(directives.get("caption_line_width") or style.get("caption_line_width") or "").strip().lower()
    if _lw in _CAPTION_WIDTH:
        cap_max_w = int(_CAPTION_WIDTH[_lw] * out_w)
    else:
        cap_max_w = int(float(editing.get("caption_max_width", 960)) * (out_w / 1080.0))
    cap_max_w = max(120, min(out_w - 40, cap_max_w))

    # ALL-CAPS captions if the reference uses them (or a mandatory directive asks)
    cap_upper = _truthy(directives.get("caption_uppercase")) or _truthy(style.get("caption_uppercase")) or _truthy(editing.get("caption_uppercase"))

    ranges = []
    for name, s in source_map.items():
        if not s["trans"].exists():
            continue
        transcript = json.loads(s["trans"].read_text())
        words = _speaker_words(transcript, speaker)
        if not words:
            continue

        fillers = filler_indices.get(name, set()) if filler_indices else set()

        # Build ranges: a filler word is a hard cut point (segment ends before it,
        # the word is skipped, a new segment starts after). Silence gaps split too.
        group: list = []
        for idx, w in enumerate(words):
            if idx in fillers:
                _flush(group, name, MIN_DUR, ranges)
                group = []
                continue
            if group and w["start"] - group[-1].get("end", group[-1]["start"]) > GAP:
                _flush(group, name, MIN_DUR, ranges)
                group = [w]
            else:
                group.append(w)
        _flush(group, name, MIN_DUR, ranges)

    fonts = {k: _font(k) for k in ("handwritten", "impact", "caption")}
    # Caption typeface from the reference: only override for the visibly-distinct
    # looks (condensed / handwritten); rounded / classic keep the default.
    _cf = str(directives.get("caption_font") or style.get("caption_font") or editing.get("caption_font") or "").strip().lower()
    if "condens" in _cf or "tall" in _cf or "impact" in _cf or "bold-sans" in _cf:
        fonts["caption"] = _font("impact")        # Oswald — tall condensed
    elif "hand" in _cf or "script" in _cf or "marker" in _cf:
        fonts["caption"] = _font("handwritten")   # Caveat — handwritten
    elif "round" in _cf or "soft" in _cf:
        fonts["caption"] = _font("rounded")       # Nunito / Arial Rounded — soft geometric
    edl_sources = {
        n: str(s["norm"].relative_to(project_dir))
        for n, s in source_map.items()
        if s["norm"].exists()
    }

    brand = client.get("brand", {})
    accent_color = brand.get("accent_color", "")

    # Caption body color: a mandatory directive wins (e.g. "only red captions"),
    # then the analyzed reference clip, then the client's explicit setting, then white.
    caption_color = (directives.get("caption_color")
                     or _color_to_hex(style.get("caption_text_color"))
                     or editing.get("caption_color", "")
                     or "#ffffff")
    # Karaoke / emphasis word color: directive > reference clip > client setting > brand accent.
    highlight_color = (directives.get("highlight_color")
                       or _color_to_hex(style.get("caption_highlight_color"))
                       or editing.get("highlight_color", "")
                       or accent_color or "")
    # Motion-graphic accent: default to the client's CHOSEN brand colour (never a
    # generic gold/white) so subscribe buttons, callouts, counters and highlights
    # come out on-brand. accent -> primary -> caption colour. Editor overrides per video.
    graphics_color = (accent_color or brand.get("primary_color", "")
                      or caption_color or "#ffffff")

    edl: dict = {
        "version": 1,
        "sources": edl_sources,
        "grade": grade_str,
        "width":  out_w,          # the real output frame — every stage reads these
        "height": out_h,          # instead of assuming 1080x1920
        "ranges": ranges,
        "style": {
            "fonts": fonts,
            "captions": {
                "speaker":         speaker,
                "font_size":       cap_size,
                "y":               cap_y,
                "max_width":       cap_max_w,
                "color":           caption_color,
                "highlight_color": highlight_color,
                "uppercase":       cap_upper,
                "weight":          int(editing.get("caption_weight", 700)),   # promoted default; job override still wins
                "keywords":        keywords or [],   # keyword-emphasis mode
            },
        },
        "broll": [],
        "hook":          hook_plan,          # {text, start_sec, duration_sec} | None
        "zoom_enabled":  zoom_enabled,
        "zoom_strength": zoom_strength,
        "brand":         brand,
        "graphics_color": graphics_color,   # client's brand colour for motion graphics
        "graphics_bg":    editing.get("graphics_bg", ""),   # optional full-screen Takeover surface (else derived from the brand)
    }

    # Transitions: if the reference fades in/out (rather than hard-cutting), carry a
    # fade config the renderer applies as a fade-from-black in and fade-to-black out
    # on the finished video. We deliberately do NOT cross-dissolve every jump cut —
    # that looks wrong on a talking head.
    _trans = str(directives.get("transition_style") or style.get("transition_style") or "").strip().lower()
    if "fade" in _trans or "dissolve" in _trans or "dip" in _trans:
        edl["fade"] = {"dur": 0.4}

    # Only add a title card if the client profile has one configured
    title_cfg = editing.get("title")
    if title_cfg and title_cfg.get("impact_lines"):
        title_cfg = dict(title_cfg)   # don't mutate the client profile
        # RESPECT a title colour set in the profile. ONLY when none is set, default to the
        # brand colour if it is bright enough to read, otherwise clean white — never a
        # washed-out grey. A per-video editor override still wins downstream.
        if not str(title_cfg.get("color") or "").strip():
            _tc = str(graphics_color or "").strip().lstrip("#")
            if len(_tc) == 3:
                _tc = "".join(ch * 2 for ch in _tc)   # expand 3-digit hex
            if len(_tc) != 6 or any(ch not in "0123456789abcdefABCDEF" for ch in _tc):
                _tc = "ffffff"
            _n = int(_tc, 16); _r, _g, _b = (_n >> 16) & 255, (_n >> 8) & 255, _n & 255
            lum = (0.2126 * _r + 0.7152 * _g + 0.0722 * _b) / 255
            title_cfg["color"] = ("#" + _tc.lower()) if lum >= 0.5 else "#ffffff"
        edl["style"]["title"] = title_cfg

    return edl


def _flush(group: list, source: str, min_dur: float, out: list):
    if not group:
        return
    s = max(0.0, group[0]["start"] - 0.05)
    e = group[-1].get("end", group[-1]["start"]) + 0.05
    if e - s < min_dur:
        return
    out.append({
        "source": source,
        "start":  round(s, 3),
        "end":    round(e, 3),
        "beat":   "AUTO",
        "quote":  " ".join(w.get("text", "") for w in group[:8]),
    })


# ── Main pipeline ──────────────────────────────────────────────────────────────

def run_pipeline(job_id: str, jobs_dir: Path, uploads_dir: Path, elevenlabs_key: str):
    """
    Full editing pipeline, designed to run in a background thread.

    Steps:
      1. Find video files in the upload directory
      2. Normalize each to true-CFR 30fps 1080x1920 PCM
      3. Transcribe each with ElevenLabs Scribe (word-level, diarized)
      4. Auto-generate edl.json from transcripts using client settings
      5. Tighten cuts with decay_clip
      6. Render: extract → concat → overlays → loudnorm → final.mp4
    """
    job_path = jobs_dir / f"{job_id}.json"
    job = json.loads(job_path.read_text())
    raw_dir     = uploads_dir / job_id       # persistent (volume): the raw upload lives here
    project_dir = SCRATCH_ROOT / job_id      # ephemeral: ALL render work happens here
    project_dir.mkdir(parents=True, exist_ok=True)

    # Inject key into environment for subprocess scripts
    os.environ["ELEVENLABS_API_KEY"] = elevenlabs_key

    # Record wall-clock start so _check_cancelled can enforce the time limit
    job["started_at"] = time.time()
    job.pop("cancelled", None)  # clear any old cancellation flag from a previous run
    job_path.write_text(json.dumps(job, indent=2))

    try:
        # ── 1. Find video files ────────────────────────────────────────────────
        _set_status(job_path, "normalizing")
        _log(job_path, "Scanning uploaded files...")

        _PIPELINE_DIRS  = {"animations", "transcripts", "clips30", "broll", "sources", "broll_src"}
        _PIPELINE_STEMS = {"base30", "base30_zoom", "composited30", "final"}

        # Source footage. Full Drive backend: when the job references clips in the
        # client's Google Drive Source folder, pull them onto scratch. Otherwise
        # use the raw files uploaded to the volume (local fallback).
        source_drive = job.get("source_drive") or []
        if source_drive:
            from integrations import gdrive as _gdrive
            scan_dir = project_dir / "sources"
            scan_dir.mkdir(exist_ok=True)
            for s in source_drive:
                fid = s.get("id")
                nm  = s.get("name") or (f"{fid}.mp4" if fid else "source.mp4")
                _log(job_path, f"Pulling source '{nm}' from Google Drive...")
                if not _gdrive.download_file(fid, scan_dir / nm, log=lambda m: _log(job_path, m)):
                    raise RuntimeError(f"Could not pull source '{nm}' from Google Drive")
        else:
            scan_dir = raw_dir

        videos = sorted(
            p for p in scan_dir.rglob("*")
            if p.is_file()
            and not p.name.startswith(".")
            and p.suffix.lower() in VIDEO_EXTS
            and "_v30" not in p.stem
            and p.stem not in _PIPELINE_STEMS
            and not p.stem.startswith("seg_")
            and not any(part in _PIPELINE_DIRS for part in p.relative_to(scan_dir).parts)
        )
        if not videos:
            raise RuntimeError("No source video files found for this job")

        _log(job_path, f"Found {len(videos)} video file(s): {', '.join(v.name for v in videos)}")

        # Use the video stem as the source key — decay_clip.py looks up
        # transcripts/{key}.json, so key must match the transcribed stem.
        source_map: dict[str, dict] = {}
        for v in videos:
            source_map[v.stem] = {
                "raw":   v,
                "norm":  project_dir / f"{v.stem}_v30.mov",
                "trans": project_dir / "transcripts" / f"{v.stem}.json",
            }

        # ── 2. Normalize ───────────────────────────────────────────────────────
        # Frame size is decided ONCE, from the footage itself. Default keeps the
        # source shape (a 16:9 YouTube video stays 16:9); a format is only forced
        # when the job or client profile explicitly asks for one.
        _fmt = str(job.get("format")
                   or job.get("client_snapshot", {}).get("editing", {}).get("format")
                   or "auto").strip().lower()
        _first_src = next(iter(source_map.values()))["raw"]
        out_w, out_h = _target_frame(_first_src, _fmt)
        _src_dims = _probe_dims(_first_src)
        if _fmt in _FORMAT_PRESETS:
            _log(job_path, f"format: '{_fmt}' requested — rendering {out_w}x{out_h} "
                           f"(source {_src_dims[0]}x{_src_dims[1]})" if _src_dims else
                           f"format: '{_fmt}' — rendering {out_w}x{out_h}")
        else:
            _log(job_path, f"format: keeping the source shape — {out_w}x{out_h}"
                           + (f" (from {_src_dims[0]}x{_src_dims[1]})" if _src_dims else ""))

        _check_cancelled(job_path)
        for name, s in source_map.items():
            if s["norm"].exists():
                _log(job_path, f"normalize: cached — {s['norm'].name}")
                continue
            _log(job_path, f"normalize: {s['raw'].name} → {s['norm'].name} @ {out_w}x{out_h}")
            normalize(s["raw"], s["norm"], height=out_h, width=out_w)

        # ── 3. Transcribe ──────────────────────────────────────────────────────
        _check_cancelled(job_path)
        _set_status(job_path, "transcribing")
        client  = job.get("client_snapshot", {})
        editing = client.get("editing", {})
        lang    = editing.get("language") or None
        if lang == "auto": lang = None
        n_spk   = editing.get("num_speakers") or None

        (project_dir / "transcripts").mkdir(exist_ok=True)

        mock_mode = MOCK_TRANSCRIBE or os.environ.get("MOCK_TRANSCRIBE") == "1"

        for name, s in source_map.items():
            if s["trans"].exists():
                _log(job_path, f"transcribe: cached — {s['trans'].name}")
                continue
            if mock_mode:
                _log(job_path, f"transcribe: MOCK MODE — generating fake transcript for {s['raw'].name}")
                _mock_transcribe(s["raw"], project_dir)
                _log(job_path, f"transcribe: mock done — {s['trans'].name}")
            else:
                provider = os.environ.get("TRANSCRIBE_PROVIDER", "auto").strip().lower()
                # Try ElevenLabs Scribe (diarized, high quality) unless forced local
                # or there is no key. On ANY Scribe failure — quota_exceeded, 401,
                # network — fall through to local Whisper so a dead quota can never
                # hard-stop a render again (this is exactly Max's quota_exceeded).
                if provider != "local" and elevenlabs_key:
                    try:
                        _log(job_path, f"transcribe: {s['raw'].name} via ElevenLabs Scribe "
                                       f"({lang or 'auto-detect'}, {n_spk or '?'} speakers)")
                        transcribe_one(
                            video=s["raw"], edit_dir=project_dir, api_key=elevenlabs_key,
                            language=lang, num_speakers=n_spk, verbose=False)
                    except Exception as e:
                        _log(job_path, f"transcribe: ElevenLabs failed ({str(e)[:180]}) "
                                       f"— falling back to local Whisper")
                if not s["trans"].exists():
                    from transcribe_local import transcribe_local
                    _log(job_path, f"transcribe: {s['raw'].name} via local Whisper "
                                   f"(model {os.environ.get('WHISPER_MODEL', 'small')}, "
                                   f"{lang or 'auto-detect'})")
                    transcribe_local(video=s["raw"], edit_dir=project_dir,
                                     language=lang, verbose=False)
                _log(job_path, f"transcribe: done — {s['trans'].name}")

        # Free the local Whisper model (if it was loaded) BEFORE the memory-heavy
        # ffmpeg encode stages, so transcription RAM never stacks with compose /
        # normalize and worsens the OOM that SIGKILLs those encodes.
        try:
            from transcribe_local import unload_model
            unload_model()
        except Exception:
            pass

        # ── 3a. Resolve the on-camera speaker robustly ─────────────────────────
        # The client is configured for one speaker (e.g. speaker_0), but diarization
        # can label a solo speaker differently — especially on short clips or non-English
        # (e.g. Danish) audio. If the configured speaker has no words but the transcript
        # does, fall back to ALL speakers so a real video never fails with "no speech".
        cfg_speaker = editing.get("caption_speaker", "speaker_0")

        def _spk_word_count(spk):
            n = 0
            for _n, _s in source_map.items():
                if _s["trans"].exists():
                    n += len(_speaker_words(json.loads(_s["trans"].read_text()), spk))
            return n

        if cfg_speaker is not None and _spk_word_count(cfg_speaker) == 0 and _spk_word_count(None) > 0:
            _log(job_path, f"transcribe: speaker '{cfg_speaker}' had no words — using all speech instead")
            editing["caption_speaker"] = None

        # ── 3a2. Two voices: keep the louder on-camera one, drop the off-camera reader ──
        # A script reader feeds lines off camera and the on-camera client repeats them, so
        # the transcript diarizes into two speakers. Keep the louder (closer mic); override
        # with job['keep_speaker'] = louder | quieter | both. Rewrites the scratch transcript
        # so EVERY downstream stage follows the kept voice. Never hard-fails.
        if not mock_mode:
            try:
                _spk_ids = set()
                for _n, _s in source_map.items():
                    if _s["trans"].exists():
                        for _w in json.loads(_s["trans"].read_text()).get("words", []):
                            if _w.get("type") == "word" and _w.get("start") is not None:
                                _spk_ids.add(_w.get("speaker_id", "speaker_0"))
                _keep = str(job.get("keep_speaker", "louder")).strip().lower()
                if _keep == "both":
                    if len(_spk_ids) >= 2:
                        editing["caption_speaker"] = None
                        _log(job_path, "speaker-select: keeping ALL voices (keep=both)")
                else:
                    from speaker_select import speaker_loudness, choose_kept_speaker, loud_word_keep
                    # 1) PER-WORD LOUDNESS GATE first. The on-camera client is on the close
                    #    mic (loud); the off-camera reader is far (much quieter, a stable
                    #    15-20 dB gap). Gating per WORD by loudness survives the diarization
                    #    drifting and MERGING the two voices partway through — the real
                    #    failure (good for ~12s, then the reader's words get the on-camera
                    #    label and slip in). Self-guards: a no-op unless the loudness is
                    #    clearly bimodal, so a single or genuine two-person clip is untouched.
                    _gated_any = False
                    for _n, _s in source_map.items():
                        try:
                            if not _s["trans"].exists():
                                continue
                            _tr = json.loads(_s["trans"].read_text())
                            _words = _tr.get("words", [])
                            _mask = loud_word_keep(_s["norm"], _words)
                            if _mask is None:
                                continue
                            _dropped = sum(1 for w, m in zip(_words, _mask)
                                           if (not m) and w.get("type") == "word")
                            if not _dropped:
                                continue
                            _tr["words"] = [w for w, m in zip(_words, _mask) if m]
                            _s["trans"].write_text(json.dumps(_tr))
                            _gated_any = True
                            _log(job_path, f"speaker-select [{_n}]: loudness gate removed "
                                           f"{_dropped} quiet off-camera word(s), kept the close-mic voice")
                        except Exception:
                            continue
                    if _gated_any:
                        editing["caption_speaker"] = None
                    elif len(_spk_ids) >= 2:
                        # 2) Fall back to the diarization-label pick when loudness is not
                        #    clearly bimodal but two labelled speakers exist.
                        _loud = speaker_loudness(source_map, editing)
                        _kept_any = False
                        for _n, _s in source_map.items():
                            _tbl = _loud.get(_n) or {}
                            _pick = choose_kept_speaker(_tbl, keep=_keep)
                            if not _pick:
                                continue
                            _tr = json.loads(_s["trans"].read_text())
                            _tr["words"] = [w for w in _tr.get("words", [])
                                            if w.get("type") != "word" or w.get("speaker_id") == _pick]
                            _s["trans"].write_text(json.dumps(_tr))
                            _kept_any = True
                            _drop = ", ".join(f"{k} ({v['rms_db']:.1f}dBFS)"
                                              for k, v in _tbl.items() if k != _pick)
                            _log(job_path, f"speaker-select [{_n}]: kept {_pick} "
                                           f"({_tbl[_pick]['rms_db']:.1f}dBFS, {_tbl[_pick]['words']} words) "
                                           f"over {_drop} — dropped the quieter off-camera voice")
                        if _kept_any:
                            editing["caption_speaker"] = None
            except Exception as _e:
                _log(job_path, f"speaker-select skipped ({_e})")

        # ── 3b. AI edit plan — filler cutting (default ON) + per-video extras ──
        palmier_instructions = job.get("palmier_instructions", "").strip()
        instr_l        = palmier_instructions.lower()
        hook_plan      = None
        keywords       = []
        zoom_enabled   = False
        zoom_strength  = 0.08
        zoom_events    = []
        graphics_plan  = []
        filler_indices = None
        ai_cut_spans   = []
        anthropic_key  = os.environ.get("ANTHROPIC_API_KEY", "")

        directives = {}
        if not anthropic_key:
            if palmier_instructions or client.get("specific_instructions"):
                _log(job_path, "AI: ANTHROPIC_API_KEY missing — skipping AI features, basic edit only")
        else:
            # Highest-priority: the client's mandatory 'Specific Instructions'. These
            # override every other setting (colours, captions, etc.) on every video.
            directives = _interpret_directives(
                client.get("specific_instructions", ""), anthropic_key, lambda m: _log(job_path, m))
            client["_directives"] = directives   # read by _auto_edl + the B-roll section

            # Filler / hesitation cutting runs on EVERY video by default (tight
            # talking-head edit), unless the user explicitly asks to keep fillers.
            _keep_fillers = any(k in instr_l for k in (
                "keep the filler", "keep filler", "keep um", "keep the um", "keep the ums",
                "leave the um", "leave the filler", "don't cut", "do not cut",
                "dont cut", "no filler", "without cutting"))
            if not _keep_fillers:
                _check_cancelled(job_path)
                _log(job_path, "AI: identifying filler words to cut (ums, uhs, hesitations)...")
                filler_indices = _identify_filler_words(
                    source_map, editing.get("caption_speaker", "speaker_0"),
                    anthropic_key, lambda m: _log(job_path, m),
                    script=job.get("script", ""))
                total_cut = sum(len(v) for v in (filler_indices or {}).values())
                _log(job_path, f"AI: {total_cut} filler word(s) marked for removal")

                # Claude drives the real cut: remove whole bad TAKES (retakes,
                # false starts, asides) as source-time spans. This is the thing
                # that makes a raw recording watchable — cutting the "she said it
                # three times" repeats — and it uses the same proven cut machinery
                # as a hand edit, so it survives re-renders.
                _check_cancelled(job_path)
                _log(job_path, "AI: reviewing the recording for retakes and false starts to cut...")
                ai_cut_spans = _plan_cuts(
                    source_map, editing.get("caption_speaker", "speaker_0"),
                    anthropic_key, lambda m: _log(job_path, m),
                    script=job.get("script", ""))

            # Hook / keyword-emphasis / zoom come from the per-video instructions
            # (or a mandatory hook rule).
            _force_hook = directives.get("hook") == "force"
            # A reference clip with a bold on-screen hook should PRODUCE a hook on
            # its own, with no typed instruction — previously hook_style was dead.
            _profile_hook = str((client.get("style_profile") or {}).get("hook_style") or "").strip().lower()
            _wants_profile_hook = (_profile_hook == "bold") and directives.get("hook") != "off"
            if palmier_instructions or _force_hook or _wants_profile_hook:
                _check_cancelled(job_path)
                _log(job_path, "AI: building per-video edit plan...")
                eff_instructions = palmier_instructions
                # _force_hook is a MANDATORY client rule → always ensure a hook.
                # The profile's bold hook only adds one when the creator typed NO
                # per-video instruction, so an explicit request (e.g. "keep it clean,
                # no on-screen text") is never silently overridden by the profile.
                _add_hook = _force_hook or (_wants_profile_hook and not palmier_instructions)
                if _add_hook and "hook" not in instr_l:
                    eff_instructions = (eff_instructions + " Always add a short punchy on-screen hook.").strip()
                    if _wants_profile_hook and not palmier_instructions and not _force_hook:
                        _log(job_path, "Style match: reference has a bold hook → adding one to this video")
                plan = _generate_edit_plan(source_map, eff_instructions, client,
                                           anthropic_key, lambda m: _log(job_path, m))
                hook_plan     = plan["hook"]
                keywords      = plan["keywords"]
                zoom_enabled  = plan["zoom"]["enabled"]
                zoom_strength = plan["zoom"]["strength"]
                zoom_events   = plan.get("zoom_events", [])
                graphics_plan = plan.get("graphics", [])
                if hook_plan:
                    _log(job_path, f"AI: hook = '{hook_plan['text']}' "
                                   f"(shows {hook_plan['start_sec']:.0f}s–{hook_plan['start_sec']+hook_plan['duration_sec']:.0f}s)")

            # Apply the client's mandatory overrides on top of the plan (highest priority)
            if directives.get("hook") == "off":
                hook_plan = None
                _log(job_path, "AI: hook disabled by the client's specific instructions")
            if directives.get("zoom") == "off":
                zoom_enabled = False
                zoom_events = []
            elif directives.get("zoom") == "force":
                zoom_enabled = True

        # ── 4. Auto-generate EDL ───────────────────────────────────────────────
        _set_status(job_path, "generating_edl")
        _log(job_path, "Building EDL from transcripts...")
        edl = _auto_edl(project_dir, source_map, client,
                        hook_plan=hook_plan,
                        keywords=keywords,
                        zoom_enabled=zoom_enabled,
                        zoom_strength=zoom_strength,
                        filler_indices=filler_indices,
                        out_w=out_w, out_h=out_h)

        # Log exactly which reference-style choices were applied to this render
        _sp = client.get("style_profile") or {}
        if _sp.get("summary") or _sp.get("features"):
            _cap = edl.get("style", {}).get("captions", {})
            _pos = str(_sp.get("caption_position") or "").strip() or "default"
            _cpm = _sp.get("cuts_per_minute")
            _pace = (f"{_cpm} cuts/min" if isinstance(_cpm, (int, float)) and _cpm
                     else str(_sp.get("pacing") or "medium").strip())
            _log(job_path,
                 f"Style match: captions {_pos} @ y={_cap.get('y')} size {_cap.get('font_size')}"
                 f"{' ALL-CAPS' if _cap.get('uppercase') else ''}, "
                 f"text {_cap.get('color')} / highlight {_cap.get('highlight_color') or 'none'}, "
                 f"font {str(_sp.get('caption_font') or 'default')}, "
                 f"pacing {_pace}, b-roll {str(_sp.get('broll_intensity') or 'ai')}, "
                 f"movement {str(_sp.get('zoom_intensity') or 'none')}")

        # Apply per-job overrides (set via the job chat OR the Studio editor) on top
        # of the generated EDL.
        overrides = job.get("job_overrides", {})
        if overrides:
            if "grade" in overrides:
                edl["grade"] = overrides["grade"]
            if overrides.get("graphics_color"):        # editor set a per-video graphics colour
                edl["graphics_color"] = overrides["graphics_color"]
            if "graphics_bg" in overrides:             # editor set / cleared the Takeover surface
                edl["graphics_bg"] = overrides["graphics_bg"]
            caps = edl.setdefault("style", {}).setdefault("captions", {})
            for ok, ek in [("caption_y","y"),("caption_font_size","font_size"),
                           ("caption_color","color"),("highlight_color","highlight_color"),
                           ("caption_max_width","max_width"),("caption_weight","weight")]:
                if ok in overrides:
                    caps[ek] = overrides[ok]
            _oh = int(edl.get("height", 1920))
            if "caption_position" in overrides:
                _p = str(overrides["caption_position"]).strip().lower()
                if _p in _CAPTION_Y:
                    caps["y"] = int(_CAPTION_Y[_p] * _oh)
            if "caption_uppercase" in overrides:
                caps["uppercase"] = _truthy(overrides["caption_uppercase"])
            if "caption_font" in overrides:
                _cf = str(overrides["caption_font"]).strip().lower()
                _fonts = edl.setdefault("style", {}).setdefault("fonts", {})
                if "condens" in _cf or "impact" in _cf:   _fonts["caption"] = _font("impact")
                elif "hand" in _cf or "script" in _cf:     _fonts["caption"] = _font("handwritten")
                elif "round" in _cf or "soft" in _cf:      _fonts["caption"] = _font("rounded")
                else:                                       _fonts["caption"] = _font("caption")
            # Title card: per-video edit / delete / restyle. Fixes the onboarding title
            # being stamped verbatim onto every video. Runs AFTER _auto_edl set it from
            # the client profile, so this wins; it also CREATES the card if none existed.
            if any(k.startswith("title_") for k in overrides):
                if "title_enabled" in overrides and not _truthy(overrides["title_enabled"]):
                    edl.get("style", {}).pop("title", None)            # delete for this video
                else:
                    _t = edl.setdefault("style", {}).setdefault("title", {})
                    if "title_text" in overrides:
                        _t["impact_lines"] = [ln.strip().upper()
                                              for ln in re.split(r"[\n|]", str(overrides["title_text"]))
                                              if ln.strip()][:2]
                    if "title_handwritten" in overrides:
                        _t["handwritten"] = str(overrides["title_handwritten"]).strip()
                    if "title_color" in overrides:
                        _t["color"] = overrides["title_color"]
                    if "title_bg" in overrides:
                        _t["bg"] = _truthy(overrides["title_bg"])
                    if "title_bg_color" in overrides:
                        _t["bg_color"] = overrides["title_bg_color"]
                    if "title_duration" in overrides:
                        try:
                            _t["duration"] = float(overrides["title_duration"])
                        except (TypeError, ValueError):
                            pass
                    for _ok, _ek in (("title_x", "x"), ("title_y", "y")):   # dragged position offset
                        if _ok in overrides:
                            try:
                                _t[_ek] = max(-0.45, min(0.45, float(overrides[_ok])))
                            except (TypeError, ValueError):
                                pass
                    _t.setdefault("duration", 4.5)   # compose needs duration>0 to show the card
                    if not (_t.get("impact_lines") or _t.get("handwritten")):
                        edl.get("style", {}).pop("title", None)       # cleared text -> no card
            _log(job_path, f"Job overrides applied: {list(overrides.keys())}")

        # Studio "split a clip" edits: divide ranges at SOURCE-time points FIRST, so a
        # subsequent per-piece trim/cut is scoped to the intended half. Non-destructive.
        split_points = job.get("split_points") or []
        if split_points:
            before = len(edl["ranges"])
            edl["ranges"] = _apply_splits(edl["ranges"], split_points)
            _log(job_path, f"Studio: {len(split_points)} split(s) applied "
                           f"({before} → {len(edl['ranges'])} ranges)")

        # Cut-out edits: remove SOURCE-time spans from the ranges. Two sources feed
        # this — the AI cut engine's bad-take removals and the Studio "cut a bit out"
        # hand edits — and they use the identical mechanism. Source time is stable
        # across re-renders, so every cut survives regeneration.
        cut_spans = list(ai_cut_spans) + (job.get("cut_spans") or [])
        if cut_spans:
            before = len(edl["ranges"])
            edl["ranges"] = _apply_cut_spans(edl["ranges"], cut_spans)
            _log(job_path, f"Cuts: {len(ai_cut_spans)} AI + {len(job.get('cut_spans') or [])} manual "
                           f"({before} → {len(edl['ranges'])} ranges)")

        # Studio caption-TEXT edits (fix a typo, reword a line). build_overlays
        # matches by original text, so an edit survives the regenerate re-render.
        if job.get("caption_text_overrides"):
            edl["caption_overrides"] = job["caption_text_overrides"]
            _log(job_path, f"Studio: {len(job['caption_text_overrides'])} caption text edit(s)")
        if job.get("caption_removes"):
            edl["caption_removes"] = job["caption_removes"]
            _log(job_path, f"Studio: {len(job['caption_removes'])} caption(s) deleted")
        # Studio per-caption COLOR edits: matched by original text, same as text edits.
        if job.get("caption_color_overrides"):
            edl["caption_color_overrides"] = job["caption_color_overrides"]
            _log(job_path, f"Studio: {len(job['caption_color_overrides'])} caption color edit(s)")

        (project_dir / "edl.json").write_text(json.dumps(edl, indent=2))
        _log(job_path, f"EDL: {len(edl['ranges'])} ranges, {sum(r['end']-r['start'] for r in edl['ranges']):.1f}s raw")

        if not edl["ranges"]:
            raise RuntimeError(
                "No on-camera speech found in transcripts. "
                "Check the speaker setting on the client profile."
            )

        # ── 4a. Timestamped punch-in zooms (in FINAL-video seconds) ────────────
        # Merge AI-parsed "zoom at Ns" events with the chat's manual add/remove.
        total_out = sum(r["end"] - r["start"] for r in edl["ranges"]) or 0.0
        z_add    = job.get("zoom_add", [])     # [{at,duration,strength}] added via chat/timeline
        z_remove = job.get("zoom_remove", [])  # [{at}] removed via chat (matched within 0.4s)
        # When the timeline UI has set zooms explicitly, it is the source of truth:
        # ignore the AI-parsed events and use only the manual list.
        base_events = [] if job.get("zoom_manual") else list(zoom_events)

        # If nothing explicit set zooms (no per-video instruction produced events,
        # no manual timeline edits), let the reference's movement style place beat
        # zooms — so a "punchy" inspiration actually punches instead of the faint
        # whole-clip drift that used to be all zoom_intensity did.
        _profile_zoom_meta = None
        if not job.get("zoom_manual") and not base_events and directives.get("zoom") != "off":
            _zsp = client.get("style_profile") or {}
            _zi  = str(_zsp.get("zoom_intensity") or "").strip().lower()
            if _zi in ("subtle", "frequent", "punchy"):
                base_events = _beat_zoom_events(
                    edl["ranges"], total_out, _zsp.get("cuts_per_minute"), _zi)
                if base_events:
                    _profile_zoom_meta = {"cpm": _zsp.get("cuts_per_minute"), "zi": _zi}
                    _log(job_path, f"Zoom: reference movement '{_zi}' → placing "
                                   f"{len(base_events)} beat zoom(s)")
        def _z_removed(at: float) -> bool:
            return any(abs(at - float(r.get("at", -999))) < 0.4 for r in z_remove)
        merged = []
        for ev in (base_events + list(z_add)):
            try:
                at = float(ev.get("at", 0) or 0)
            except (TypeError, ValueError):
                continue
            if at < 0 or at > total_out + 0.5:
                _log(job_path, f"Zoom: {at:.1f}s is outside the {total_out:.1f}s video — skipping")
                continue
            if _z_removed(at):
                continue
            dur  = max(0.8, min(6.0, float(ev.get("duration", 2.5) or 2.5)))
            dur  = min(dur, max(0.8, total_out - at))   # never hold past the end
            strg = max(0.06, min(0.30, float(ev.get("strength", 0.12) or 0.12)))
            merged.append({"at": round(at, 2), "duration": round(dur, 2), "strength": round(strg, 3)})
        merged.sort(key=lambda e: e["at"])
        zooms = []
        for e in merged:   # drop near-duplicates within 0.4s
            if zooms and abs(e["at"] - zooms[-1]["at"]) < 0.4:
                continue
            zooms.append(e)
        if zooms:
            edl["zooms"] = zooms
            _log(job_path, "Zoom: " + ", ".join(
                f"{e['at']:.1f}s +{e['strength']*100:.0f}% for {e['duration']:.1f}s" for e in zooms))
        # Record the final zooms + the output length so the chat/timeline can list
        # and edit them precisely (the timeline bar needs the duration).
        _jz = json.loads(job_path.read_text())
        _jz["zoom_last"] = zooms
        _jz["output_duration"] = round(total_out, 2)
        job_path.write_text(json.dumps(_jz, indent=2))
        (project_dir / "edl.json").write_text(json.dumps(edl, indent=2))
        # Only auto-placed beat zooms on an otherwise-untouched video can be safely
        # re-placed on the tightened timeline after decay_clip (below). If the user
        # has hand-edited zooms via chat, their absolute times are left alone.
        _reanchor_zoom = bool(_profile_zoom_meta) and not z_add and not z_remove
        # Graphics are resolved AFTER decay_clip (step 5a2), because decay tightens
        # every range and would otherwise drift each card late off its spoken moment.

        # ── 4b. Inject B-roll — AI-matched to what's being said ────────────────
        client_id   = job.get("client_id", "")
        client_name = job.get("client_name", "")
        BASE_DIR    = Path(os.environ.get("DATA_ROOT") or Path(__file__).parent.parent)
        # Persistent per-client folder on the volume: holds any locally-uploaded
        # clips AND the vision-tag cache (so each clip is analysed only once).
        local_broll = BASE_DIR / "broll_library" / client_id
        local_broll.mkdir(parents=True, exist_ok=True)

        # Working B-roll folder for THIS render, on ephemeral scratch. Clips come
        # from local uploads plus the client's Google Drive B-roll folder (Option
        # A: no in-app upload). Pulled fresh each render; the volume stays lean.
        broll_src = project_dir / "broll_src"
        broll_src.mkdir(exist_ok=True)
        for f in local_broll.iterdir():
            if f.is_file() and f.suffix.lower() in BROLL_EXTS:
                dst = broll_src / f.name
                if not dst.exists():
                    shutil.copy2(f, dst)
        try:
            from integrations import config as _icfg, gdrive as _gdrive
            if _icfg.gdrive_configured():
                _log(job_path, "B-roll: checking the client's Google Drive folder...")
                n = _gdrive.download_broll(client_name, broll_src, log=lambda m: _log(job_path, m))
                _log(job_path, f"B-roll: {n} clip(s) available from Google Drive"
                     if n else "B-roll: none found in the Drive folder")
        except Exception as _e:
            _log(job_path, f"B-roll: Drive pull skipped ({_e})")

        clips = sorted(
            f for f in broll_src.iterdir()
            if f.is_file() and f.suffix.lower() in BROLL_EXTS
        ) if broll_src.exists() else []
        # HEIC/HEIF photos aren't ffmpeg-readable — convert them to JPEG up front so
        # every later stage (tagging, planning, compositing) sees a standard image.
        # Dedup by final name so a re-run doesn't include both IMG.HEIC and IMG.jpg.
        _by_name = {}
        for c in clips:
            d = _decodable_image(c, lambda m: _log(job_path, m))
            if d is not None:
                _by_name[d.name] = d
        clips = sorted(_by_name.values())

        # B-roll count control (set per-video on the job card):
        #   None / "ai"  -> AI decides how many
        #   0            -> no B-roll this video
        #   N            -> exactly N cutaways (best-fitting), spread across the video
        _broll_raw = job.get("broll_count", None)
        broll_count = None
        if isinstance(_broll_raw, (int, float)):
            broll_count = int(_broll_raw)
        elif isinstance(_broll_raw, str) and _broll_raw.strip().isdigit():
            broll_count = int(_broll_raw.strip())

        # If this video didn't set a count, let the reference style's B-roll density
        # decide how many cutaways to place — scaled by the video's length and clamped.
        if broll_count is None:
            _bi = str((client.get("style_profile") or {}).get("broll_intensity") or "").strip().lower()
            if _bi in ("light", "moderate", "heavy"):
                _mins = max(0.2, sum(r["end"] - r["start"] for r in edl["ranges"]) / 60.0)
                _per_min = {"light": 1.0, "moderate": 2.5, "heavy": 4.0}[_bi]
                broll_count = max(1, min(12, round(_per_min * _mins)))
                _log(job_path, f"B-roll: reference style is '{_bi}' → targeting {broll_count} cutaway(s)")

        # A mandatory 'no B-roll' rule from the client's specific instructions wins
        if directives.get("broll") == "off":
            broll_count = 0
            _log(job_path, "B-roll: disabled by the client's specific instructions")

        # Did the client actually HAVE a library? (before a 0-count empties it, so
        # the empty-library warning below never fires when b-roll was just disabled.)
        _had_clips = bool(clips)

        if clips and broll_count == 0:
            _log(job_path, "B-roll: set to 0 for this video — skipping")
            clips = []

        if clips:
            broll_dest = project_dir / "broll"
            broll_dest.mkdir(exist_ok=True)
            for c in clips:
                dst = broll_dest / c.name
                if not dst.exists():
                    shutil.copy2(c, dst)

            anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
            speaker = editing.get("caption_speaker", "speaker_0")

            # Cumulative segment offsets (float output time) for placement math
            edl_off, cum = [], 0.0
            for r in edl["ranges"]:
                edl_off.append(cum); cum += r["end"] - r["start"]

            broll_entries = []
            broll_summary: list[dict] = []   # human-readable, for the AI chat to read/edit
            clip_names   = {c.name for c in clips}
            # Manual fine-tuning deltas set via the job chat (auto-match, then adjust)
            broll_remove = job.get("broll_remove", [])
            broll_add    = job.get("broll_add", [])
            # Photo style: "cards" forces every photo to pop up as a card (BAM);
            # "auto" (default) lets the AI pick card vs full-frame per photo.
            broll_style  = str(job.get("broll_style", "auto") or "auto").lower()
            force_cards  = broll_style in ("card", "cards", "pop", "popin", "pop-in", "bam")

            if anthropic_key:
                _check_cancelled(job_path)
                total_dur = sum(r["end"] - r["start"] for r in edl["ranges"]) or 1.0
                mode_txt  = f"exactly {broll_count}" if broll_count else "AI-decided count of"
                _log(job_path, f"B-roll: tagging {len(clips)} clip(s), placing {mode_txt} cutaway(s)...")
                tags = tag_broll_clips(broll_src, clips, anthropic_key, lambda m: _log(job_path, m), cache_dir=local_broll)
                _log(job_path, "B-roll: matching clips to the transcript...")
                placements = _plan_broll(source_map, tags, palmier_instructions or "",
                                         anthropic_key, lambda m: _log(job_path, m),
                                         desired_count=broll_count, force_cards=force_cards)

                # Apply chat REMOVALS: drop any auto placement the user took out
                def _is_removed(p: dict) -> bool:
                    for r in broll_remove:
                        rf = (r.get("file") or "").lower()
                        if rf and rf == (p.get("file") or "").lower():
                            rq = (r.get("quote") or "").strip().lower()
                            if not rq or rq in (p.get("quote") or "").lower():
                                return True
                    return False
                if broll_remove:
                    kept = [p for p in placements if not _is_removed(p)]
                    if len(kept) != len(placements):
                        _log(job_path, f"B-roll: removed {len(placements)-len(kept)} auto cutaway(s) per your edits")
                    placements = kept

                if broll_count and broll_count > 0:
                    MIN_GAP = max(1.5, min(5.0, total_dur / (broll_count + 1)))
                else:
                    MIN_GAP = 5.0

                timeline = _build_word_timeline(source_map, speaker, edl)
                placed_ts: list[float] = []

                def _place(p: dict, enforce_gap: bool, source: str):
                    fname = Path(p.get("file", "")).name
                    if fname not in clip_names:
                        _log(job_path, f"B-roll: clip '{fname}' not in library — skipping")
                        return
                    t = _find_quote_time(timeline, p.get("quote", ""))
                    if t is None:
                        _log(job_path, f"B-roll: could not locate quote '{p.get('quote')}' — skipping")
                        return
                    if enforce_gap and any(abs(t - pt) < MIN_GAP for pt in placed_ts):
                        return
                    seg_i = max((i for i, off in enumerate(edl_off) if off <= t), default=0)
                    dur = max(1.5, min(3.5, float(p.get("duration_sec", 2.5))))
                    is_img = _is_broll_image(fname)
                    _tg = tags.get(fname) or {}
                    _ain  = float(_tg.get("active_in", 0.0) or 0.0)
                    _aout = float(_tg.get("active_out", 0.0) or 0.0)
                    if not is_img and _aout > _ain:          # keep the cutaway inside the action
                        dur = max(1.2, min(dur, _aout - _ain))
                    mode = "full"
                    if is_img:
                        mode = str(p.get("style", "full") or "full").lower()
                        if mode not in ("card", "full"):
                            mode = "full"
                        if force_cards:
                            mode = "card"
                    entry = {
                        "file":            f"broll/{fname}",
                        "start_in_output": round(edl_off[seg_i], 3),
                        "delay":           round(t - edl_off[seg_i], 3),
                        "span":            1,
                        "duration":        dur,
                    }
                    if is_img:
                        entry["is_image"] = True
                        entry["mode"] = mode
                    else:
                        entry["src_in"] = round(max(0.0, _ain), 3)   # start the clip at the action
                    broll_entries.append(entry)
                    placed_ts.append(t)
                    summ = {"file": fname, "at_sec": round(t, 1),
                            "duration": dur, "quote": p.get("quote", ""), "source": source}
                    if is_img:
                        summ["kind"] = "photo"
                        summ["style"] = mode
                    broll_summary.append(summ)
                    kind_txt = f" [photo/{mode}]" if is_img else ""
                    _log(job_path, f"B-roll: '{fname}' at {t:.1f}s (on '{p.get('quote')}') for {dur:.1f}s [{source}]{kind_txt}")

                # Auto-matched first (respecting count + spacing)
                for p in placements:
                    if broll_count and sum(1 for e in broll_summary if e["source"] == "auto") >= broll_count:
                        break
                    _place(p, enforce_gap=True, source="auto")
                # Then your manual additions — always honored, no spacing filter
                for p in broll_add:
                    _place(p, enforce_gap=False, source="manual")

                _log(job_path, f"B-roll: {len(broll_entries)} insertion(s) placed"
                               + (f" ({len(broll_add)} manual)" if broll_add else ""))
            else:
                _log(job_path, "B-roll: ANTHROPIC_API_KEY missing — skipping B-roll (no random fallback)")

            # Record the final placements so the chat can list/remove them precisely
            _j = json.loads(job_path.read_text())
            _j["broll_last"] = broll_summary
            job_path.write_text(json.dumps(_j, indent=2))

            edl["broll"] = broll_entries
            (project_dir / "edl.json").write_text(json.dumps(edl, indent=2))
        elif _had_clips:
            # Clips exist but b-roll was deliberately zeroed/disabled for this video
            # (the reason was already logged just above) — say nothing misleading.
            pass
        else:
            # Genuinely no library. The reference footage itself is never copied (it
            # belongs to someone else), so if the reference is B-roll heavy, tell the
            # owner the ONE thing to do to get cutaways.
            _bi_want = str((client.get("style_profile") or {}).get("broll_intensity") or "").strip().lower()
            if _bi_want in ("light", "moderate", "heavy"):
                _log(job_path, f"B-roll: the reference style is '{_bi_want}' on cutaways, but this "
                               f"client has NO B-roll clips to use — add clips to the client's B-roll "
                               f"library (or their Drive B-roll folder) and re-render to get them. "
                               f"Rendering this pass without B-roll.")
            else:
                _log(job_path, "B-roll: no clips in this client's library — skipping")

        # ── 5. Tighten cuts ────────────────────────────────────────────────────
        _check_cancelled(job_path)
        _set_status(job_path, "rendering")
        _log(job_path, "Tightening cuts (decay_clip)...")
        _run("decay_clip.py", str(project_dir))

        # ── 5a. Re-anchor auto beat zooms to the TIGHTENED timeline ────────────
        # decay_clip trims dead air from every range in place, so the output gets
        # shorter and the pre-decay beat-zoom times drift late (and trailing ones
        # can fall off the new end). Re-place them on the decayed ranges so each
        # zoom lands on its real beat. Only for cleanly auto-placed zooms.
        # ALWAYS reconcile zooms + output_duration to the POST-decay timeline, which
        # is the timeline compose actually renders. Auto beat zooms are recomputed on
        # the tightened cut; MANUAL/chat zooms keep the user's exact times and are only
        # clamped (do NOT re-map them — the editor already places them on the real
        # post-decay video). Writing output_duration as the true final length is what
        # makes the editor's ruler match the video, fixing the marker-vs-zoom drift.
        try:
            _de   = json.loads((project_dir / "edl.json").read_text())
            _tot2 = sum(r["end"] - r["start"] for r in _de["ranges"]) or 0.0
            if _reanchor_zoom:
                _src = _beat_zoom_events(_de["ranges"], _tot2,
                                         _profile_zoom_meta["cpm"], _profile_zoom_meta["zi"])
            else:
                _src = _de.get("zooms", [])      # keep the user's manual/chat zoom times
            _clamped = []
            for e in _src:
                try:
                    at = min(float(e["at"]), max(0.0, _tot2 - 0.5))
                except (TypeError, ValueError):
                    continue
                if at < 0:
                    continue
                dur = max(0.8, min(6.0, min(float(e.get("duration", 2.5)), max(0.8, _tot2 - at))))
                strg = max(0.06, min(0.30, float(e.get("strength", 0.12))))
                _clamped.append({"at": round(at, 2), "duration": round(dur, 2), "strength": round(strg, 3)})
            if _clamped:
                _de["zooms"] = _clamped
            else:
                _de.pop("zooms", None)
            (project_dir / "edl.json").write_text(json.dumps(_de, indent=2))
            _jr = json.loads(job_path.read_text())
            _jr["zoom_last"] = _clamped
            _jr["output_duration"] = round(_tot2, 2)
            job_path.write_text(json.dumps(_jr, indent=2))
            _log(job_path, f"Zoom/length: reconciled to post-decay — {len(_clamped)} zoom(s), {_tot2:.1f}s")
        except Exception as _e:
            _log(job_path, f"Zoom/length post-decay reconcile skipped ({_e})")

        # ── 5a2. Resolve on-screen graphics on the TIGHTENED timeline ──────────
        # Anchor each planned card/stat/lower-third to its spoken moment using the
        # POST-decay ranges (reloaded from disk, since decay_clip ran as a subprocess),
        # so a card lands on the right sentence instead of drifting late. A graphic
        # whose quote cannot be located is DROPPED, never dumped at t=0. build_overlays
        # renders each via Remotion; compose overlays it.
        if graphics_plan:
            try:
                _dg    = json.loads((project_dir / "edl.json").read_text())
                _gspk  = editing.get("caption_speaker", "speaker_0")
                _gtl   = _build_word_timeline(source_map, _gspk, _dg)
                _gtot  = sum(r["end"] - r["start"] for r in _dg["ranges"]) or 0.0
                _resolved = []
                for g in graphics_plan:
                    if not isinstance(g, dict):
                        continue
                    tmpl = g.get("template")
                    if tmpl not in _GRAPHIC_TEMPLATES:
                        continue
                    at = _find_quote_time(_gtl, g.get("quote", "")) if g.get("quote") else None
                    if at is None:
                        # Can't anchor it to a real spoken moment -> don't show it.
                        _log(job_path, f"Graphics: dropped {tmpl} — quote '{str(g.get('quote',''))[:40]}' not found")
                        continue
                    at  = max(0.0, min(float(at), max(0.0, _gtot - 1.0)))
                    dur = max(1.0, min(8.0, float(g.get("duration_sec", 3.0) or 3.0)))
                    dur = min(dur, max(1.0, _gtot - at))
                    _resolved.append({"template": tmpl, "props": g.get("props") or {},
                                      "start_sec": round(at, 2), "duration_sec": round(dur, 2)})
                if _resolved:
                    _dg["graphics"] = _resolved
                    (project_dir / "edl.json").write_text(json.dumps(_dg, indent=2))
                    _log(job_path, "Graphics: " + ", ".join(
                        f"{g['template']}@{g['start_sec']:.1f}s" for g in _resolved))
            except Exception as _e:
                _log(job_path, f"Graphics: resolution skipped ({_e})")

        # ── 5a3. Studio timeline MOVES: the editor's positions win over AI placement.
        # graphics carry absolute start_sec; b-roll carries at_sec (absolute), both
        # honoured directly by compose. Applied last so nothing regenerates over them.
        _gov, _bov = job.get("graphics_override"), job.get("broll_override")
        if _gov is not None or _bov is not None:
            try:
                _dm = json.loads((project_dir / "edl.json").read_text())
                if _gov is not None:
                    _dm["graphics"] = _gov
                    _log(job_path, f"Studio: {len(_gov)} graphic position(s) set")
                if _bov is not None:
                    _dm["broll"] = _bov
                    _log(job_path, f"Studio: {len(_bov)} b-roll position(s) set")
                (project_dir / "edl.json").write_text(json.dumps(_dm, indent=2))
            except Exception as _e:
                _log(job_path, f"Studio moves skipped ({_e})")

        # Chat "use clip X from 10s to 15s": stamp the source in/out onto matching b-roll
        # entries (by filename + optional at_sec). LAST b-roll mutation so an explicit span
        # wins over auto placement AND Studio drags. Photos are skipped.
        _btrims = job.get("broll_trims") or []
        if _btrims:
            try:
                _dm = json.loads((project_dir / "edl.json").read_text())
                _imgs = (".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".gif")
                _n = 0
                for _en in _dm.get("broll", []):
                    if _en.get("is_image") or Path(str(_en.get("file", ""))).suffix.lower() in _imgs:
                        continue
                    _enm = Path(str(_en.get("file", ""))).name.lower()
                    _eat = _en.get("at_sec")
                    if _eat is None:
                        _eat = float(_en.get("start_in_output", 0) or 0) + float(_en.get("delay", 0) or 0)
                    for _t in _btrims:
                        if Path(str(_t.get("file", ""))).name.lower() != _enm:
                            continue
                        if _t.get("at_sec") is not None and abs(float(_t["at_sec"]) - float(_eat)) > 0.75:
                            continue
                        _en["src_in"] = round(max(0.0, float(_t.get("src_in", 0.0))), 3)
                        if _t.get("src_out") is not None:
                            _en["src_out"] = round(float(_t["src_out"]), 3)
                            _en["duration"] = max(0.5, min(12.0, _en["src_out"] - _en["src_in"]))
                        _n += 1
                        break
                (project_dir / "edl.json").write_text(json.dumps(_dm, indent=2))
                if _n:
                    _log(job_path, f"Studio/chat: {_n} b-roll source span(s) applied")
            except Exception as _e:
                _log(job_path, f"B-roll trims skipped ({_e})")

        # Materialize any b-roll file not yet staged, so a clip the operator ADDED from
        # Drive in the editor renders even when the auto b-roll path was skipped (its file
        # was never pulled). Copy from the Drive pull / local library, else fetch by
        # drive_id, else drop the entry so compose never fails opening a missing file.
        try:
            _bdir = project_dir / "broll"; _bdir.mkdir(exist_ok=True)
            _lib = BASE_DIR / "broll_library" / job.get("client_id", "")
            _bsrc = project_dir / "broll_src"
            _dm = json.loads((project_dir / "edl.json").read_text())
            _entries = _dm.get("broll", [])
            _kept = []
            for _en in _entries:
                _nm = Path(str(_en.get("file", ""))).name
                if not _nm:
                    continue
                _dest = _bdir / _nm
                if _dest.exists() and _dest.stat().st_size > 0:
                    _kept.append(_en); continue
                _ok = False
                for _cand in (_bsrc / _nm, _lib / _nm):
                    if _cand.exists():
                        try:
                            shutil.copy2(_cand, _dest); _ok = True; break
                        except Exception:
                            pass
                if not _ok and _en.get("drive_id"):
                    try:
                        from integrations import gdrive as _gd
                        _ok = bool(_gd.download_file(_en["drive_id"], _dest))
                    except Exception:
                        _ok = False
                if _ok:
                    _kept.append(_en)
                else:
                    _log(job_path, f"B-roll: added clip '{_nm}' unavailable — skipping")
            if len(_kept) != len(_entries):
                _dm["broll"] = _kept
                (project_dir / "edl.json").write_text(json.dumps(_dm, indent=2))
        except Exception as _e:
            _log(job_path, f"B-roll materialize skipped ({_e})")

        # ── 6. Compose ─────────────────────────────────────────────────────────
        _log(job_path, "Rendering — normalize → concat → overlays → loudnorm (this takes a while)...")
        _run("compose.py", str(project_dir))

        # ── 7. Done ────────────────────────────────────────────────────────────
        final = project_dir / "final.mp4"
        if not final.exists():
            raise RuntimeError("compose.py finished but final.mp4 not found")

        size_mb = final.stat().st_size / (1024 * 1024)
        _log(job_path, f"Done — final.mp4 is {size_mb:.1f} MB")

        # Persist edl.json + captions.json on the volume (tiny) so the Studio editor
        # can read the finished cut's settings + caption text after scratch is wiped.
        # raw_dir may not exist yet for a Drive-pulled + Drive-delivered job (no local
        # upload created it, and delivery kept no local copy) — create it, or these
        # writes fail silently and the editor shows "no saved edit".
        raw_dir.mkdir(parents=True, exist_ok=True)
        try:
            edl_src = project_dir / "edl.json"
            if edl_src.exists():
                shutil.copy2(edl_src, raw_dir / "edl.json")
            cap_src = project_dir / "captions.json"
            if cap_src.exists():
                shutil.copy2(cap_src, raw_dir / "captions.json")
        except Exception:
            pass

        # Caption-free proxy for the Studio "captions off" preview, so the caption
        # drag has no burned-in duplicate. It's the post-cut/zoom base (no overlays),
        # downscaled small. Best-effort — the editor falls back to the full video.
        try:
            _base = project_dir / ("base30_zoom.mkv" if (project_dir / "base30_zoom.mkv").exists()
                                   else "base30.mkv")
            if _base.exists():
                subprocess.run(
                    ["ffmpeg", "-y", "-v", "error", "-i", str(_base),
                     "-vf", "scale='min(720,iw)':-2", "-threads", os.environ.get("FFMPEG_THREADS", "4"),
                     "-c:v", "libx264", "-preset", "veryfast", "-crf", "30",
                     "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart",
                     str(raw_dir / "proxy.mp4")], check=True, timeout=300)
        except Exception as _e:
            _log(job_path, f"Studio: caption-free proxy skipped ({_e})")

        client_name = job.get("client_name", "Unknown client")
        folder      = job.get("folder_name", job_id)
        out_size    = final.stat().st_size

        # ── 8. Deliver to Drive first. The returned link is our confirmation the
        #      finished video is safely in Drive (full Drive backend). On success
        #      we keep NO local copy — Drive is its home. Only if delivery does not
        #      confirm do we fall back to keeping the file on the volume so it is
        #      never lost and the Download button still works.
        drive_link = None
        try:
            from integrations import delivery as _delivery
            if _delivery.is_active():
                match_name = job.get("folder_name") or job_id
                _log(job_path, f"Delivery: uploading '{match_name}' to {client_name or 'Drive'}...")
                drive_link = _delivery.deliver_finished(match_name, client_name, final, log=lambda m: _log(job_path, m))
        except Exception as _e:
            _log(job_path, f"Delivery: skipped ({_e})")

        out_path = ""
        if drive_link:
            _log(job_path, "Finished video stored in Drive — no local copy kept")
        else:
            try:
                raw_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(final, raw_dir / "final.mp4")
                out_path = str(raw_dir / "final.mp4")
            except Exception as e:
                _log(job_path, f"note: could not keep a local copy of the finished video ({e})")

        job = json.loads(job_path.read_text())
        job["status"]      = "done"
        job["output_path"] = out_path
        job["output_size"] = out_size
        if drive_link:
            job["drive_link"] = drive_link
        job_path.write_text(json.dumps(job, indent=2))

        # Ping the creator's chosen channel(s) — Telegram / Slack / Discord — with the
        # Drive link. Configured in the Control Center; Slack via env still works too.
        try:
            from integrations import notify as _notify
            _notify.send_finished(client_name, folder, drive_link or "",
                                  lambda m: _log(job_path, m))
        except Exception as _ne:
            _log(job_path, f"notify skipped ({_ne})")

        # ── 9. Render intermediates are cleaned in the `finally` below, so cleanup
        #      runs on success AND on failure. A failed render must never leave its
        #      working files behind — that is what filled the volume.

    except Exception as exc:
        msg = str(exc)
        if msg == "__CANCELLED__":
            _log(job_path, "Job cancelled by user")
            return
        if msg.startswith("__TIMEOUT__"):
            _log(job_path, f"ERROR: Job timed out after {MAX_JOB_MINUTES} minutes — click Retry")
            _set_status(job_path, "failed")
            return
        _log(job_path, f"ERROR: {exc}")
        _set_status(job_path, "failed")
        job = json.loads(job_path.read_text())
        client_name = job.get("client_name", "Unknown client")
        folder      = job.get("folder_name", job_id)
        # One failure ping to the creator's chosen channel(s).
        try:
            from integrations import notify as _notify
            _notify.send_failed(client_name, folder, str(exc), lambda m: _log(job_path, m))
        except Exception:
            pass

    finally:
        # The render scratch dir is entirely ephemeral, so remove it whole on
        # success, failure or cancel — nothing lingers. The raw upload and the
        # copied-back final.mp4 live under raw_dir on the volume, untouched here.
        try:
            shutil.rmtree(project_dir, ignore_errors=True)
        except Exception:
            pass
