#!/usr/bin/env python3
"""Build the transparent overlay clips for one project:

  animations/title/title.mov     intro card (handwritten line + Impact caps)
  animations/captions/captions.mov  word-synced captions (phrase-coherent)

ffmpeg has no libass/drawtext here, so text is rendered with PIL and encoded as
ProRes 4444 (alpha) clips that compose.py overlays LAST (captions on top).

Everything visual is driven by the EDL "style" block (see example/edl.json), so
you never edit this file per video.

Usage:
    python build_overlays.py <project_dir> [all|title|captions]
"""
from __future__ import annotations
import gc, json, math, os, re, shutil, subprocess, sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

# Cap ffmpeg encoder threads to keep encode memory down on small containers
# (unbounded threads is part of what OOM-killed the ProRes caption encode).
FF_THREADS = os.environ.get("FFMPEG_THREADS", "4")

# Overlay canvas. These are DEFAULTS ONLY — main() overrides them from the EDL so
# overlays are built at the video's real frame size. Never assume 9:16 here: a
# 1080x1920 caption layer composited onto a 1920x1080 edit lands in the corner.
W, H = 1080, 1920
FPS = 30
VS = 1.0        # vertical scale vs the 1920-tall frame these defaults were tuned on

# ----- defaults (overridable per project via EDL style.fonts / style.captions) -----
DEFAULT_FONTS = {
    "handwritten": ["/System/Library/Fonts/Noteworthy.ttc", 1],
    "impact":      ["/System/Library/Fonts/Supplemental/Impact.ttf", 0],
    "caption":     ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0],
}
# Spoken Danish numbers -> digits (reference caption style). Extend via style.captions.number_map.
DEFAULT_NUMBER_MAP = [
    [r"\bhundrede procent\b", "100%"], [r"\bseks\b", "6"], [r"\bsyv\b", "7"],
]
# Connector/article/pronoun words a caption line must never END on (Danish).
DEFAULT_STOP = {
    "og","i","at","på","til","en","et","den","det","du","din","dit","dine","der",
    "som","af","om","så","men","for","vi","jeg","er","vil","kan","har","de","han",
    "hun","sin","mit","min","ved","fra","med","eller","dig","mig","sig","os","jer",
    "dem","ham","hende","ens",
}
PHRASE_END = set(".,!?;:")

# Readability sets for line breaking inside a caption. EN + DA union, so both English
# (Rooney / Claire / Max) and Danish (Kavlund) benefit with NO language detection — a
# word only ever matters when it actually appears in that language's caption.
# _LINE_TAIL_AVOID: forward-binding function words a line should never END on.
_LINE_TAIL_AVOID = {
    # English: prepositions / articles / conjunctions / determiners
    "the", "a", "an", "to", "of", "in", "on", "at", "by", "for", "with", "from", "as",
    "into", "onto", "about", "and", "but", "or", "nor", "so", "yet", "that", "this",
    "these", "those", "your", "my", "our", "their", "his", "her", "its", "no", "every", "each",
    # Danish
    "og", "men", "eller", "at", "som", "i", "på", "med", "til", "af", "om", "fra", "over",
    "under", "mod", "ved", "efter", "før", "uden", "gennem", "igennem", "hos", "mellem",
    "hvor", "når", "fordi", "en", "et", "den", "det", "de", "din", "dit", "dine", "min",
    "mit", "mine", "sin", "sit", "vores", "deres", "hans", "hendes",
}


def _wrap_words(words_list, fnt, max_w):
    """Greedy width wrap, improved for readability: never END a line on a forward-binding
    function word (which also makes any connective start the next line), and never leave a
    lone word on a two-line caption's second line."""
    def wide(ws):
        return text_size(fnt, " ".join(ws))[0]
    lines, i, n = [], 0, len(words_list)
    while i < n:
        j = i + 1
        while j < n and wide(words_list[i:j + 1]) <= max_w:
            j += 1
        # For a non-final line, never end on a forward-binding function word: push it to
        # the next line (which also makes any connective START the next line). Keep at
        # least two words on the line so we don't create needless orphans.
        if j < n:
            while j - i >= 3:
                lw = words_list[j - 1]
                if lw and lw[-1] not in ".!?" and _norm_word(lw) in _LINE_TAIL_AVOID:
                    j -= 1
                else:
                    break
        lines.append(words_list[i:j]); i = j
    # top-heavy: no single orphaned word on the second line of a two-line caption
    if (len(lines) == 2 and len(lines[1]) == 1 and len(lines[0]) >= 3
            and wide(lines[0][-1:] + lines[1]) <= max_w):
        lines = [lines[0][:-1], lines[0][-1:] + lines[1]]
    return lines


