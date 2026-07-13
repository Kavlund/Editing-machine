#!/usr/bin/env python3
"""
Pipeline test runner — runs one video through the full editing pipeline N times
and produces an HTML report on reliability and output quality.

Each run gets a fresh job directory so it exercises the real source-scan, AI
planning, and compose steps. To keep it fast and cheap, the expensive
normalize + transcribe steps are done ONCE and their results are seeded into
every run's directory (override with --fresh to redo them every time).

Usage:
    python test_runner.py \
        --video /path/to/clip.mov \
        --client 7edfc5cc-3be8-4646-922b-42bcbedec556 \
        --instructions "Cut filler words. Add a hook. Add my name. Subtle zoom." \
        --runs 5

    # Reuse a video already sitting in an uploads/ folder (skips the copy):
    python test_runner.py --video ../uploads/<job>/IMG_1920.MOV --client <id> --runs 3

Output:
    test_runs/<timestamp>/report.html   ← open this
    test_runs/<timestamp>/run_NN/        ← each run's working dir + final.mp4
"""
from __future__ import annotations
import argparse, json, shutil, subprocess, sys, time, uuid, html
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parent
BASE    = BACKEND.parent
sys.path.insert(0, str(BACKEND))

# Load .env exactly like the server does so ELEVENLABS/ANTHROPIC keys are present
try:
    from dotenv import load_dotenv
    load_dotenv(BASE / ".env", override=True)
except ImportError:
    pass

import os
from pipeline import run_pipeline, VIDEO_EXTS

CLIENTS_FILE = BASE / "data" / "clients.json"
TEST_ROOT    = BASE / "test_runs"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _load_client(client_id: str) -> dict:
    clients = json.loads(CLIENTS_FILE.read_text())
    for c in clients:
        if c["id"] == client_id:
            return c
    ids = "\n".join(f"  {c['id']}  {c['name']}" for c in clients)
    raise SystemExit(f"Client '{client_id}' not found. Available:\n{ids}")


def _probe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(out.stdout.strip() or 0.0)
    except Exception:
        return 0.0


def _warm_cache(video: Path, client: dict, elevenlabs_key: str,
                jobs_dir: Path, uploads_dir: Path) -> Path:
    """Run normalize + transcribe once; return the warmed project dir."""
    job_id  = "warmup"
    job_dir = uploads_dir / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
    job_dir.mkdir(parents=True)
    shutil.copy2(video, job_dir / video.name)

    job = _make_job(job_id, client, video.name, elevenlabs_key,
                    instructions="")   # no editing — we only want normalize+transcribe cached
    (jobs_dir / f"{job_id}.json").write_text(json.dumps(job, indent=2))

    print("Warming cache (normalize + transcribe once)...", flush=True)
    run_pipeline(job_id, jobs_dir, uploads_dir, elevenlabs_key)
    print("Cache warmed.\n", flush=True)
    return job_dir


def _make_job(job_id: str, client: dict, video_name: str,
              elevenlabs_key: str, instructions: str) -> dict:
    return {
        "id":                  job_id,
        "client_id":           client["id"],
        "client_name":         client["name"],
        "folder_name":         video_name,
        "notes":               instructions,
        "status":              "uploaded",
        "created_at":          datetime.now().isoformat(),
        "files":               [{"path": video_name, "size": 0}],
        "total_bytes":         0,
        "upload_dir":          "",
        "client_snapshot":     client,
        "elevenlabs_key":      elevenlabs_key,
        "palmier_instructions": instructions,
    }


def _seed_from_cache(warm_dir: Path, run_dir: Path, video_name: str):
    """Copy raw video + cached _v30 clips + transcripts so a run skips normalize/transcribe."""
    run_dir.mkdir(parents=True, exist_ok=True)
    # raw source
    shutil.copy2(warm_dir / video_name, run_dir / video_name)
    # normalized clips (*_v30.mov)
    for f in warm_dir.glob("*_v30.mov"):
        shutil.copy2(f, run_dir / f.name)
    # transcripts
    tsrc = warm_dir / "transcripts"
    if tsrc.exists():
        shutil.copytree(tsrc, run_dir / "transcripts", dirs_exist_ok=True)


# ── Result collection ────────────────────────────────────────────────────────

