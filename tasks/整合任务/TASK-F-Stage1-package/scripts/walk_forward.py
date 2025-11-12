#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Walk-forward driver for Stage-1 optimization.
For each fold, call param_search.py with the same group/search-space but different windows.
"""
import argparse, subprocess, sys, json, time
from pathlib import Path
from datetime import datetime, timedelta, timezone

def dt(s): return datetime.fromisoformat(s.replace("Z","+00:00"))

def fmt(dt): return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--group-config", required=True)
    ap.add_argument("--search-space", required=True)
    ap.add_argument("--mode", choices=["A","B"], default="B")
    ap.add_argument("--signals-src")
    ap.add_argument("--features-dir")
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--symbols", required=True)
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--train-days", type=int, default=30)
    ap.add_argument("--val-days", type=int, default=7)
    ap.add_argument("--test-days", type=int, default=7)
    ap.add_argument("--step-days", type=int, default=7)
    ap.add_argument("--tz", default="Asia/Tokyo"); ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-workers", type=int, default=6)
    ap.add_argument("--max-trials", type=int, default=200)
    args = ap.parse_args()

    start = dt(args.start); end = dt(args.end)
    t = start
    fold = 0
    while t + timedelta(days=args.train_days + args.val_days + args.test_days) <= end:
        fold += 1
        tr0 = t; tr1 = tr0 + timedelta(days=args.train_days)
        va0 = tr1; va1 = va0 + timedelta(days=args.val_days)
        te0 = va1; te1 = te0 + timedelta(days=args.test_days)
        fold_out = Path(args.out_root) / f"wf_fold_{fold:02d}"
        fold_out.mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable, "scripts/param_search.py",
            "--group-config", args.group_config,
            "--search-space", args.search_space,
            "--mode", args.mode,
            "--out-root", str(fold_out),
            "--symbols", args.symbols,
            "--start", fmt(tr0), "--end", fmt(tr1),
            "--tz", args.tz, "--seed", str(args.seed),
            "--max-workers", str(args.max_workers),
            "--max-trials", str(args.max_trials),
        ]
        if args.mode=="B":
            cmd += ["--signals-src", args.signals_src]
        else:
            cmd += ["--features-dir", args.features_dir]

        print(f"[Fold {fold}] Train {fmt(tr0)} ~ {fmt(tr1)}")
        proc = subprocess.run(cmd)
        if proc.returncode != 0:
            print(f"[Fold {fold}] param_search failed", file=sys.stderr); sys.exit(proc.returncode)

        t = t + timedelta(days=args.step_days)

    print("Walk-forward finished. See outputs in", args.out_root)

if __name__ == "__main__":
    main()