def font(spec, size, weight=None):
    """Load a font for drawing.

    Two safeguards: a broken font file never kills the render (we fall back to a
    real system font), and `weight` picks the right instance from a VARIABLE font
    — Oswald[wght]/Caveat[wght] open at Regular unless told otherwise.
    """
    path, idx = spec[0], spec[1]
    try:
        f = ImageFont.truetype(path, size, index=idx)
    except Exception as e:
        for fb in ("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
                   "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
                   "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
            if Path(fb).exists():
                print(f"font: '{path}' is unusable ({e}) — falling back to {fb}", file=sys.stderr)
                f = ImageFont.truetype(fb, size)
                break
        else:
            raise
    if weight:
        try:
            # clamp so an out-of-range value never raises; single 'wght' axis on
            # our variable faces (Nunito/Oswald/Caveat). Static faces just ignore it.
            f.set_variation_by_axes([int(max(100, min(900, int(weight))))])
        except Exception:
            pass  # a static font, or no variable-font support — use it as-is
    return f

def ease_out_cubic(t):
    return 1 - (1 - t) ** 3

def hex_to_rgba(hex_color: str) -> tuple:
    h = hex_color.lstrip("#")
    if len(h) == 3: h = h[0]*2 + h[1]*2 + h[2]*2
    return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16), 255)

def draw_centered(d, cx, cy, text, fnt, color=(255,255,255,255)):
    d.text((cx, cy), text, font=fnt, fill=color, anchor="mm")

def text_size(fnt, text):
    d = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    b = d.textbbox((0, 0), text, font=fnt)
    return b[2]-b[0], b[3]-b[1]

def layer_with_shadow(render_fn, shadows):
    base = Image.new("RGBA", (W, H), (0,0,0,0))
    render_fn(ImageDraw.Draw(base))
    alpha = base.split()[3]
    canvas = Image.new("RGBA", (W, H), (0,0,0,0))
    for sh in shadows:
        a = alpha.point(lambda v, k=sh["alpha"]: int(v*k/255))
        shadow = Image.merge("RGBA", (Image.new("L",(W,H),0),)*3 + (a,))
        canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(sh["blur"])), sh["offset"])
    canvas.alpha_composite(base)
    return canvas

