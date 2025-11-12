#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Minimal parameter search driver for OFI/CVD Stage-1 (Mode A/B compatible).
- Reads a group baseline YAML and a search-space JSON (dot-key -> values list).
- For each trial: merges overrides into the baseline, writes a temp YAML, runs backtest,
  then evaluates pnl_daily.jsonl + trades.jsonl and records a score.
- Parallel execution via multiprocessing.
"""
import argparse, json, os, sys, subprocess, tempfile, shutil, itertools, math, time
from pathlib import Path
from multiprocessing import Pool, cpu_count

try:
    import yaml
except Exception:
    print("Please install pyyaml: pip install pyyaml", file=sys.stderr); sys.exit(1)

PY = sys.executable

def set_by_dots(d: dict, dotted: str, value):
    """Set nested dict by dot-key, creating nodes as needed."""
    cur = d
    parts = dotted.split(".")
    for p in parts[:-1]:
        if p not in cur or not isinstance(cur[p], dict):
            cur[p] = {}
        cur = cur[p]
    cur[parts[-1]] = value

def deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k,v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out

def load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}

def save_yaml(path: Path, data: dict):
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")

def grid_from_json(space_json: dict):
    params = space_json.get("params", {})
    keys = list(params.keys())
    values = [params[k] for k in keys]
    for combo in itertools.product(*values):
        yield dict(zip(keys, combo))

def eval_score(out_dir: Path):
    # Load pnl_daily & trades; compute score
    pnl_file = out_dir / "pnl_daily.jsonl"
    trades_file = out_dir / "trades.jsonl"
    if not pnl_file.exists() or not trades_file.exists():
        return None
    pnl = []
    with pnl_file.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                pnl.append(json.loads(ln))
    trades = []
    with trades_file.open("r", encoding="utf-8") as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                trades.append(json.loads(ln))
    pnl_net = sum(x.get("pnl",0.0)+x.get("fees",0.0) for x in pnl)
    # equity & drawdown (daily)
    eq = 0.0; peak = 0.0; mdd = 0.0
    rets = []
    for x in pnl:
        r = x.get("pnl",0.0)+x.get("fees",0.0)
        rets.append(r); eq += r; peak = max(peak, eq); mdd = min(mdd, eq-peak)
    mdd = abs(mdd)
    if rets:
        mu = sum(rets)/len(rets)
        vol = (sum((r-mu)**2 for r in rets)/len(rets))**0.5
    else:
        mu = 0.0; vol = 0.0
    sharpe = (mu/(vol+1e-8)) if vol>0 else 0.0
    maker_ratio = (sum(1 for t in trades if t.get("maker")) / max(1,len(trades)))
    # freq per day ~ trades.jsonl count / len(pnl_daily)
    freq = (len(trades) / max(1, len(pnl)))
    # penalties
    pen_freq = 0.0
    if freq < 200: pen_freq += (200 - freq)*0.001
    if freq > 1500: pen_freq += (freq - 1500)*0.001
    pen_maker = 0.0
    if maker_ratio < 0.55: pen_maker += (0.55 - maker_ratio)*10
    score = pnl_net - 0.5*mdd - 0.1*abs(sum(x.get("fees",0.0) for x in pnl)) \
            - 0.05*pen_freq - 0.05*pen_maker + 0.05*sharpe
    return {
        "score": round(score,6),
        "pnl_net": round(pnl_net,6),
        "mdd": round(mdd,6),
        "sharpe": round(sharpe,4),
        "freq": round(freq,2),
        "maker": round(maker_ratio,3),
        "trades": len(trades),
        "days": len(pnl),
    }

def run_trial(args):
    (trial_id, base_cfg_path, overrides, cli, out_root) = args
    base = load_yaml(Path(base_cfg_path))
    # apply dot-key overrides
    merged = dict(base)
    for k,v in overrides.items():
        set_by_dots(merged, k, v)
    # constraint: w_ofi + w_cvd == 1.0 if both present
    try:
        w_ofi = merged.get("components",{}).get("fusion",{}).get("w_ofi")
        w_cvd = merged.get("components",{}).get("fusion",{}).get("w_cvd")
        if (w_ofi is not None) and (w_cvd is not None):
            if abs((w_ofi + w_cvd) - 1.0) > 1e-9:
                return (trial_id, overrides, {"error":"w_ofi+w_cvd!=1.0"})
    except Exception:
        pass
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"trial_{trial_id}_"))
    try:
        cfg_path = tmp_dir / "trial_config.yaml"
        save_yaml(cfg_path, merged)
        run_id = f"trial_{trial_id:05d}"
        out_dir = Path(out_root) / run_id / "output"
        out_dir.parent.mkdir(parents=True, exist_ok=True)
        # backtest command
        cmd = [sys.executable, "-m", "backtest.app",
               "--mode", cli["mode"],
               "--out-dir", str(out_dir),
               "--symbols", cli["symbols"],
               "--start", cli["start"], "--end", cli["end"],
               "--tz", cli.get("tz","Asia/Tokyo"),
               "--seed", str(cli.get("seed",42)),
               "--config", str(cfg_path)]
        if cli["mode"] == "B":
            cmd += ["--signals-src", cli["signals_src"]]
        else:
            cmd += ["--features-dir", cli["features_dir"]]
        if cli.get("emit_sqlite", False):
            cmd += ["--emit-sqlite"]
        # run
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            return (run_id, overrides, {"error":"backtest_failed", "stderr":proc.stderr[-4000:]})
        # evaluate
        score = eval_score(out_dir)
        if score is None:
            return (run_id, overrides, {"error":"missing_outputs"})
        return (run_id, overrides, score)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group-config", required=True, help="Baseline YAML for this group")
    ap.add_argument("--search-space", required=True, help="JSON file defining dot-key search params")
    ap.add_argument("--mode", choices=["A","B"], default="B")
    ap.add_argument("--signals-src", help="sqlite:// or jsonl:// (Mode=B)")
    ap.add_argument("--features-dir", help="features root (Mode=A)")
    ap.add_argument("--out-root", required=True, help="where to store trial outputs")
    ap.add_argument("--symbols", required=True, help="comma separated symbols")
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--tz", default="Asia/Tokyo"); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-workers", type=int, default=max(1, cpu_count()//2))
    ap.add_argument("--max-trials", type=int, default=200)
    ap.add_argument("--emit-sqlite", action="store_true")
    args = ap.parse_args()

    out_root = Path(args.out_root); out_root.mkdir(parents=True, exist_ok=True)
    space = json.loads(Path(args.search_space).read_text(encoding="utf-8"))
    combos = list(grid_from_json(space))
    if args.max_trials and len(combos) > args.max_trials:
        combos = combos[:args.max_trials]

    cli = {
        "mode": args.mode,
        "signals_src": args.signals_src or "",
        "features_dir": args.features_dir or "",
        "symbols": args.symbols,
        "start": args.start, "end": args.end,
        "tz": args.tz, "seed": args.seed,
        "emit_sqlite": bool(args.emit_sqlite),
    }

    work = [(i+1, args.group_config, combos[i], cli, str(out_root)) for i in range(len(combos))]
    with Pool(processes=max(1,args.max_workers)) as pool:
        results = pool.map(run_trial, work)

    # Save leaderboard
    rows = []
    for run_id, overrides, metrics in results:
        row = {"run_id": run_id, **overrides, **metrics}
        rows.append(row)
    rows_sorted = sorted(rows, key=lambda r: (r.get("score",-1e9), r.get("pnl_net",-1e9)), reverse=True)

    import csv
    csv_path = out_root / "trial_results.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=sorted({k for r in rows_sorted for k in r.keys()}))
        writer.writeheader()
        for r in rows_sorted:
            writer.writerow(r)
    json_path = out_root / "trial_results.json"
    json_path.write_text(json.dumps(rows_sorted, ensure_ascii=False, indent=2), encoding="utf-8")

    # Manifest
    manifest = {
        "group_config": str(args.group_config),
        "search_space": str(args.search_space),
        "cli": cli, "max_workers": args.max_workers, "max_trials": args.max_trials,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S")
    }
    (out_root / "trial_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Done. Results at {out_root}")

if __name__ == "__main__":
    main()
