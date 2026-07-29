"""Pick the on-camera voice when a video has two speakers.

A script reader speaks each line off camera and the on-camera client repeats it,
so the transcript has two diarized speakers. The on-camera person is on the
closer/louder mic, so a loudness pass over the normalized audio picks them and
the off-camera reader is dropped. Every function is exception safe and returns
None on failure so the render never hard-fails (caller keeps today's behaviour).
"""
from __future__ import annotations

import json
import subprocess
import numpy as np


def _decode_mono(video_path, sr: int = 16000):
    """Decode a clip to mono float32 PCM in [-1, 1]; None on any failure."""
    try:
        r = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(video_path), "-vn", "-ac", "1",
             "-ar", str(sr), "-f", "s16le", "-"],
            capture_output=True, timeout=180)
        if r.returncode != 0 or not r.stdout:
            return None
        a = np.frombuffer(r.stdout, dtype=np.int16).astype(np.float32) / 32768.0
        return a if a.size else None
    except Exception:
        return None


def _rms_db(x) -> float:
    if x is None or x.size == 0:
        return -120.0
    rms = float(np.sqrt(np.mean(np.square(x))))
    return 20.0 * float(np.log10(rms + 1e-9))


def speaker_loudness(source_map: dict, editing: dict, sr: int = 16000) -> dict:
    """Per-source, per-speaker loudness: {source: {speaker_id: {rms_db, words, dur}}}.

    A speaker's score is the duration-weighted MEDIAN of its per-word RMS (median
    resists a few clipped or silent words)."""
    out = {}
    for name, s in source_map.items():
        try:
            if not s["trans"].exists():
                continue
            tr = json.loads(s["trans"].read_text())
            words = [w for w in tr.get("words", [])
                     if w.get("type") == "word" and w.get("start") is not None]
            if not words:
                continue
            audio = _decode_mono(s["norm"], sr)
            if audio is None:
                continue
            per = {}
            for w in words:
                spk = w.get("speaker_id", "speaker_0")
                try:
                    a = int(float(w["start"]) * sr)
                    b = int(float(w.get("end", w["start"])) * sr)
                except (TypeError, ValueError):
                    continue
                a = max(0, a)
                b = min(audio.size, max(a + 1, b))
                if b <= a:
                    continue
                d = per.setdefault(spk, {"rms": [], "words": 0, "dur": 0.0})
                d["rms"].append(_rms_db(audio[a:b]))
                d["words"] += 1
                d["dur"] += (b - a) / float(sr)
            tbl = {spk: {"rms_db": float(np.median(d["rms"])), "words": d["words"],
                         "dur": round(d["dur"], 2)}
                   for spk, d in per.items() if d["rms"]}
            if tbl:
                out[name] = tbl
        except Exception:
            continue
    return out


def choose_kept_speaker(per_speaker: dict, keep: str = "louder",
                        margin_db: float = 3.0, min_word_share: float = 0.15):
    """Which speaker to keep for ONE source, or None to keep everyone.

    Returns None (keep all) when there is only one real speaker or the top two are
    within margin_db (a genuine two-person video, not a reader + repeat)."""
    if not per_speaker or len(per_speaker) < 2:
        return None
    total = sum(v["words"] for v in per_speaker.values()) or 1
    cand = {k: v for k, v in per_speaker.items() if v["words"] / total >= min_word_share}
    if len(cand) < 2:
        return None
    ordered = sorted(cand.items(), key=lambda kv: kv[1]["rms_db"])   # quietest -> loudest
    if ordered[-1][1]["rms_db"] - ordered[-2][1]["rms_db"] < margin_db:
        return None                                   # too close -> keep everyone
    if keep == "quieter":
        return ordered[0][0]
    if keep == "both":
        return None
    return ordered[-1][0]                              # default: the louder on-camera voice