def _collect(job_id: str, jobs_dir: Path, run_dir: Path, elapsed: float) -> dict:
    job = json.loads((jobs_dir / f"{job_id}.json").read_text())
    status = job.get("status", "unknown")
    log    = job.get("log", [])
    err    = next((e["msg"] for e in reversed(log)
                   if e["msg"].startswith("ERROR")), None)

    final = run_dir / "final.mp4"
    edl_p = run_dir / "edl.json"
    edl   = json.loads(edl_p.read_text()) if edl_p.exists() else {}

    hook_mov = run_dir / "animations" / "hook" / "hook.mov"
    lt_mov   = run_dir / "animations" / "lower_third" / "lower_third.mov"

    # Pull the AI-generated hook text out of the log if present
    hook_text = edl.get("hook_text")
    if not hook_text:
        for e in log:
            if e["msg"].startswith("AI: hook = "):
                hook_text = e["msg"].split("=", 1)[1].strip().strip("'\"")

    return {
        "run":            job_id,
        "passed":         status == "done" and final.exists() and final.stat().st_size > 1_000_000,
        "status":         status,
        "error":          err,
        "elapsed":        elapsed,
        "output_size_mb": round(final.stat().st_size / 1_048_576, 1) if final.exists() else 0.0,
        "output_dur":     round(_probe_duration(final), 1) if final.exists() else 0.0,
        "range_count":    len(edl.get("ranges", [])),
        "raw_seconds":    round(sum(r["end"] - r["start"] for r in edl.get("ranges", [])), 1),
        "hook_text":      hook_text,
        "hook_rendered":  hook_mov.exists(),
        "lt_name":        edl.get("lower_third_name"),
        "lt_rendered":    lt_mov.exists(),
        "zoom":           bool(edl.get("zoom_enabled")),
        "final_path":     str(final) if final.exists() else None,
    }


# ── HTML report ──────────────────────────────────────────────────────────────

