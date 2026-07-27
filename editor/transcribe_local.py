"""Local transcription with faster-whisper — no external API, no per-key quota.

This is the fallback (and optional replacement) for the ElevenLabs Scribe path in
transcribe.py. It produces the EXACT SAME transcript JSON shape the rest of the
pipeline consumes:

    {"words": [{"type": "word", "text": "...", "start": s, "end": e,
                "speaker_id": "speaker_0"}, ...],
     "text": "...", "language_code": "en", "provider": "faster-whisper"}

so nothing downstream changes. faster-whisper runs on CPU via CTranslate2 (int8) —
no GPU, no PyTorch. It has no diarization, so every word is attributed to
speaker_0 (the pipeline's 3a step already falls back to "all speech" when a
configured speaker id has no words, so a single-speaker transcript is safe).

Model is chosen by WHISPER_MODEL (default "small"); the weights are baked into the
Docker image under WHISPER_MODEL_DIR so there is no runtime download.

Usage:
    python transcribe_local.py <video_path> [--edit-dir DIR] [--language en] [--model small]
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# One loaded model per process, reused across clips in the same job.
_MODEL = None
_MODEL_SIZE: str | None = None


def _get_model(size: str):
    global _MODEL, _MODEL_SIZE
    if _MODEL is None or _MODEL_SIZE != size:
        from faster_whisper import WhisperModel  # imported lazily so the pipeline
        # never pays the ctranslate2 import cost on cached / mock / Scribe runs.
        root = os.environ.get("WHISPER_MODEL_DIR") or None
        _MODEL = WhisperModel(size, device="cpu", compute_type="int8", download_root=root)
        _MODEL_SIZE = size
    return _MODEL


def unload_model() -> None:
    """Drop the loaded model and reclaim its RAM (~1GB for 'small').

    Called after transcription so the model never stays resident through the
    memory-heavy ffmpeg encode stages (compose / normalize), where it would add
    to the exact OOM pressure that SIGKILLs those encodes."""
    global _MODEL, _MODEL_SIZE
    _MODEL = None
    _MODEL_SIZE = None
    import gc
    gc.collect()


def extract_audio(video_path: Path, dest: Path, timeout: int = 900) -> None:
    """16kHz mono PCM — identical to the Scribe path so behaviour matches."""
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path),
             "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dest)],
            check=True, timeout=timeout,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"audio extraction timed out after {timeout // 60} min — the footage "
            f"may be corrupt or an unsupported format.")


def transcribe_local(
    video: Path,
    edit_dir: Path,
    language: str | None = None,
    model_size: str | None = None,
    verbose: bool = True,
) -> Path:
    """Transcribe one video locally. Returns the transcript JSON path.

    Cached: returns immediately if the transcript already exists (so it composes
    with the Scribe path — whichever wrote the file first wins)."""
    transcripts_dir = edit_dir / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    out_path = transcripts_dir / f"{video.stem}.json"
    if out_path.exists():
        if verbose:
            print(f"cached: {out_path.name}")
        return out_path

    size = model_size or os.environ.get("WHISPER_MODEL", "small")
    lang = None if (not language or language == "auto") else language

    t0 = time.time()
    model = _get_model(size)
    with tempfile.TemporaryDirectory() as tmp:
        audio = Path(tmp) / f"{video.stem}.wav"
        extract_audio(video, audio)
        if verbose:
            print(f"  local whisper ({size}) transcribing {video.name}", flush=True)
        segments, info = model.transcribe(
            str(audio), language=lang, word_timestamps=True, beam_size=5)

        words: list[dict] = []
        for seg in segments:                      # generator — this drives the work
            for w in (seg.words or []):
                txt = (w.word or "").strip()
                if not txt:
                    continue
                words.append({
                    "type":       "word",
                    "text":       txt,
                    "start":      round(float(w.start), 3),
                    "end":        round(float(w.end), 3),
                    "speaker_id": "speaker_0",
                })

    payload = {
        "words":         words,
        "text":          " ".join(w["text"] for w in words),
        "language_code": getattr(info, "language", None),
        "provider":      "faster-whisper",
    }
    out_path.write_text(json.dumps(payload, indent=2))
    if verbose:
        dt = time.time() - t0
        print(f"  saved: {out_path.name} — {len(words)} words in {dt:.1f}s "
              f"({getattr(info, 'language', '?')})")
    return out_path


def main() -> None:
    ap = argparse.ArgumentParser(description="Transcribe a video locally with faster-whisper")
    ap.add_argument("video", type=Path)
    ap.add_argument("--edit-dir", type=Path, default=None)
    ap.add_argument("--language", type=str, default=None)
    ap.add_argument("--model", type=str, default=None, help="tiny|base|small|medium|large-v3")
    args = ap.parse_args()

    video = args.video.resolve()
    if not video.exists():
        sys.exit(f"video not found: {video}")
    edit_dir = (args.edit_dir or (video.parent / "edit")).resolve()
    transcribe_local(video=video, edit_dir=edit_dir,
                     language=args.language, model_size=args.model)


if __name__ == "__main__":
    main()
