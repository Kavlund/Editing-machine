"""Full editing pipeline: normalize → transcribe → auto-EDL → decay → compose → final.mp4"""

from __future__ import annotations
import json, os, random, re, shutil, subprocess, sys, time, urllib.request
from datetime import datetime
from pathlib import Path

MAX_JOB_MINUTES = 45  # hard wall-clock limit per job

BROLL_EXTS = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}

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

def _font(kind: str) -> list:
    """Return [path, ttc_index] for a font, preferring macOS then Docker paths."""
    candidates = {
        "handwritten": [
            ("/System/Library/Fonts/Noteworthy.ttc", 1),
            ("/app/fonts/Caveat-Regular.ttf", 0),
            ("/usr/share/fonts/truetype/freefont/FreeSans.ttf", 0),
        ],
        "impact": [
            ("/System/Library/Fonts/Supplemental/Impact.ttf", 0),
            ("/app/fonts/Oswald-Bold.ttf", 0),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
        ],
        "caption": [
            ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0),
            ("/app/fonts/Poppins-SemiBold.ttf", 0),
            ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 0),
            ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
        ],
    }
    for path, idx in candidates.get(kind, []):
        if Path(path).exists():
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
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
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


def _generate_edit_plan(source_map: dict, instructions: str, client: dict,
                        anthropic_key: str, log_fn) -> dict:
    """One Claude call turns per-video instructions + transcript into a concrete plan.

    This is the personalization layer — every video gets its own plan from ITS
    instructions, so no two edits are templated the same.

    Returns:
      {
        "hook": {"text": str, "start_sec": float, "duration_sec": float} | None,
        "keywords": [str, ...],          # words to emphasize in captions
        "zoom": {"enabled": bool, "strength": float}
      }
    """
    plan = {"hook": None, "keywords": [], "zoom": {"enabled": False, "strength": 0.08}}
    transcript = _full_transcript(source_map)
    if not transcript:
        return plan

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
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
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
        '  "zoom": {"enabled": true/false, "strength": 0.06-0.12}\n'
        "}\n\n"
        "Rules:\n"
        "- LANGUAGE: write the hook and pick the keywords in the SAME language the speaker uses "
        "in the transcript (e.g. a Danish video gets a Danish hook and Danish keywords). Never translate to English.\n"
        "- Only include a hook if the instructions ask for one (hook / text / title). Otherwise null.\n"
        "- keywords: pick the 15-30 highest-impact CONTENT words across the whole script "
        "(nouns, verbs, numbers, names). These get highlighted as they appear in captions. "
        "Skip filler and function words. Lowercase them.\n"
        "- zoom.enabled only if instructions mention zoom / punch-in / movement.\n"
        "- Respect the instructions literally. If they say no hook, hook=null. If they don't mention zoom, zoom.enabled=false."
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
        log_fn(f"AI plan: hook={'yes' if plan['hook'] else 'no'}, "
               f"{len(plan['keywords'])} keyword(s), zoom={plan['zoom']['enabled']}")
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
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
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


# ── B-roll AI matching ───────────────────────────────────────────────────────

def _extract_frame(video: Path, out_jpg: Path, t: float | None = None):
    args = ["ffmpeg", "-y", "-v", "error"]
    if t is not None:
        args += ["-ss", f"{t:.2f}"]
    args += ["-i", str(video), "-frames:v", "1", "-vf", "scale=640:-1", "-q:v", "4", str(out_jpg)]
    subprocess.run(args, check=True, timeout=60)


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

    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)
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
            # sample a frame ~1s in (or start for very short clips)
            dur = 0.0
            try:
                r = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                                    "-of","default=noprint_wrappers=1:nokey=1", str(clip)],
                                   capture_output=True, text=True, timeout=30)
                dur = float(r.stdout.strip() or 0.0)
            except Exception:
                pass
            _extract_frame(clip, frame, t=min(1.0, dur/2) if dur else None)
            b64 = base64.standard_b64encode(frame.read_bytes()).decode()
            resp = sdk.messages.create(
                model="claude-sonnet-5",
                max_tokens=300,
                messages=[{"role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                    {"type": "text", "text":
                        "This is a frame from a B-roll video clip. Return STRICT JSON only:\n"
                        '{"description": "one plain sentence of what is shown", '
                        '"keywords": ["6-10 concrete nouns / actions / concepts a script might mention that this clip could illustrate"]}'},
                ]}],
            )
            raw = _resp_text(resp)
            m = re.search(r'\{.*\}', raw, re.DOTALL)
            info = json.loads(m.group()) if m else {"description": "", "keywords": []}
            info["keywords"] = [str(k).lower().strip() for k in info.get("keywords", []) if str(k).strip()]
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


