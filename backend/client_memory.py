"""Per-creator style memory.

Every tweak someone makes to a single video is recorded here. When the SAME kind
of tweak shows up more than once for that creator, it becomes a *suggestion*:
"Kasper keeps moving the captions up — make it his default?". Nothing changes on
its own; the operator accepts or ignores it.

Memory is strictly per client. One creator's habits never leak into another's.

Stored at DATA_ROOT/client_memory/{client_id}.json:
  {
    "observations": [ {at, job_id, job_name, category, key, value, prev} ],
    "suggestions":  [ {id, category, key, value, label, count, first_seen,
                       last_seen, status: pending|accepted|ignored} ],
    "accepted":     [ {id, category, key, value, label, at} ]
  }
"""

import json, uuid
from datetime import datetime, timezone
from pathlib import Path

# How many times the same tweak must appear before we suggest making it default.
PROMOTE_AFTER = 2

# Which per-video settings we learn, and how close two values must be to count
# as "the same tweak". None = must match exactly (colours, styles, modes).
_TRACKED = {
    # caption look
    "caption_y":          ("caption", 80,   "Caption position"),
    "caption_font_size":  ("caption", 8,    "Caption size"),
    "caption_max_width":  ("caption", 80,   "Caption line width"),
    "caption_color":      ("caption", None, "Caption colour"),
    "highlight_color":    ("caption", None, "Word-by-word highlight colour"),
    # colour grade
    "grade":              ("grade",   None, "Colour grade"),
    # b-roll + photo habits
    "broll_count":        ("broll",   None, "B-roll amount"),
    "broll_style":        ("broll",   None, "Photo style"),
    # zoom habits
    "zoom_strength":      ("zoom",    0.03, "Zoom strength"),
    "zoom_count":         ("zoom",    1,    "Zooms per video"),
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _mem_dir(data_root: Path) -> Path:
    d = Path(data_root) / "client_memory"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(data_root: Path, client_id: str) -> Path:
    safe = "".join(c for c in str(client_id) if c.isalnum() or c in "-_")
    return _mem_dir(data_root) / f"{safe}.json"


def load(data_root: Path, client_id: str) -> dict:
    p = _path(data_root, client_id)
    if p.exists():
        try:
            d = json.loads(p.read_text())
        except Exception:
            d = {}
    else:
        d = {}
    d.setdefault("observations", [])
    d.setdefault("suggestions", [])
    d.setdefault("accepted", [])
    return d


def save(data_root: Path, client_id: str, mem: dict) -> None:
    # Keep the log from growing without bound; suggestions/accepted are what matter.
    mem["observations"] = mem.get("observations", [])[-300:]
    _path(data_root, client_id).write_text(json.dumps(mem, indent=2))


def _same_value(key: str, a, b) -> bool:
    """Two tweaks count as the same preference if they land in the same place."""
    tol = _TRACKED.get(key, (None, None, None))[1]
    if tol is None:
        return str(a).strip().lower() == str(b).strip().lower()
    try:
        return abs(float(a) - float(b)) <= float(tol)
    except (TypeError, ValueError):
        return str(a) == str(b)


def _describe(key: str, value) -> str:
    label = _TRACKED.get(key, (None, None, key))[2]
    if key == "caption_y":
        return f"{label}: move to y={value}"
    if key == "broll_style":
        return f"{label}: {'photos always pop up as cards' if str(value) == 'cards' else 'AI decides per photo'}"
    if key == "grade":
        return f"{label}: adopt the graded look from this video"
    return f"{label}: {value}"


def record(data_root: Path, client_id: str, changes: dict,
           job_id: str = "", job_name: str = "", client_defaults: dict | None = None) -> list:
    """Log per-video tweaks for this creator and return any NEW suggestions raised.

    changes: {setting_key: new_value} straight from a chat edit.
    client_defaults: the client's current defaults, so re-applying a value they
    already have as default is not treated as a fresh preference.
    """
    if not client_id or not changes:
        return []
    defaults = client_defaults or {}
    mem = load(data_root, client_id)
    raised = []

    for key, value in changes.items():
        if key not in _TRACKED or value is None:
            continue
        # Already their default? Then this is not a new preference.
        if key in defaults and _same_value(key, defaults[key], value):
            continue
        category = _TRACKED[key][0]
        mem["observations"].append({
            "at": _now(), "job_id": job_id, "job_name": job_name,
            "category": category, "key": key, "value": value,
            "prev": defaults.get(key),
        })

        # Already accepted this exact preference? Nothing to raise.
        if any(a["key"] == key and _same_value(key, a["value"], value)
               for a in mem["accepted"]):
            continue

        # Count matching observations (including this one) to decide on promotion.
        hits = [o for o in mem["observations"]
                if o["key"] == key and _same_value(key, o["value"], value)]

        existing = next((s for s in mem["suggestions"]
                         if s["key"] == key and _same_value(key, s["value"], value)
                         and s["status"] == "pending"), None)
        if existing:
            existing["count"] = len(hits)
            existing["value"] = value          # track the latest value they chose
            existing["last_seen"] = _now()
            existing["label"] = _describe(key, value)
        elif len(hits) >= PROMOTE_AFTER:
            # Don't re-raise something the operator already dismissed.
            if any(s["key"] == key and _same_value(key, s["value"], value)
                   and s["status"] == "ignored" for s in mem["suggestions"]):
                continue
            sugg = {
                "id": uuid.uuid4().hex[:12],
                "category": category, "key": key, "value": value,
                "label": _describe(key, value),
                "count": len(hits), "first_seen": hits[0]["at"], "last_seen": _now(),
                "status": "pending",
            }
            mem["suggestions"].append(sugg)
            raised.append(sugg)

    save(data_root, client_id, mem)
    return raised


def pending(data_root: Path, client_id: str) -> list:
    return [s for s in load(data_root, client_id)["suggestions"] if s["status"] == "pending"]


def accept(data_root: Path, client_id: str, suggestion_id: str) -> dict | None:
    """Mark a suggestion accepted. The caller writes the value into the client."""
    mem = load(data_root, client_id)
    for s in mem["suggestions"]:
        if s["id"] == suggestion_id and s["status"] == "pending":
            s["status"] = "accepted"
            # Replace any earlier accepted preference for the same setting.
            mem["accepted"] = [a for a in mem["accepted"] if a["key"] != s["key"]]
            mem["accepted"].append({
                "id": s["id"], "category": s["category"], "key": s["key"],
                "value": s["value"], "label": s["label"], "at": _now(),
            })
            save(data_root, client_id, mem)
            return s
    return None


def ignore(data_root: Path, client_id: str, suggestion_id: str) -> bool:
    mem = load(data_root, client_id)
    for s in mem["suggestions"]:
        if s["id"] == suggestion_id and s["status"] == "pending":
            s["status"] = "ignored"
            save(data_root, client_id, mem)
            return True
    return False


def forget(data_root: Path, client_id: str, key: str) -> bool:
    """Drop a learned preference so the creator's style can move on."""
    mem = load(data_root, client_id)
    before = len(mem["accepted"])
    mem["accepted"] = [a for a in mem["accepted"] if a["key"] != key]
    mem["suggestions"] = [s for s in mem["suggestions"] if s["key"] != key]
    mem["observations"] = [o for o in mem["observations"] if o["key"] != key]
    save(data_root, client_id, mem)
    return len(mem["accepted"]) != before


def summary(data_root: Path, client_id: str) -> str:
    """Plain-language note about this creator, injected into the AI prompts so the
    assistant knows the person it is editing for. Empty when nothing is learned."""
    mem = load(data_root, client_id)
    if not mem["accepted"]:
        return ""
    lines = [f"  - {a['label']}" for a in mem["accepted"]]
    return ("WHAT YOU HAVE LEARNED ABOUT THIS CREATOR (from edits they kept making — "
            "already applied as their defaults, respect them unless asked otherwise):\n"
            + "\n".join(lines))