def _write_report(results: list, meta: dict, out: Path):
    n       = len(results)
    passed  = sum(1 for r in results if r["passed"])
    rate    = round(100 * passed / n) if n else 0
    durs    = [r["elapsed"] for r in results if r["passed"]]
    sizes   = [r["output_size_mb"] for r in results if r["passed"]]
    avg_dur = f"{sum(durs)/len(durs):.0f}s" if durs else "—"
    avg_sz  = f"{sum(sizes)/len(sizes):.1f} MB" if sizes else "—"

    hook_ok = sum(1 for r in results if r["hook_rendered"])
    lt_ok   = sum(1 for r in results if r["lt_rendered"])
    zoom_ok = sum(1 for r in results if r["zoom"])

    rate_color = "#22c55e" if rate >= 90 else "#eab308" if rate >= 70 else "#ef4444"

    def esc(x): return html.escape(str(x)) if x is not None else "—"

    rows = ""
    for r in results:
        badge = ('<span class="b b-green">PASS</span>' if r["passed"]
                 else '<span class="b b-red">FAIL</span>')
        hook_cell = (f'<span class="chk">✓</span> {esc(r["hook_text"])}'
                     if r["hook_rendered"] else '<span class="x">—</span>')
        lt_cell = (f'<span class="chk">✓</span> {esc(r["lt_name"])}'
                   if r["lt_rendered"] else '<span class="x">—</span>')
        zoom_cell = '<span class="chk">✓</span>' if r["zoom"] else '<span class="x">—</span>'
        err_row = (f'<tr class="err-row"><td colspan="9">⚠ {esc(r["error"])}</td></tr>'
                   if r["error"] else "")
        rows += f"""
        <tr>
          <td class="mono">{esc(r["run"])}</td>
          <td>{badge}</td>
          <td class="mono num">{r["elapsed"]:.0f}s</td>
          <td class="mono num">{r["output_size_mb"]}</td>
          <td class="mono num">{r["output_dur"]}s</td>
          <td class="mono num">{r["range_count"]}</td>
          <td>{hook_cell}</td>
          <td>{lt_cell}</td>
          <td class="ctr">{zoom_cell}</td>
        </tr>{err_row}"""

    # Recommendations
    recs = []
    if rate < 100:
        fails = [r for r in results if not r["passed"]]
        errs  = [r["error"] for r in fails if r["error"]]
        if errs:
            recs.append(f"{len(fails)} run(s) failed. Most recent error: {errs[-1]}")
        else:
            recs.append(f"{len(fails)} run(s) did not produce a valid final.mp4.")
    if hook_ok < n:
        recs.append(f"Hook rendered in only {hook_ok}/{n} runs — check Claude hook generation / instructions.")
    if lt_ok < n:
        recs.append(f"Lower third rendered in only {lt_ok}/{n} runs — check name detection / client profile.")
    if durs and max(durs) > 2 * (sum(durs)/len(durs)):
        recs.append("Large variance in run time — one run was much slower, possible transcription/API stall.")
    if not recs:
        recs.append("All runs passed with all features rendered. Pipeline is stable for this input.")

    rec_html = "".join(f"<li>{esc(x)}</li>" for x in recs)

    report = f"""<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pipeline Test Report</title>
<style>
:root{{--bg:#0b0b0b;--surface:#141414;--s2:#1e1e1e;--border:rgba(255,255,255,.08);
--text:#e2e0db;--muted:#6e6b66;--accent:#f97316;--green:#22c55e;--yellow:#eab308;--red:#ef4444;}}
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,system-ui,sans-serif;
font-size:14px;line-height:1.6;padding:40px 24px 80px;}}
.wrap{{max-width:1040px;margin:0 auto;}}
.mono{{font-family:ui-monospace,"SF Mono",Consolas,monospace;}}
.num{{text-align:right;font-variant-numeric:tabular-nums;}}
.ctr{{text-align:center;}}
header{{display:flex;align-items:baseline;justify-content:space-between;margin-bottom:8px;flex-wrap:wrap;gap:8px;}}
h1{{font-size:22px;letter-spacing:-.4px;}}
.sub{{color:var(--muted);font-size:13px;margin-bottom:32px;}}
.sub .mono{{color:var(--accent);}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:32px;}}
.stat{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px 18px;}}
.stat .k{{font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin-bottom:6px;}}
.stat .v{{font-size:26px;font-weight:700;letter-spacing:-.5px;font-variant-numeric:tabular-nums;}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:4px;margin-bottom:24px;overflow-x:auto;}}
table{{width:100%;border-collapse:collapse;min-width:760px;}}
th{{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--muted);
padding:12px 10px;border-bottom:1px solid var(--border);white-space:nowrap;}}
th.num{{text-align:right;}} th.ctr{{text-align:center;}}
td{{padding:11px 10px;border-bottom:1px solid var(--border);font-size:13px;vertical-align:top;}}
tr:last-child td{{border-bottom:none;}}
.b{{display:inline-block;padding:2px 9px;border-radius:4px;font-size:11px;font-weight:700;letter-spacing:.03em;}}
.b-green{{background:rgba(34,197,94,.14);color:var(--green);}}
.b-red{{background:rgba(239,68,68,.14);color:var(--red);}}
.chk{{color:var(--green);font-weight:700;}} .x{{color:var(--muted);}}
.err-row td{{background:rgba(239,68,68,.06);color:var(--red);font-size:12px;padding:8px 12px;
font-family:ui-monospace,monospace;}}
h2{{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:0 0 12px 2px;}}
.recs{{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:18px 22px 18px 40px;}}
.recs li{{margin-bottom:8px;font-size:13.5px;}} .recs li:last-child{{margin-bottom:0;}}
.foot{{color:var(--muted);font-size:12px;margin-top:32px;border-top:1px solid var(--border);padding-top:16px;}}
</style></head><body><div class="wrap">
<header>
  <h1>Pipeline Test Report</h1>
  <div class="mono" style="color:var(--muted);font-size:12px">{esc(meta['timestamp'])}</div>
</header>
<div class="sub">
  <span class="mono">{esc(meta['video'])}</span> · client <span class="mono">{esc(meta['client'])}</span> · {n} run(s)<br>
  instructions: "{esc(meta['instructions'])}"
</div>

<div class="stats">
  <div class="stat"><div class="k">Pass rate</div><div class="v" style="color:{rate_color}">{rate}%</div></div>
  <div class="stat"><div class="k">Passed</div><div class="v">{passed}/{n}</div></div>
  <div class="stat"><div class="k">Avg time</div><div class="v">{avg_dur}</div></div>
  <div class="stat"><div class="k">Avg size</div><div class="v">{avg_sz}</div></div>
  <div class="stat"><div class="k">Hook</div><div class="v">{hook_ok}/{n}</div></div>
  <div class="stat"><div class="k">Name</div><div class="v">{lt_ok}/{n}</div></div>
  <div class="stat"><div class="k">Zoom</div><div class="v">{zoom_ok}/{n}</div></div>
</div>

<h2>Per-run results</h2>
<div class="card"><table>
<thead><tr>
  <th>Run</th><th>Result</th><th class="num">Time</th><th class="num">Size MB</th>
  <th class="num">Out s</th><th class="num">Cuts</th><th>Hook</th><th>Name</th><th class="ctr">Zoom</th>
</tr></thead>
<tbody>{rows}</tbody>
</table></div>

<h2>Findings &amp; recommendations</h2>
<ul class="recs">{rec_html}</ul>

<div class="foot">
  Final videos are in each <span class="mono">run_NN/final.mp4</span> next to this report.
  Regenerate with <span class="mono">python test_runner.py</span>.
</div>
</div></body></html>"""
    out.write_text(report)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="Run a video through the pipeline N times and report.")
    ap.add_argument("--video", required=True, help="Path to the test video")
    ap.add_argument("--client", required=True, help="Client ID (from data/clients.json)")
    ap.add_argument("--instructions", default="Cut the filler words. Add a hook at the top. Add my name at the bottom. Keep the zoom subtle.",
                    help="Editing instructions passed to the pipeline")
    ap.add_argument("--runs", type=int, default=3, help="Number of runs")
    ap.add_argument("--fresh", action="store_true",
                    help="Re-normalize and re-transcribe every run (slower, tests full pipeline)")
    args = ap.parse_args()

    video = Path(args.video).expanduser().resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")
    if video.suffix.lower() not in VIDEO_EXTS:
        raise SystemExit(f"Not a video file: {video.name}")

    client = _load_client(args.client)
    elevenlabs_key = os.environ.get("ELEVENLABS_API_KEY", "")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("WARNING: ANTHROPIC_API_KEY not set — hook generation will be skipped.\n")

    stamp   = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_root = TEST_ROOT / stamp
    run_root.mkdir(parents=True, exist_ok=True)

    # Isolated jobs/uploads dirs so the test never touches real jobs
    jobs_dir    = run_root / "_jobs"
    uploads_dir = run_root / "_uploads"
    jobs_dir.mkdir(); uploads_dir.mkdir()

    warm_dir = None
    if not args.fresh:
        # Persistent cache keyed by video name + client — survives across test sessions
        # so we only normalize + transcribe once ever, not every run.
        cache_key   = f"{video.stem}_{client['id'][:8]}"
        persist_dir = TEST_ROOT / "_cache" / cache_key
        cached_norm = list(persist_dir.glob("*_v30.mov")) if persist_dir.exists() else []
        cached_trans = (persist_dir / "transcripts").exists() if persist_dir.exists() else False

        if cached_norm and cached_trans:
            print(f"Reusing persistent cache: {persist_dir}\n")
            warm_dir = persist_dir
        else:
            warm_dir = _warm_cache(video, client, elevenlabs_key, jobs_dir, uploads_dir)
            # Persist the warmed artifacts for next time
            persist_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(warm_dir / video.name, persist_dir / video.name)
            for f in warm_dir.glob("*_v30.mov"):
                shutil.copy2(f, persist_dir / f.name)
            tsrc = warm_dir / "transcripts"
            if tsrc.exists():
                shutil.copytree(tsrc, persist_dir / "transcripts", dirs_exist_ok=True)
            print(f"Cached artifacts for reuse: {persist_dir}\n")

    results = []
    for i in range(1, args.runs + 1):
        job_id  = f"run_{i:02d}"
        run_dir = uploads_dir / job_id
        print(f"── Run {i}/{args.runs} ──", flush=True)

        if warm_dir is not None:
            _seed_from_cache(warm_dir, run_dir, video.name)
        else:
            run_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(video, run_dir / video.name)

        job = _make_job(job_id, client, video.name, elevenlabs_key, args.instructions)
        (jobs_dir / f"{job_id}.json").write_text(json.dumps(job, indent=2))

        t0 = time.time()
        try:
            run_pipeline(job_id, jobs_dir, uploads_dir, elevenlabs_key)
        except Exception as e:
            print(f"  run raised: {e}", flush=True)
        elapsed = time.time() - t0

        res = _collect(job_id, jobs_dir, run_dir, elapsed)
        results.append(res)
        mark = "✓ PASS" if res["passed"] else "✗ FAIL"
        print(f"  {mark}  {elapsed:.0f}s  {res['output_size_mb']}MB  "
              f"hook={'y' if res['hook_rendered'] else 'n'} "
              f"name={'y' if res['lt_rendered'] else 'n'} "
              f"zoom={'y' if res['zoom'] else 'n'}"
              + (f"  ERR: {res['error']}" if res['error'] else ""), flush=True)

        # copy final.mp4 up next to the report for easy access
        if res["final_path"]:
            shutil.copy2(res["final_path"], run_root / f"{job_id}_final.mp4")

    meta = {
        "timestamp":    stamp,
        "video":        video.name,
        "client":       client["name"],
        "instructions": args.instructions,
    }
    report = run_root / "report.html"
    _write_report(results, meta, report)

    passed = sum(1 for r in results if r["passed"])
    print(f"\n{'='*50}")
    print(f"  {passed}/{len(results)} passed ({round(100*passed/len(results))}%)")
    print(f"  Report: {report}")
    print(f"{'='*50}")
    # auto-open on macOS
    subprocess.run(["open", str(report)], check=False)


if __name__ == "__main__":
    main()
