"""Render a motion-graphics template with Remotion -> a transparent overlay clip.

Code-based templates live in <repo>/remotion. The LLM only supplies text/props;
the animation is fixed, version-controlled code that cannot break the way per-video
PIL drawing can. Output is ProRes 4444 with alpha (yuva444p10le), the SAME codec
family as the PIL overlays, so compose.py composites it unchanged.

Requires Node + the remotion project's node_modules (installed into the image).
Guarded by REMOTION_GRAPHICS=1 upstream; callers fall back to PIL if this raises.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

REMOTION_DIR = Path(
    os.environ.get("REMOTION_DIR")
    or (Path(__file__).resolve().parent.parent / "remotion")
)
_ENTRY = "src/index.ts"


def available() -> bool:
    """True only if the node project is present AND installed, so a caller can
    cheaply decide to use Remotion vs fall back to PIL."""
    return (REMOTION_DIR / "node_modules").is_dir() and (REMOTION_DIR / _ENTRY).exists()


def render_template(template_id: str, out_path: Path, props: dict,
                    timeout: int = 600) -> Path:
    # Resolve to absolute BEFORE running: the command runs with cwd=REMOTION_DIR,
    # so a relative out_path would be written nested under the remotion project.
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # Bound Chromium memory/CPU — Remotion rendering is heavy and must stay within
    # the same memory budget that the render serialization protects.
    conc = os.environ.get("REMOTION_CONCURRENCY", "2")
    cmd = [
        "npx", "remotion", "render", _ENTRY, template_id, str(out_path),
        "--codec=prores", "--prores-profile=4444",
        "--pixel-format=yuva444p10le", "--image-format=png",
        f"--concurrency={conc}",
        f"--props={json.dumps(props, ensure_ascii=False)}",
    ]
    subprocess.run(cmd, cwd=str(REMOTION_DIR), check=True, timeout=timeout)
    return out_path


def render_hook(text: str, out_path: Path, width: int, height: int,
                duration_sec: float, fps: int = 30, accent: str = "#ffffff") -> Path:
    frames = max(30, int(round(duration_sec * fps)))
    return render_template("Hook", out_path, {
        "text": text,
        "durationInFrames": frames,
        "width": int(width),
        "height": int(height),
        "accent": accent,
    })