def _plan_broll(source_map: dict, broll_tags: dict, instructions: str,
                anthropic_key: str, log_fn, desired_count: int | None = None) -> list:
    """Ask Claude where each B-roll clip best illustrates the script.
    Returns [{"file": name, "quote": "...", "duration_sec": float}].
    desired_count: exact number of cutaways to return (best-fitting); None = AI decides."""
    transcript = _full_transcript(source_map)
    if not transcript or not broll_tags:
        return []
    import anthropic as ant
    sdk = ant.Anthropic(api_key=anthropic_key, timeout=120.0, max_retries=1)

    catalog = "\n".join(
        f'- "{name}": {info.get("description","")} (keywords: {", ".join(info.get("keywords", []))})'
        for name, info in broll_tags.items()
    )
    if desired_count and desired_count > 0:
        count_rule = (f"- Place AT MOST {desired_count} cutaway(s) — and ONLY ones that clearly fit. "
                      f"If fewer than {desired_count} strongly match, place fewer (or none). "
                      f"Never pad up to the number with weak matches.\n")
    else:
        count_rule = ("- There is no target number. Place only strong matches, spaced out. Most talking-head "
                      "videos need only a few genuine cutaways — often zero.\n")
    system = (
        "You are a senior video editor placing B-roll cutaways over a talking-head video "
        "(one person speaking to camera). Return STRICT JSON only: a list of placements.\n\n"
        '[{"file": "<exact clip filename>", "quote": "<exact 2-5 word phrase from the transcript where this clip should START>", "duration_sec": 2.5}]\n\n'
        "THE BAR FOR PLACING A CLIP IS HIGH. Place a clip ONLY when its VISUAL CONTENT literally and "
        "specifically shows the object, action, place, or concept being spoken at that exact moment. "
        "A vague thematic, emotional, or 'kind of related' connection is NOT enough.\n"
        "  GOOD: speaker says 'lifting weights' + clip shows a gym/weights -> place it.\n"
        "  BAD:  speaker says 'boys and girls' + clip is a selfie of a person -> DO NOT place.\n"
        "  BAD:  speaker says 'cutting out dead space' + clip is a generic keyboard -> too loose, DO NOT place.\n\n"
        "HARD RULES:\n"
        "- NEVER use a clip that merely shows a person talking, a face, or a selfie. That is redundant over "
        "talking-head footage and is always wrong as B-roll.\n"
        "- Returning an EMPTY list [] is a correct, GOOD answer when nothing strongly fits. It is far better "
        "to place NOTHING than to place a clip that doesn't clearly match. Do NOT force placements.\n"
        "- The quote MUST be copied verbatim from the transcript (2-5 consecutive words) so it can be located.\n"
        + count_rule +
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


def _grade_from_style(style: dict) -> str:
    """Turn an analyzed reference clip's look into a concrete ffmpeg grade string."""
    warmth   = (style.get("grade_warmth") or "neutral").lower()
    contrast = (style.get("grade_contrast") or "normal").lower()
    sat      = (style.get("grade_saturation") or "normal").lower()
    # colorlevels: lower max = that channel boosted more
    if "warm" in warmth:   rimax, gimax, bimax = 0.90, 0.91, 0.95
    elif "cool" in warmth: rimax, gimax, bimax = 0.95, 0.95, 0.82
    else:                  rimax, gimax, bimax = 0.92, 0.92, 0.88
    c = {"low": 0.98, "normal": 1.02, "high": 1.10}.get(contrast, 1.02)
    s = {"muted": 0.85, "normal": 1.0, "vivid": 1.18}.get(sat, 1.0)
    return (f"colorlevels=rimax={rimax}:gimax={gimax}:bimax={bimax},"
            f"eq=saturation={s}:contrast={c},unsharp=5:5:0.3:5:5:0.0")


def _auto_edl(project_dir: Path, source_map: dict, client: dict,
              hook_plan: dict | None = None,
              keywords: list | None = None,
              zoom_enabled: bool = False,
              zoom_strength: float = 0.08,
              filler_indices: dict | None = None) -> dict:
    editing = client.get("editing", {})
    speaker = editing.get("caption_speaker", "speaker_0")
    GAP     = 0.5   # silence gap in seconds that splits a range
    MIN_DUR = 0.3   # ranges shorter than this are discarded

    # Precedence for grade + caption size:
    #   1. Specific-instruction directives (mandatory, highest)
    #   2. Style reference (analyzed clips)
    #   3. Client default settings
    style      = client.get("style_profile") or {}
    directives = client.get("_directives", {})

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
    edl_sources = {
        n: str(s["norm"].relative_to(project_dir))
        for n, s in source_map.items()
        if s["norm"].exists()
    }

    brand = client.get("brand", {})
    accent_color = brand.get("accent_color", "")

    # Caption body color: a mandatory directive wins (e.g. "only red captions"),
    # then the client's explicit setting, then white.
    caption_color = directives.get("caption_color") or editing.get("caption_color", "") or "#ffffff"
    # Keyword emphasis color: directive wins, else brand accent.
    highlight_color = directives.get("highlight_color") or accent_color or ""

    edl: dict = {
        "version": 1,
        "sources": edl_sources,
        "grade": grade_str,
        "ranges": ranges,
        "style": {
            "fonts": fonts,
            "captions": {
                "speaker":         speaker,
                "font_size":       cap_size,
                "y":               editing.get("caption_y", 1300),
                "max_width":       editing.get("caption_max_width", 960),
                "color":           caption_color,
                "highlight_color": highlight_color,
                "keywords":        keywords or [],   # keyword-emphasis mode
            },
        },
        "broll": [],
        "hook":          hook_plan,          # {text, start_sec, duration_sec} | None
        "zoom_enabled":  zoom_enabled,
        "zoom_strength": zoom_strength,
        "brand":         brand,
    }

    # Only add a title card if the client profile has one configured
    title_cfg = editing.get("title")
    if title_cfg and title_cfg.get("impact_lines"):
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

        _PIPELINE_DIRS  = {"animations", "transcripts", "clips30", "broll"}
        _PIPELINE_STEMS = {"base30", "base30_zoom", "composited30", "final"}
        videos = sorted(
            p for p in raw_dir.rglob("*")
            if p.is_file()
            and not p.name.startswith(".")
            and p.suffix.lower() in VIDEO_EXTS
            and "_v30" not in p.stem
            and p.stem not in _PIPELINE_STEMS
            and not p.stem.startswith("seg_")
            and not any(part in _PIPELINE_DIRS for part in p.relative_to(raw_dir).parts)
        )
        if not videos:
            raise RuntimeError("No video files found in the uploaded folder")

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
        _check_cancelled(job_path)
        for name, s in source_map.items():
            if s["norm"].exists():
                _log(job_path, f"normalize: cached — {s['norm'].name}")
                continue
            _log(job_path, f"normalize: {s['raw'].name} → {s['norm'].name}")
            normalize(s["raw"], s["norm"])

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
                _log(job_path, f"transcribe: {s['raw'].name} ({lang or 'auto-detect'}, {n_spk or '?'} speakers)")
                transcribe_one(
                    video=s["raw"],
                    edit_dir=project_dir,
                    api_key=elevenlabs_key,
                    language=lang,
                    num_speakers=n_spk,
                    verbose=False,
                )
                _log(job_path, f"transcribe: done — {s['trans'].name}")

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

        # ── 3b. AI edit plan — filler cutting (default ON) + per-video extras ──
        palmier_instructions = job.get("palmier_instructions", "").strip()
        instr_l        = palmier_instructions.lower()
        hook_plan      = None
        keywords       = []
        zoom_enabled   = False
        zoom_strength  = 0.08
        filler_indices = None
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

            # Hook / keyword-emphasis / zoom come from the per-video instructions
            # (or a mandatory hook rule).
            _force_hook = directives.get("hook") == "force"
            if palmier_instructions or _force_hook:
                _check_cancelled(job_path)
                _log(job_path, "AI: building per-video edit plan...")
                eff_instructions = palmier_instructions
                if _force_hook and "hook" not in instr_l:
                    eff_instructions = (eff_instructions + " Always add a hook.").strip()
                plan = _generate_edit_plan(source_map, eff_instructions, client,
                                           anthropic_key, lambda m: _log(job_path, m))
                hook_plan     = plan["hook"]
                keywords      = plan["keywords"]
                zoom_enabled  = plan["zoom"]["enabled"]
                zoom_strength = plan["zoom"]["strength"]
                if hook_plan:
                    _log(job_path, f"AI: hook = '{hook_plan['text']}' "
                                   f"(shows {hook_plan['start_sec']:.0f}s–{hook_plan['start_sec']+hook_plan['duration_sec']:.0f}s)")

            # Apply the client's mandatory overrides on top of the plan (highest priority)
            if directives.get("hook") == "off":
                hook_plan = None
                _log(job_path, "AI: hook disabled by the client's specific instructions")
            if directives.get("zoom") == "off":
                zoom_enabled = False
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
                        filler_indices=filler_indices)

        # Apply per-job overrides (set via the job chat) on top of the generated EDL
        overrides = job.get("job_overrides", {})
        if overrides:
            if "grade" in overrides:
                edl["grade"] = overrides["grade"]
            caps = edl.setdefault("style", {}).setdefault("captions", {})
            for ok, ek in [("caption_y","y"),("caption_font_size","font_size"),
                           ("caption_color","color"),("highlight_color","highlight_color"),
                           ("caption_max_width","max_width")]:
                if ok in overrides:
                    caps[ek] = overrides[ok]
            _log(job_path, f"Job overrides applied: {list(overrides.keys())}")

        (project_dir / "edl.json").write_text(json.dumps(edl, indent=2))
        _log(job_path, f"EDL: {len(edl['ranges'])} ranges, {sum(r['end']-r['start'] for r in edl['ranges']):.1f}s raw")

        if not edl["ranges"]:
            raise RuntimeError(
                "No on-camera speech found in transcripts. "
                "Check the speaker setting on the client profile."
            )

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

        # A mandatory 'no B-roll' rule from the client's specific instructions wins
        if directives.get("broll") == "off":
            broll_count = 0
            _log(job_path, "B-roll: disabled by the client's specific instructions")

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

            if anthropic_key:
                _check_cancelled(job_path)
                total_dur = sum(r["end"] - r["start"] for r in edl["ranges"]) or 1.0
                mode_txt  = f"exactly {broll_count}" if broll_count else "AI-decided count of"
                _log(job_path, f"B-roll: tagging {len(clips)} clip(s), placing {mode_txt} cutaway(s)...")
                tags = tag_broll_clips(broll_src, clips, anthropic_key, lambda m: _log(job_path, m), cache_dir=local_broll)
                _log(job_path, "B-roll: matching clips to the transcript...")
                placements = _plan_broll(source_map, tags, palmier_instructions or "",
                                         anthropic_key, lambda m: _log(job_path, m),
                                         desired_count=broll_count)

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
                    broll_entries.append({
                        "file":            f"broll/{fname}",
                        "start_in_output": round(edl_off[seg_i], 3),
                        "delay":           round(t - edl_off[seg_i], 3),
                        "span":            1,
                        "duration":        dur,
                    })
                    placed_ts.append(t)
                    broll_summary.append({"file": fname, "at_sec": round(t, 1),
                                          "duration": dur, "quote": p.get("quote", ""), "source": source})
                    _log(job_path, f"B-roll: '{fname}' at {t:.1f}s (on '{p.get('quote')}') for {dur:.1f}s [{source}]")

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
        else:
            _log(job_path, "B-roll: no clips in this client's library — skipping")

        # ── 5. Tighten cuts ────────────────────────────────────────────────────
        _check_cancelled(job_path)
        _set_status(job_path, "rendering")
        _log(job_path, "Tightening cuts (decay_clip)...")
        _run("decay_clip.py", str(project_dir))

        # ── 6. Compose ─────────────────────────────────────────────────────────
        _log(job_path, "Rendering — normalize → concat → overlays → loudnorm (this takes a while)...")
        _run("compose.py", str(project_dir))

        # ── 7. Done ────────────────────────────────────────────────────────────
        final = project_dir / "final.mp4"
        if not final.exists():
            raise RuntimeError("compose.py finished but final.mp4 not found")

        size_mb = final.stat().st_size / (1024 * 1024)
        _log(job_path, f"Done — final.mp4 is {size_mb:.1f} MB")

        # Copy the finished video from ephemeral scratch onto the volume so the
        # Download button survives redeploys. The durable copy also goes to Drive
        # below. If the volume is full, keep serving it from scratch for now.
        out_final = final
        try:
            raw_dir.mkdir(parents=True, exist_ok=True)
            volume_final = raw_dir / "final.mp4"
            shutil.copy2(final, volume_final)
            out_final = volume_final
        except Exception as e:
            _log(job_path, f"note: finished video kept on scratch, not copied to the volume ({e})")

        # Persist edl.json on the volume too, so the "Edit video" chat can read the
        # finished cut's settings after the ephemeral scratch dir is wiped.
        try:
            edl_src = project_dir / "edl.json"
            if edl_src.exists():
                shutil.copy2(edl_src, raw_dir / "edl.json")
        except Exception:
            pass

        job = json.loads(job_path.read_text())
        job["status"]      = "done"
        job["output_path"] = str(out_final)
        job["output_size"] = out_final.stat().st_size
        job_path.write_text(json.dumps(job, indent=2))

        client_name = job.get("client_name", "Unknown client")
        folder      = job.get("folder_name", job_id)
        _slack(f":white_check_mark: *{client_name}* — `{folder}` is done. {size_mb:.1f} MB ready to download.")

        # ── 8. Deliver to client integrations (Notion CPS + Google Drive) ──────
        # Best-effort and inert until the client's credentials are configured.
        try:
            from integrations import delivery as _delivery
            if _delivery.is_active():
                match_name  = job.get("folder_name") or job_id
                client_name = job.get("client_name", "")
                _log(job_path, f"Delivery: uploading '{match_name}' to {client_name or 'Drive'}...")
                _delivery.deliver_finished(match_name, client_name, out_final, log=lambda m: _log(job_path, m))
        except Exception as _e:
            _log(job_path, f"Delivery: skipped ({_e})")

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
        _slack(f":x: *{client_name}* — `{folder}` failed: {str(exc)[:200]}")

    finally:
        # The render scratch dir is entirely ephemeral, so remove it whole on
        # success, failure or cancel — nothing lingers. The raw upload and the
        # copied-back final.mp4 live under raw_dir on the volume, untouched here.
        try:
            shutil.rmtree(project_dir, ignore_errors=True)
        except Exception:
            pass