def crop_to_content(img):
    bbox = img.getbbox()
    if not bbox:
        return img, (W//2, H//2)
    return img.crop(bbox), ((bbox[0]+bbox[2])//2, (bbox[1]+bbox[3])//2)

def encode_mov(frames_dir, out_path):
    subprocess.run(["ffmpeg","-y","-v","error","-framerate",str(FPS),
                    "-i", str(frames_dir/"f_%05d.png"),
                    "-threads", FF_THREADS,
                    "-c:v","prores_ks","-profile:v","4444","-pix_fmt","yuva444p10le",
                    str(out_path)], check=True)

def load_style(edl):
    s = edl.get("style", {})
    fonts = {**DEFAULT_FONTS, **s.get("fonts", {})}
    return s, fonts


# ============================== TITLE ==============================

def build_title(edit, edl):
    s, fonts = load_style(edl)
    t = s.get("title")
    if not t:
        print("no style.title -> skipping title.mov"); return
    out_dir = edit/"animations"/"title"; frames = out_dir/"frames"
    if frames.exists(): shutil.rmtree(frames)
    frames.mkdir(parents=True)

    f_hand = font(fonts["handwritten"], t.get("handwritten_size", 56))
    f_imp  = font(fonts["impact"], t.get("impact_size", 115), weight=700)
    L1 = t.get("handwritten", "")
    impact_lines = t.get("impact_lines", [])
    # Defaults are tuned for a 1920-tall frame; scale them to the real one.
    y1 = int(round(t.get("y_handwritten", 292) * VS))
    y2 = int(round(t.get("y_impact", 360) * VS))
    line_gap = int(round(t.get("impact_line_gap", 95) * VS))
    dur = float(t.get("duration", 4.5))

    big_shadows  = [{"offset":(0,12),"alpha":190,"blur":22},{"offset":(0,5),"alpha":230,"blur":8}]
    hand_shadows = [{"offset":(0,9),"alpha":200,"blur":18},{"offset":(0,3),"alpha":230,"blur":6}]

    _tcol = hex_to_rgba(t["color"]) if t.get("color") else (255, 255, 255, 255)
    def draw_big(d):
        for i, ln in enumerate(impact_lines):
            draw_centered(d, W//2, y2 + i*line_gap, ln, f_imp, _tcol)
    big  = layer_with_shadow(draw_big, big_shadows)
    hand = layer_with_shadow(lambda d: draw_centered(d, W//2, y1, L1, f_hand, _tcol), hand_shadows) if L1 else None
    text_full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text_full.alpha_composite(big)
    if hand is not None: text_full.alpha_composite(hand)
    # Optional solid panel behind the title (drawn first so the drop shadows fall on it).
    if t.get("bg"):
        bbox = text_full.getbbox()
        if bbox:
            padx, pady, rad = int(round(52*VS)), int(round(36*VS)), int(round(26*VS))
            bgc = hex_to_rgba(t["bg_color"]) if t.get("bg_color") else (10, 12, 16, 210)
            full = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(full).rounded_rectangle(
                [bbox[0]-padx, bbox[1]-pady, bbox[2]+padx, bbox[3]+pady], radius=rad, fill=bgc)
            full.alpha_composite(text_full)
        else:
            full = text_full
    else:
        full = text_full
    crop, (ccx, ccy) = crop_to_content(full)

    n = int(dur*FPS); in_t = out_t = 0.45
    for i in range(n):
        tt = i/FPS
        if tt < in_t:           p = ease_out_cubic(tt/in_t); scale = 0.86+0.14*p; alpha = p
        elif tt > dur-out_t:    p = (dur-tt)/out_t;          scale = 1.0;          alpha = max(0.0, p)
        else:                                                 scale = 1.0;          alpha = 1.0
        canvas = Image.new("RGBA", (W, H), (0,0,0,0))
        if alpha > 0:
            sw, sh = max(1,int(crop.width*scale)), max(1,int(crop.height*scale))
            layer = crop.resize((sw, sh), Image.LANCZOS)
            if alpha < 1.0:
                layer.putalpha(layer.split()[3].point(lambda v: int(v*alpha)))
            canvas.alpha_composite(layer, (ccx-sw//2, ccy-sh//2))
        canvas.save(frames/f"f_{i:05d}.png")
    encode_mov(frames, out_dir/"title.mov"); shutil.rmtree(frames)
    print(f"title.mov: {n} frames, {dur}s")


# ============================== CAPTIONS ==============================

def build_caption_chunks(edit, edl):
    s, _ = load_style(edl)
    cs = s.get("captions", {})
    speaker = cs.get("speaker", "speaker_0")          # on-camera speaker id
    number_map = DEFAULT_NUMBER_MAP + cs.get("number_map", [])
    stop = set(w.lower() for w in cs.get("stop_words", DEFAULT_STOP))
    caps_prefixes = cs.get("capitalize_prefixes", [])

    def clean_word(t):
        return (t or "").strip().replace("--", "").replace("…", "")
    def normalize_numbers(txt):
        for pat, rep in number_map:
            txt = re.sub(pat, rep, txt, flags=re.IGNORECASE)
        return txt
    def is_stop(w):
        return clean_word(w).lower().strip(".,!?;:") in stop

    # Each range pulls words from ITS source transcript, filtered to the
    # on-camera speaker (keeps the off-camera reader out of the captions).
    words_by_src = {}
    for name in edl["sources"]:
        tr = json.loads((edit/"transcripts"/f"{name}.json").read_text())
        words_by_src[name] = [w for w in tr["words"]
                              if w.get("type")=="word" and w.get("start") is not None
                              and (speaker is None or w.get("speaker_id")==speaker)]

    so_path = edit/"_seg_offsets.json"
    actual = json.loads(so_path.read_text()) if so_path.exists() else None

    chunks, offset = [], 0.0
    timed_words = []   # every on-camera word in OUTPUT time, for karaoke sync
    for si, r in enumerate(edl["ranges"]):
        ss, se = float(r["start"]), float(r["end"])
        seg_base = actual[si] if actual else offset
        seg_words = [w for w in words_by_src[r["source"]] if ss <= w["start"] < se]

        # Record each word's on-screen time span (maps source time -> timeline time)
        for w in seg_words:
            tw_text = clean_word(w["text"])
            if tw_text:
                timed_words.append({
                    "t": tw_text,
                    "s": (max(ss, w["start"]) - ss) + seg_base,
                    "e": (min(se, w.get("end", w["start"])) - ss) + seg_base,
                })

        seg_chunks, cur = [], []
        def flush():
            nonlocal cur
            if not cur: return
            txt = " ".join(clean_word(w["text"]) for w in cur)
            txt = normalize_numbers(" ".join(txt.split())).rstrip(",;:")
            if txt:
                st = max(ss, cur[0]["start"]) - ss + seg_base
                en = min(se, cur[-1]["end"]) - ss + seg_base
                seg_chunks.append([st, en, txt])
            cur = []
        for w in seg_words:
            cur.append(w)
            cw = clean_word(w["text"])
            chars = sum(len(clean_word(x["text"])) for x in cur)
            if cw and cw[-1] in PHRASE_END:                 # hard break on punctuation
                flush(); continue
            long_enough = len(cur) >= 3 or (len(cur) >= 2 and chars >= 14)
            if long_enough and not is_stop(cw):             # soft break, never on a stop word
                flush()
            elif len(cur) >= 5:
                flush()
        flush()
        # merge a lone short dangler into its same-sentence neighbour (never span 2 sentences)
        merged, i = [], 0
        while i < len(seg_chunks):
            ch = seg_chunks[i]; wl = ch[2].split()
            dangler = len(wl) == 1 and len(wl[0].strip(".,!?;:")) <= 4
            prev_ends = bool(merged) and merged[-1][2].rstrip()[-1:] in ".!?"
            if dangler and merged and not prev_ends and len(merged[-1][2].split()) <= 4:
                merged[-1][1] = ch[1]; merged[-1][2] += " " + ch[2]
            elif dangler and i+1 < len(seg_chunks) and ch[2].rstrip()[-1:] not in ".!?":
                nxt = seg_chunks[i+1]; nxt[0] = ch[0]; nxt[2] = ch[2] + " " + nxt[2]
                merged.append(nxt); i += 2; continue
            else:
                merged.append(ch)
            i += 1
        chunks.extend(merged); offset += (se - ss)

    # capitalize sentence-starts ASR tagged lowercase (cut into a take mid-run)
    for ch in chunks:
        for pre in caps_prefixes:
            if ch[2].startswith(pre):
                ch[2] = ch[2][0].upper() + ch[2][1:]
    chunks.sort(key=lambda c: c[0])
    for i in range(len(chunks)-1):                          # hold each caption until the next
        chunks[i][1] = chunks[i+1][0]
    if chunks:
        chunks[-1][1] += 0.5
    timed_words.sort(key=lambda w: w["s"])
    return chunks, timed_words


def _norm_word(w: str) -> str:
    return w.lower().strip(".,!?;:—–-\"'“”‘’")

def render_caption_image(text, fnt, cy, max_w, color=(255,255,255,255),
                         highlight_color=None, keywords=None, active_index=None):
    """Render a centered caption.
    - active_index (int): highlight the single word at that position (karaoke sync).
    - else keywords: highlight any word whose normalized form is in `keywords`.
    Everything else is drawn in `color`."""
    words_list = text.split()
    if not words_list:
        return Image.new("RGBA", (W, H), (0,0,0,0))
    # Word-wrap into lines (each a list of words), readability-aware: never end a line
    # on a function word, prefer to break before a connective, no orphaned last-line word.
    lines = _wrap_words(words_list, fnt, max_w)

    lh = int(text_size(fnt, "Ag")[1] * 1.15)
    total_h = lh * len(lines)
    sp_w = text_size(fnt, " ")[0]
    kw = set(keywords or [])
    use_kw = bool(kw) and highlight_color and highlight_color != color
    use_idx = active_index is not None and highlight_color is not None

    def render(d):
        y = cy - total_h // 2 + lh // 2
        widx = 0
        for words in lines:
            line_w = sum(text_size(fnt, w)[0] for w in words) + sp_w * (len(words) - 1)
            x = W // 2 - line_w // 2
            for w in words:
                if use_idx:
                    is_hl = (widx == active_index)
                else:
                    is_hl = use_kw and _norm_word(w) in kw
                d.text((x, y), w, font=fnt, fill=(highlight_color if is_hl else color), anchor="lm")
                x += text_size(fnt, w)[0] + sp_w
                widx += 1
            y += lh

    return layer_with_shadow(render, [{"offset":(0,8),"alpha":130,"blur":16},
                                       {"offset":(0,3),"alpha":190,"blur":6}])


def build_captions(edit, edl):
    s, fonts = load_style(edl)
    cs = s.get("captions", {})
    out_dir = edit/"animations"/"captions"; frames = out_dir/"frames"
    if frames.exists(): shutil.rmtree(frames)
    frames.mkdir(parents=True)

    chunks, timed = build_caption_chunks(edit, edl)

    # Studio caption-TEXT edits: replace a chunk's text where its original text
    # matches an override 'from' (text-match is stable across the regenerate-from-
    # transcript re-render, unlike a time index which drifts after a cut). An edited
    # chunk drops karaoke word-sync (its words no longer map to transcript timings).
    overrides = (edl.get("caption_overrides") or [])
    color_overrides = (edl.get("caption_color_overrides") or [])
    edited_spans = []
    chunk_color = {}          # (st,en) -> rgba for a caption given its own colour
    _ck = lambda t: re.sub(r"\s+", " ", str(t).strip().lower())
    omap = {_ck(o.get("from","")): str(o.get("to","")).strip()
            for o in overrides if isinstance(o, dict) and o.get("from")}
    cmap = {_ck(o.get("from","")): o.get("color")
            for o in color_overrides if isinstance(o, dict) and o.get("from") and o.get("color")}
    if omap or cmap:
        # Match on the chunk's ORIGINAL text BEFORE any text edit rewrites ch[2],
        # so per-caption text and colour both key off the same stable original text.
        for ch in chunks:
            key = _ck(ch[2])
            if key in cmap:
                try:
                    chunk_color[(ch[0], ch[1])] = hex_to_rgba(cmap[key])
                except Exception:
                    pass
            if key in omap and omap[key]:
                ch[2] = omap[key]
                edited_spans.append((ch[0], ch[1]))
        if omap:
            print(f"captions: applied {len(omap)} text edit(s)")
        if cmap:
            print(f"captions: applied {len(cmap)} colour edit(s)")

    # Persist the final chunks (text + output-time window) so the Studio editor can
    # list and edit caption text. Copied to the volume at finalize.
    try:
        (edit/"captions.json").write_text(json.dumps(
            [{"start": round(float(c[0]),2), "end": round(float(c[1]),2), "text": c[2]} for c in chunks],
            ensure_ascii=False, indent=2))
    except Exception:
        pass
    print(f"captions: {len(chunks)} chunks (karaoke word-sync)")

    # weight only bites on VARIABLE fonts (Nunito/Oswald/Caveat) — static faces
    # (Poppins-SemiBold, Arial Bold) ignore it — so captions render bold either way.
    f_cap = font(fonts["caption"], cs.get("font_size", 60), weight=cs.get("weight", 700))
    cy, max_w = cs.get("y", 1300), cs.get("max_width", 960)
    UP = bool(cs.get("uppercase"))
    def _disp(t): return t.upper() if UP else t   # display-only ALL CAPS (karaoke stays synced)
    raw_color = cs.get("color", "#ffffff")
    cap_color = hex_to_rgba(raw_color) if isinstance(raw_color, str) else tuple(raw_color)
    raw_hl = cs.get("highlight_color", "")
    hl_color = hex_to_rgba(raw_hl) if raw_hl else cap_color   # no accent -> no visible sweep

    # For each caption, attach its timed tokens and pre-render one image per
    # highlighted-word state (index -1 = none, 0..k-1 = that word in accent).
    EPS = 1e-3
    edited_set = set(edited_spans)
    built = []
    for st, en, txt in chunks:
        this_color = chunk_color.get((st, en), cap_color)   # per-caption colour or global
        toks = [tw for tw in timed if st - EPS <= tw["s"] < en - EPS]
        # An edited chunk renders its NEW text as-is (no karaoke: its words no longer
        # map to transcript timings). Same path as a chunk with no timed tokens.
        if not toks or (st, en) in edited_set:
            crop, (ccx, ccy) = crop_to_content(
                render_caption_image(_disp(txt), f_cap, cy, max_w, this_color, hl_color))
            built.append((st, en, [], [(crop, ccx, ccy)]))
            continue
        line_text = _disp(" ".join(t["t"] for t in toks))
        variants = []
        for active in range(-1, len(toks)):
            crop, (ccx, ccy) = crop_to_content(
                render_caption_image(line_text, f_cap, cy, max_w, this_color, hl_color,
                                     active_index=(active if active >= 0 else None)))
            variants.append((crop, ccx, ccy))
        built.append((st, en, toks, variants))
        print(f"  [{st:6.2f}-{en:6.2f}] {line_text}")

    total = (chunks[-1][1] if chunks else 0.0)
    n = int(math.ceil((total + 0.5)*FPS)); POP = 0.12
    for i in range(n):
        t = i/FPS
        canvas = Image.new("RGBA", (W, H), (0,0,0,0))
        active = next((b for b in built if b[0] <= t < b[1]), None)
        if active:
            st, en, toks, variants = active
            # Which word is being spoken now? Last token whose start has passed.
            aidx = -1
            for k, tw in enumerate(toks):
                if tw["s"] <= t:
                    aidx = k
                else:
                    break
            crop, ccx, ccy = variants[aidx + 1]   # variants[0] == "no highlight"
            age = t - st
            if age < POP:
                p = ease_out_cubic(age/POP); scale = 0.92+0.08*p; alpha = min(1.0, age/0.08)
            else:
                scale = 1.0; alpha = 1.0
            sw, sh = max(1,int(crop.width*scale)), max(1,int(crop.height*scale))
            layer = crop.resize((sw, sh), Image.LANCZOS)
            if alpha < 1.0:
                layer.putalpha(layer.split()[3].point(lambda v: int(v*alpha)))
            canvas.alpha_composite(layer, (ccx-sw//2, ccy-sh//2))
        canvas.save(frames/f"f_{i:05d}.png")
    # Release every pre-rendered caption image before the ProRes encode — on a long
    # video these variant bitmaps are hundreds of MB, and holding them WHILE ffmpeg
    # encodes is part of what OOM-killed this step. The PNGs on disk are all ffmpeg needs.
    built.clear(); gc.collect()
    encode_mov(frames, out_dir/"captions.mov"); shutil.rmtree(frames)
    print(f"captions.mov: {n} frames, {n/FPS:.2f}s")


HOOK_Y = 470   # vertical center of the hook — below the top edge, above the face


def build_hook(edit, edl):
    """Animated hook: pops in, holds, pops out over its own short window.
    Reads edl['hook'] = {text, start_sec, duration_sec}. Produces a clip that is
    exactly duration_sec long (compose.py places it starting at start_sec)."""
    hook = edl.get("hook")
    if not hook or not hook.get("text"):
        print("no hook -> skipping hook.mov"); return

    duration = max(2.0, float(hook.get("duration_sec", 6)))
    out_dir = edit / "animations" / "hook"
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prefer the code-based Remotion template (deterministic, version-controlled,
    # cannot break); fall back to the PIL renderer if Remotion is off/unavailable
    # or errors. Same output path + codec, so compose.py is unchanged either way.
    if os.environ.get("REMOTION_GRAPHICS") == "1":
        try:
            import remotion_render as _rr
            if _rr.available():
                _rr.render_hook(str(hook["text"]), out_dir / "hook.mov", W, H, duration, fps=FPS)
                print("hook.mov via Remotion"); return
            print("Remotion graphics on but project not built — using PIL hook", file=sys.stderr)
        except Exception as e:
            print(f"Remotion hook failed ({e}) — using PIL hook", file=sys.stderr)

    text     = str(hook["text"]).upper()
    _, fonts = load_style(edl)
    frames = out_dir / "frames"
    if frames.exists(): shutil.rmtree(frames)
    frames.mkdir(parents=True)

    f_hook = font(fonts["impact"], 66, weight=700)
    # White hook (distinct from orange keyword captions), with the shadow baked in
    layer = render_caption_image(text, f_hook, HOOK_Y, W - 120, (255, 255, 255, 255))
    crop, (ccx, ccy) = crop_to_content(layer)

    n = int(duration * FPS); in_t = 0.32; out_t = 0.32
    for i in range(n):
        tt = i / FPS
        if tt < in_t:                 p = ease_out_cubic(tt / in_t); scale = 0.82 + 0.18 * p; alpha = p
        elif tt > duration - out_t:   p = max(0.0, (duration - tt) / out_t); scale = 1.0; alpha = p
        else:                         scale = 1.0; alpha = 1.0
        canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if alpha > 0:
            sw, sh = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
            l = crop.resize((sw, sh), Image.LANCZOS)
            if alpha < 1.0:
                l.putalpha(l.split()[3].point(lambda v: int(v * alpha)))
            canvas.alpha_composite(l, (ccx - sw // 2, ccy - sh // 2))
        canvas.save(frames / f"f_{i:05d}.png")
    encode_mov(frames, out_dir / "hook.mov"); shutil.rmtree(frames)
    print(f"hook.mov: {n} frames ({duration:.1f}s), '{text}'")


def build_graphics(edit, edl):
    """Render each Remotion graphic in edl['graphics'] to animations/graphics/g{i}.mov.

    A no-op unless REMOTION_GRAPHICS=1 AND the node project is built — compose.py
    then overlays only the files that exist, so a disabled or failed graphic simply
    does not appear (never breaks the render)."""
    graphics = edl.get("graphics") or []
    if not graphics:
        return
    if os.environ.get("REMOTION_GRAPHICS") != "1":
        print("graphics: REMOTION_GRAPHICS off -> skipping"); return
    try:
        import remotion_render as _rr
    except Exception as e:
        print(f"graphics: remotion_render import failed ({e}) -> skipping", file=sys.stderr); return
    if not _rr.available():
        print("graphics: remotion project not built -> skipping", file=sys.stderr); return

    out_dir = edit / "animations" / "graphics"
    if out_dir.exists(): shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    brand  = edl.get("brand", {})
    # The client's chosen brand colour (resolved in _auto_edl, overridable per video
    # from the Studio editor). Falls back to the raw brand accent, then white.
    accent = edl.get("graphics_color") or brand.get("accent_color") or "#ffffff"
    for i, g in enumerate(graphics):
        tmpl = g.get("template")
        if not tmpl:
            continue
        # Honor the pipeline's already-fit duration (it clamps to the remaining
        # video); only guard the hard bounds so a near-end card's outro isn't cut.
        dur   = max(1.0, min(8.0, float(g.get("duration_sec", 3.0))))
        props = dict(g.get("props") or {})
        props.update({
            "durationInFrames": max(30, int(round(dur * FPS))),
            "width":  W, "height": H,
            "accent": props.get("accent") or accent,
        })
        # Retry once: a single Remotion/Chromium render can fail transiently
        # (memory pressure, a flaky headless launch), which is why a graphic
        # sometimes vanished from an otherwise-fine render.
        last_err = None
        for attempt in range(2):
            try:
                _rr.render_template(tmpl, out_dir / f"g{i}.mov", props)
                print(f"graphics: rendered g{i} ({tmpl})" + (" (retry)" if attempt else ""))
                last_err = None
                break
            except Exception as e:
                last_err = e
                print(f"graphics: g{i} ({tmpl}) attempt {attempt+1} failed ({e})", file=sys.stderr)
        if last_err is not None:
            print(f"graphics: g{i} ({tmpl}) skipped after retries", file=sys.stderr)


def main():
    edit = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    which = sys.argv[2] if len(sys.argv) > 2 else "all"
    edl = json.loads((edit/"edl.json").read_text())
    # Build overlays at the video's REAL frame size, not a hardcoded 9:16 canvas.
    global W, H, VS, HOOK_Y
    W = int(edl.get("width", 1080))
    H = int(edl.get("height", 1920))
    VS = H / 1920.0
    HOOK_Y = int(round(HOOK_Y * VS))     # hook sits at the same relative height
    print(f"overlays canvas: {W}x{H}")
    if which in ("all", "title"):    build_title(edit, edl)
    if which in ("all", "captions"): build_captions(edit, edl)
    if which in ("all", "hook"):     build_hook(edit, edl)
    if which in ("all", "graphics"): build_graphics(edit, edl)


if __name__ == "__main__":
    main()
