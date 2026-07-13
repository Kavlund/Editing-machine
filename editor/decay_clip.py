#!/usr/bin/env python3
"""Tighten every cut in an EDL by trimming the dead air around each segment,
in place. Run this AFTER you've set rough word-boundary start/end times and
BEFORE compose.py.

WHY: the perceived "too long pause" at a cut is usually the low-energy trailing
DECAY of a drawn-out final word (e.g. "baaagefteer") — not true silence, so
silencedetect misses it. This clips each segment's end to where the audible
energy actually stops, and each start to a tiny lead, capped so it never bleeds
into the off-camera reader on the same track.

Usage:
    python decay_clip.py <project_dir>
    python decay_clip.py <project_dir> --tail 0.05 --lead 0.015 --only IMG_1925
    python decay_clip.py <project_dir> --from-index 8        # only re-clip seg>=8
"""
from __future__ import annotations
import argparse, json, subprocess, wave
from pathlib import Path
import numpy as np

DROP_DB = 24.0        # energy this far below the clip's peak counts as "decay / pause"
MIN_WORD = 0.16       # always keep at least this much of the final word
READER = "speaker_1"  # off-camera reader id (caps so cuts never bleed into it)


def load_audio(path):
    wavp = Path("/tmp")/f"_decayclip_{Path(path).stem}.wav"
    subprocess.run(["ffmpeg","-y","-v","error","-i",str(path),"-ac","1","-ar","48000",
                    "-f","wav",str(wavp)], check=True)
    w = wave.open(str(wavp),"rb"); sr = w.getframerate()
    a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32)/32768.0
    return a, sr

def env(a, sr, t0, t1, step=0.01):
    out = []
    for i in range(int(t0*sr), int(t1*sr), int(step*sr)):
        seg = a[i:i+int(step*sr)]
        if len(seg) == 0: break
        out.append((i/sr, 20*np.log10(np.sqrt(np.mean(seg**2))+1e-9)))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("project", type=Path)
    ap.add_argument("--tail", type=float, default=0.05, help="seconds kept after audible end")
    ap.add_argument("--lead", type=float, default=0.015, help="seconds kept before first word")
    ap.add_argument("--only", default=None, help="only re-clip this source name")
    ap.add_argument("--from-index", type=int, default=0, help="only re-clip ranges at/after this index")
    a = ap.parse_args()

    edit = a.project.resolve()
    edl = json.loads((edit/"edl.json").read_text())
    cache, trans = {}, {}
    for name, rel in edl["sources"].items():
        cache[name] = load_audio(edit/rel)
        tr = json.loads((edit/"transcripts"/f"{name}.json").read_text())
        ws = [w for w in tr["words"] if w.get("type")=="word" and w.get("start") is not None]
        trans[name] = ws
    peak = {n: max(d for _, d in env(au, sr, 0, len(au)/sr)) for n, (au, sr) in cache.items()}

    for i, r in enumerate(edl["ranges"]):
        if i < a.from_index: continue
        if a.only and r["source"] != a.only: continue
        c = r["source"]; au, sr = cache[c]; s, e = r["start"], r["end"]
        s0 = [w for w in trans[c] if w["speaker_id"]!=READER and s-0.05 <= w["start"] < e]
        if not s0: continue
        fw, lw = s0[0], s0[-1]
        s1 = [w for w in trans[c] if w["speaker_id"]==READER]
        rns = min((w["start"] for w in s1 if lw["start"] <= w["start"] < lw["end"]+0.40), default=None)
        rb  = [w["end"] for w in s1 if w["end"] <= fw["start"] and w["end"] > fw["start"]-0.20]

        hi = min(lw["end"]+0.15, (rns-0.01) if rns else lw["end"]+0.15)
        be = lw["start"]
        for t, d in env(au, sr, lw["start"], hi):
            if d >= peak[c]-DROP_DB: be = t+0.01            # last audible-energy moment
        ne = be + a.tail
        ne = max(ne, lw["start"]+MIN_WORD)                  # don't gut a short word
        ne = min(ne, lw["end"]+0.06)                        # don't hold past the spoken word
        if rns is not None: ne = min(ne, rns-0.012)         # never bleed into the reader
        ns = fw["start"] - a.lead
        if rb: ns = max(ns, max(rb)+0.012)
        ns = max(ns, 0.0)
        r["start"], r["end"] = round(ns, 3), round(ne, 3)
        print(f"seg{i:2d} {c} {ns:.3f}->{ne:.3f}  last='{lw['text']}'")

    json.dump(edl, open(edit/"edl.json", "w"), ensure_ascii=False, indent=2)
    print(f"total ~{sum(r['end']-r['start'] for r in edl['ranges']):.1f}s")


if __name__ == "__main__":
    main()
