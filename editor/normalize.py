#!/usr/bin/env python3
"""Normalise a raw clip to a true-CFR 30fps, 1080x1920 (vertical), PCM-audio
intermediate that the rest of the pipeline cuts from.

WHY: phone footage is often ~29.97/59.94fps (not true 30) and stored with a
rotation flag. Cutting directly + forcing -r 30 makes each segment's video
frame-count != audio sample-count, and the error accumulates into progressive
lip-sync drift across cuts. Normalising once up front (true CFR 30 + PCM) makes
every later cut frame- and sample-exact, so there is no drift.

Usage:
    python normalize.py <input.mov> <output_v30.mov>
    python normalize.py <input.mov> <output_v30.mov> --height 1920
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path


def normalize(src: Path, dst: Path, height: int = 1920, crf: int = 18,
              timeout: int = 1800, width: int | None = None) -> None:
    # fps=30 -> true CFR;  setsar=1 -> square pixels.
    # ffmpeg auto-applies the rotation matrix before filters, so portrait phone
    # clips come out portrait. Audio -> PCM 48k so cuts are sample-exact.
    # timeout: a corrupt/malformed upload must never hang the pipeline forever.
    #
    # WIDTH MATTERS: with only a height, `scale=-2:1920` blows a 16:9 clip up to
    # 3413x1920 and everything downstream then squashes it back into 9:16. When
    # the caller knows the target frame, fit INSIDE it and pad — never crop, so
    # no part of the picture is ever thrown away.
    if width:
        vf = (f"fps=30,scale={width}:{height}:force_original_aspect_ratio=decrease,"
              f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1")
    else:
        vf = f"fps=30,scale=-2:{height},setsar=1"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-i", str(src),
             "-vf", vf, "-fps_mode", "cfr",
             "-c:v", "libx264", "-crf", str(crf), "-preset", "fast",
             "-c:a", "pcm_s16le", "-ar", "48000", str(dst)],
            check=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"normalize timed out after {timeout // 60} min — the footage may be "
            f"corrupt or an unsupported format. Try re-exporting the clip.")
    print(f"normalized -> {dst}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("output", type=Path)
    ap.add_argument("--height", type=int, default=1920)
    ap.add_argument("--crf", type=int, default=18)
    a = ap.parse_args()
    if not a.input.exists():
        sys.exit(f"no such file: {a.input}")
    normalize(a.input, a.output, a.height, a.crf)


if __name__ == "__main__":
    main()
