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


def loud_word_keep(video_path, words, sr: int = 16000, gate_db: float = 10.0,
                   min_gap_db: float = 9.0, min_share: float = 0.15):
    """Per-WORD keep-mask that isolates the close-mic on-camera voice by loudness.

    In the reader+repeat workflow, an off-camera reader says each line and the on-camera
    client repeats it. The on-camera person is on the close mic (loud); the reader is far
    (much quieter) — a stable 15-20 dB gap. The existing speaker pick trusts the
    diarization SPEAKER LABELS, which drift and merge the two voices partway through, so
    the reader survives. This gates per word by loudness instead, catching a reader word
    even when it was mislabeled as the on-camera speaker.

    Returns a list of booleans aligned to `words` (True = keep), or None to keep all when
    the loudness is NOT clearly bimodal — so a genuine single speaker (even a dynamic one)
    or a real two-person talk at similar levels is never chopped.
    """
    audio = _decode_mono(video_path, sr)
    if audio is None:
        return None
    rms = []
    for w in words:
        if w.get("type") != "word" or w.get("start") is None:
            rms.append(None); continue
        try:
            a = max(0, int(float(w["start"]) * sr))
            b = min(audio.size, max(a + 1, int(float(w.get("end", w["start"])) * sr)))
        except (TypeError, ValueError):
            rms.append(None); continue
        rms.append(_rms_db(audio[a:b]) if b > a else None)
    vals = [r for r in rms if r is not None and r > -55]        # voiced words only
    if len(vals) < 10:
        return None
    s = sorted(vals)
    oncam = s[int(0.75 * (len(s) - 1))]                          # the close-mic level
    gate = oncam - gate_db
    quiet = [r for r in vals if r < gate]
    loud = [r for r in vals if r >= gate]
    # Only act on a genuine reader+repeat signature: a SUSTAINED quiet population that is
    # clearly separated from the on-camera voice. Otherwise keep everything.
    if not loud or len(quiet) < max(6, int(min_share * len(vals))):
        return None
    if (float(np.median(loud)) - float(np.median(quiet))) < min_gap_db:
        return None
    return [(r is None) or (r >= gate) for r in rms]


def reader_cut_spans(video_path, sr: int = 16000, gate_db: float = 13.0,
                     min_cut: float = 0.45, win_s: float = 0.10,
                     min_gap_db: float = 8.0, min_reader_share: float = 0.06):
    """SOURCE-TIME spans of the off-camera reader (and the dead air) to CUT.

    The reader+repeat workflow: an off-camera reader says each line and the on-camera
    client repeats it. The client is on the close mic and sits in a clear LOUD band; the
    reader is far and much quieter (a stable 15-20 dB gap, confirmed on the real clips —
    him ~-16 dBFS, the reader ~-30 to -40). This measures his band per clip and returns the
    SUSTAINED stretches that sit well below it — the reader plus the dead air around him —
    so his loud speech is kept and everything quieter is removed at the AUDIO level.

    Why audio-level, not per-word: it removes the reader even where the diarization merged
    the two voices onto one label, or the transcription garbled his overlapping quiet
    speech into gibberish. Cutting whole quiet SPANS (not dropping scattered words) also
    means no dead 'silent' gaps are left behind and no reliance on the transcription being
    right — which is exactly where the earlier per-word gate fell down.

    Returns a list of (start, end) source-time spans, or [] when there is no genuine reader
    signature (a real population of voiced-but-quiet windows, clearly separated from his
    band). A normal single-voice clip returns [] and is left for the ordinary pause trimmer.
    Never raises. Tunables: gate_db = how far below his level still counts as HIM (so his
    softer moments are kept); min_cut = only cut sustained quiet, never a brief soft word
    between two loud ones (never chops him mid sentence).
    """
    try:
        audio = _decode_mono(video_path, sr)
        if audio is None:
            return []
        win = max(1, int(win_s * sr))
        n = int(audio.size // win)
        if n < 20:
            return []
        seg = audio[:n * win].reshape(n, win)
        rms = np.sqrt(np.mean(np.square(seg), axis=1))
        db = 20.0 * np.log10(rms + 1e-9)
        top = float(np.percentile(db, 95))                     # his loud peaks
        voiced = db[db > top - 40.0]                           # drop pure silence
        if voiced.size < 10:
            return []
        his_level = float(np.percentile(voiced, 75))           # the close-mic band
        gate = his_level - gate_db                             # below here = reader / dead air
        silence_floor = his_level - 30.0                       # below here = silence, not voice
        his = db[db >= gate]
        reader = db[(db >= silence_floor) & (db < gate)]       # voiced but quiet = the reader
        # Only act on a real reader+repeat signature: a sustained quiet SECOND voice that is
        # clearly separated from his band. Otherwise keep everything (single voice, or two
        # people at similar levels) and let the ordinary pause trimmer handle the silences.
        if his.size == 0 or reader.size < max(4, int(min_reader_share * n)):
            return []
        if (float(np.median(his)) - float(np.median(reader))) < min_gap_db:
            return []
        keep = db >= gate                                      # True = his loud speech
        spans = []
        min_w = max(1, int(round(min_cut / win_s)))
        i = 0
        while i < n:
            if keep[i]:
                i += 1
                continue
            j = i
            while j < n and not keep[j]:
                j += 1
            if (j - i) >= min_w:                               # a SUSTAINED quiet stretch
                a = (i + 1) * win_s                            # pull edges in one window so
                b = (j - 1) * win_s                            # his adjacent words never clip
                if b - a >= 0.20:
                    spans.append((round(a, 3), round(b, 3)))
            i = j
        return spans
    except Exception:
        return []


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
