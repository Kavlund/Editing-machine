#!/usr/bin/env python3
"""Two-pass EBU R128 loudness normalisation (self-contained, ffmpeg only).

Pass 1 measures the clip's loudness; pass 2 normalises to the target with the
measured values fed back in (linear=true) so the result is broadcast-consistent.
"""
from __future__ import annotations
import json, subprocess
from pathlib import Path

# Target loudness. -14 LUFS / -1 dBTP is the common social/streaming target.
LOUDNORM_I   = -14.0
LOUDNORM_TP  = -1.0
LOUDNORM_LRA = 11.0


def measure_loudness(video_path: Path):
    """Run ffmpeg loudnorm pass 1 and parse the JSON measurement (or None)."""
    f = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}:print_format=json"
    proc = subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(video_path),
         "-af", f, "-vn", "-f", "null", "-"],
        capture_output=True, text=True)
    stderr = proc.stderr
    start, end = stderr.rfind("{"), stderr.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(stderr[start:end + 1])
    except json.JSONDecodeError:
        return None
    needed = {"input_i", "input_tp", "input_lra", "input_thresh", "target_offset"}
    return data if needed.issubset(data) else None


def apply_loudnorm_two_pass(input_path: Path, output_path: Path, preview: bool = False) -> bool:
    """Normalise input_path -> output_path. Returns True on success."""
    input_path, output_path = Path(input_path), Path(output_path)
    if not preview:
        print(f"  loudnorm pass 1: measuring {input_path.name}")
        m = measure_loudness(input_path)
        if m is None:
            print("  measurement failed -> 1-pass fallback")
            preview = True
        else:
            print(f"    measured: I={m['input_i']} LUFS  TP={m['input_tp']}  LRA={m['input_lra']}")
            f = (f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
                 f":measured_I={m['input_i']}:measured_TP={m['input_tp']}"
                 f":measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}"
                 f":offset={m['target_offset']}:linear=true")
            print(f"  loudnorm pass 2: normalizing -> {output_path.name}")
    if preview:
        f = f"loudnorm=I={LOUDNORM_I}:TP={LOUDNORM_TP}:LRA={LOUDNORM_LRA}"
        print(f"  loudnorm (1-pass) -> {output_path.name}")
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-nostats", "-i", str(input_path),
         "-c:v", "copy", "-af", f, "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
         "-movflags", "+faststart", str(output_path)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    return True
