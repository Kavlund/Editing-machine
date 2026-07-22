#!/usr/bin/env python3
"""Render the final vertical (1080x1920 @30fps) edit for one project.

Pipeline (the order matters — see README "Hard rules"):
  1. extract each EDL range @30fps with the grade + 30ms edge fades  (per-segment)
  2. lossless `-c copy` concat -> base30.mkv                          (no re-encode)
  3. (re)build captions on the ACTUAL measured timeline
  4. overlay b-roll, then title, then captions LAST                   (captions on top)
  5. two-pass loudnorm -> final.mp4

Usage:
    python compose.py <project_dir>
A project dir contains: edl.json, transcripts/<source>.json, and the normalised
<source>_v30.mov clips referenced by edl["sources"].
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loudnorm import apply_loudnorm_two_pass

HERE = Path(__file__).resolve().parent
FPS = 30


def run(cmd, quiet=True):
    try:
        subprocess.run(cmd, check=True,
                       stdout=subprocess.DEVNULL if quiet else None,
                       stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        # Surface ffmpeg's own error instead of swallowing it, so a failed render
        # shows WHY (missing stream, bad overlay input, etc.) not just an exit code.
        err = e.stderr.decode("utf-8", "replace") if isinstance(e.stderr, (bytes, bytearray)) else (e.stderr or "")
        sys.stderr.write("FFMPEG ERROR (exit %s): %s\n" % (e.returncode, err.strip()[-1500:]))
        sys.stderr.flush()
        raise

def probe_dur(path) -> float:
    out = subprocess.run(["ffprobe","-v","error","-show_entries","format=duration",
                          "-of","default=noprint_wrappers=1:nokey=1", str(path)],
                         capture_output=True, text=True)
    return float(out.stdout.strip() or 0.0)


def extract_segments(edit, edl):
    clips = edit/"clips30"; clips.mkdir(exist_ok=True)
    grade = edl.get("grade", "")
    OW, OH = int(edl.get("width", 1080)), int(edl.get("height", 1920))
    paths = []
    for i, r in enumerate(edl["ranges"]):
        s, e = float(r["start"]), float(r["end"])
        sq  = round(s*FPS)/FPS
        dur = round((e-s)*FPS)/FPS
        out = clips/f"seg_{i:02d}.mkv"
        # Fit inside the output frame and pad — never crop, so nothing is lost
        # when a source doesn't exactly match the target shape.
        vf = (f"scale={OW}:{OH}:force_original_aspect_ratio=decrease,"
              f"pad={OW}:{OH}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1"
              + (f",{grade}" if grade else ""))
        af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={max(0,dur-0.03):.3f}:d=0.03"
        src = edit/edl["sources"][r["source"]]
        run(["ffmpeg","-y","-v","error","-ss",f"{sq:.4f}","-i",str(src),
             "-t",f"{dur:.4f}","-vf",vf,"-af",af,
             "-c:v","libx264","-preset","fast","-crf","20",
             "-pix_fmt","yuv420p","-r",str(FPS),"-vsync","cfr",
             "-c:a","pcm_s16le","-ar","48000", str(out)])
        print(f"  seg {i:02d}  {sq:7.3f}+{dur:5.3f}s")
        paths.append(out)
    return paths


def apply_zoom(src, out, strength, ow=1080, oh=1920):
    """Slow continuous push-in across the whole clip (Ken Burns), applied to the
    base video BEFORE overlays so captions/hook stay locked in place.
    z ramps linearly 1.0 -> 1+strength over the full duration."""
    r = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                        "-count_frames","-show_entries","stream=nb_read_frames",
                        "-of","default=noprint_wrappers=1:nokey=1", str(src)],
                       capture_output=True, text=True)
    total = max(1, int((r.stdout.strip() or "1")))
    end_z = 1.0 + strength
    zexpr = f"min(1+{strength:.5f}*on/{total},{end_z:.5f})"
    # zoompan holds each input frame for one output frame (d=1) and re-crops per frame
    vf = (f"zoompan=z='{zexpr}':d=1:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={ow}x{oh}:fps={FPS}")
    run(["ffmpeg","-y","-v","error","-i",str(src),
         "-vf",vf,"-c:v","libx264","-preset","fast","-crf","18",
         "-pix_fmt","yuv420p","-c:a","copy", str(out)])
    print(f"  zoom applied: 1.0 -> {end_z:.3f} over {total} frames")


def apply_timed_zooms(src, out, events, ow=1080, oh=1920):
    """Punch in and hold at specific moments: at each event time the frame snaps
    tighter (fast ease-in), holds for its duration, then eases back to normal.
    Applied to the base video BEFORE overlays so captions/hook stay locked.
    events: [{"at": output_sec, "duration": sec, "strength": 0.04..0.30}]."""
    R = 0.18  # ease in / ease out, seconds
    terms = []
    for ev in events:
        a = max(0.0, float(ev.get("at", 0.0)))
        d = max(0.5, min(8.0, float(ev.get("duration", 2.5))))
        strg = max(0.04, min(0.30, float(ev.get("strength", 0.12))))
        tt = f"(on/{FPS})"
        # trapezoid pulse: rise over R, hold, fall over R — all inside [a, a+d]
        rise = f"clip(({tt}-{a:.3f})/{R},0,1)"
        fall = f"clip(({a + d:.3f}-{tt})/{R},0,1)"
        terms.append(f"{strg:.4f}*{rise}*{fall}")
    if not terms:
        return apply_zoom(src, out, 0.0001, ow, oh)  # no-op safety (shouldn't happen)
    zexpr = "1+" + "+".join(terms)
    vf = (f"zoompan=z='{zexpr}':d=1:"
          f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={ow}x{oh}:fps={FPS}")
    run(["ffmpeg","-y","-v","error","-i",str(src),
         "-vf",vf,"-c:v","libx264","-preset","fast","-crf","18",
         "-pix_fmt","yuv420p","-c:a","copy", str(out)])
    print(f"  timed zooms: {len(events)} punch-in(s) at "
          + ", ".join(f"{float(e.get('at',0)):.1f}s" for e in events))


def actual_offsets(edit, paths):
    """Cumulative output start of each segment from ACTUAL rendered frame counts
    (EDL float offsets drift ~1 frame/segment). Captions + b-roll align to this."""
    offs, durs = [0.0], []
    for p in paths:
        out = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
                              "-count_frames","-show_entries","stream=nb_read_frames",
                              "-of","default=noprint_wrappers=1:nokey=1", str(p)],
                             capture_output=True, text=True)
        d = int(out.stdout.strip())/FPS
        durs.append(d); offs.append(offs[-1]+d)
    (edit/"_seg_offsets.json").write_text(json.dumps(offs[:-1]))
    return offs[:-1], durs


def concat(edit, paths, out):
    lst = edit/"_concat30.txt"
    lst.write_text("".join(f"file '{p.resolve()}'\n" for p in paths))
    run(["ffmpeg","-y","-v","error","-f","concat","-safe","0","-i",str(lst),"-c","copy",str(out)])
    lst.unlink()


def overlay(edit, edl, base, out, starts, durs):
    OW, OH     = int(edl.get("width", 1080)), int(edl.get("height", 1920))
    title      = edit/"animations/title/title.mov"
    caps       = edit/"animations/captions/captions.mov"
    hook_mov   = edit/"animations/hook/hook.mov"
    broll = edl.get("broll", [])
    style = edl.get("style", {})
    title_dur = float(style.get("title", {}).get("duration", 0.0)) if (style.get("title") and title.exists()) else 0.0
    caps_dur  = probe_dur(caps) if caps.exists() else 0.0
    hook_dur  = probe_dur(hook_mov) if hook_mov.exists() else 0.0
    hook_cfg  = edl.get("hook") or {}
    hook_start = float(hook_cfg.get("start_sec", 0.0))

    edl_off, o = [], 0.0
    for r in edl["ranges"]:
        edl_off.append(o); o += r["end"]-r["start"]

    inputs = ["-i", str(base)]
    has_title = title.exists() and title_dur > 0
    has_caps  = caps.exists() and caps_dur > 0
    has_hook  = hook_mov.exists() and hook_dur > 0
    ti = ci = hi = None
    nin = 1
    if has_hook:  hi = nin; inputs += ["-i", str(hook_mov)];  nin += 1
    if has_title: ti = nin; inputs += ["-i", str(title)];     nin += 1
    if has_caps:  ci = nin; inputs += ["-i", str(caps)];      nin += 1
    bidx0 = nin
    OVL = 1.5/FPS
    _IMG = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
    # Precompute each B-roll's on-screen window so a still photo can be looped for
    # exactly its length (a video just plays its own frames).
    bwin = []
    for b in broll:
        seg_i = min(range(len(edl_off)), key=lambda k: abs(edl_off[k]-b["start_in_output"]))
        span  = int(b.get("span", 1))
        s = starts[seg_i] + float(b.get("delay", 0.0))
        clip_dur = float(b.get("duration", 0))
        e = s + clip_dur + OVL if clip_dur > 0 else starts[seg_i] + sum(durs[seg_i:seg_i+span]) + OVL
        is_img = Path(str(b["file"])).suffix.lower() in _IMG
        bwin.append((b, s, e, is_img))
        p = str(edit/b["file"])
        if is_img:
            inputs += ["-loop", "1", "-t", f"{max(0.3, e - s + 0.2):.3f}", "-i", p]
        else:
            inputs += ["-i", p]

    parts = ["[0:v]format=yuv420p[v0]"]
    # Hook is placed at its start_sec by shifting PTS; shown only for its own length
    if has_hook:  parts.append(f"[{hi}:v]setpts=PTS-STARTPTS+{hook_start}/TB[h1]")
    if has_title: parts.append(f"[{ti}:v]setpts=PTS-STARTPTS[t1]")
    if has_caps:  parts.append(f"[{ci}:v]setpts=PTS-STARTPTS[c1]")

    cur = "[v0]"
    for i, (b, s, e, is_img) in enumerate(bwin):
        idx = bidx0 + i
        if is_img and b.get("mode") == "card":
            # "BAM" card: the photo snaps up on a white card over the speaker,
            # centered in the upper third, and cuts out at the end of the window.
            parts.append(
                f"[{idx}:v]scale=660:900:force_original_aspect_ratio=decrease,"
                f"pad=iw+28:ih+28:14:14:color=white,"
                f"format=yuv420p,setpts=PTS-STARTPTS+{s}/TB[b{i}]")
            ov = f"overlay=x=(W-w)/2:y=(H-h)/2-200:enable='between(t,{s:.3f},{e:.3f})'"
        elif is_img:
            # Full-frame still: cover the frame + a gentle Ken Burns push-in, held
            # for the placement window (the looped input above gives it a timeline).
            nfr = max(1, int((e - s) * FPS))
            zexpr = f"min(1+0.06*on/{nfr},1.06)"
            parts.append(
                f"[{idx}:v]scale={OW}:{OH}:force_original_aspect_ratio=increase,crop={OW}:{OH},"
                f"zoompan=z='{zexpr}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={OW}x{OH}:fps={FPS},"
                f"format=yuv420p,setpts=PTS-STARTPTS+{s}/TB[b{i}]")
            ov = f"overlay=enable='between(t,{s:.3f},{e:.3f})'"
        else:
            parts.append(f"[{idx}:v]setpts=PTS-STARTPTS+{s}/TB[b{i}]")
            ov = f"overlay=enable='between(t,{s:.3f},{e:.3f})'"
        nl = f"[bo{i}]"
        parts.append(f"{cur}[b{i}]{ov}{nl}")
        cur = nl
    if has_hook:
        he = hook_start + hook_dur
        nl = "[oh]"
        parts.append(f"{cur}[h1]overlay=enable='between(t,{hook_start:.2f},{he:.2f})'{nl}"); cur = nl
    if has_title:
        nl = "[ot]"; parts.append(f"{cur}[t1]overlay=enable='between(t,0,{title_dur})'{nl}"); cur = nl
    if has_caps:
        nl = "[outv]"; parts.append(f"{cur}[c1]overlay=enable='between(t,0,{caps_dur:.2f})'{nl}"); cur = nl
    else:
        parts.append(f"{cur}null[outv]")

    run(["ffmpeg","-y","-v","error",*inputs,
         "-filter_complex",";".join(parts),"-map","[outv]","-map","0:a",
         "-c:v","libx264","-preset","fast","-crf","18","-pix_fmt","yuv420p",
         "-c:a","copy","-shortest", str(out)], quiet=False)


def main():
    edit = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    edl = json.loads((edit/"edl.json").read_text())
    OW, OH = int(edl.get("width", 1080)), int(edl.get("height", 1920))
    print(f"output frame: {OW}x{OH}")
    for f in ("clips30","base30.mkv","base30_zoom.mkv","composited30.mkv","_seg_offsets.json"):
        p = edit/f
        if p.is_dir():
            import shutil; shutil.rmtree(p)
        elif p.exists():
            p.unlink()

    print("extracting segments @30fps (pcm audio)...")
    paths = extract_segments(edit, edl)
    starts, durs = actual_offsets(edit, paths)
    print("building overlays on the measured timeline...")
    subprocess.run([sys.executable, str(HERE/"build_overlays.py"), str(edit), "all"], check=True)
    print("concat -> base30.mkv")
    concat(edit, paths, edit/"base30.mkv")

    # Zoom on the base video BEFORE overlays, so captions/hook stay put.
    # Timestamped punch-in-and-hold zooms take precedence over the slow global push-in.
    base = edit/"base30.mkv"
    zooms = edl.get("zooms") or []
    if zooms:
        print(f"applying {len(zooms)} timed punch-in zoom(s)...")
        zoomed = edit/"base30_zoom.mkv"
        apply_timed_zooms(base, zoomed, zooms, OW, OH)
        base = zoomed
    elif edl.get("zoom_enabled"):
        print("applying zoom push-in...")
        zoomed = edit/"base30_zoom.mkv"
        apply_zoom(base, zoomed, float(edl.get("zoom_strength", 0.08)), OW, OH)
        base = zoomed

    print("overlays (b-roll, hook, title, captions LAST) -> composited30.mkv")
    comp = edit/"composited30.mkv"
    overlay(edit, edl, base, comp, starts, durs)
    print("loudnorm -> final.mp4")
    apply_loudnorm_two_pass(comp, edit/"final.mp4")
    print(f"done: {edit/'final.mp4'}")


if __name__ == "__main__":
    main()
