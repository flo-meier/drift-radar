#!/usr/bin/env python3
"""Copy pipeline outputs into the Astro src/data/ folder so the site builds.

Run this after `run.py` (and before `astro build`).
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).parent
APP_DATA = ROOT.parent / "src" / "data"
APP_DATA.mkdir(parents=True, exist_ok=True)

FILES = [
    (ROOT / "data" / "ui" / "drift_radar.json", APP_DATA / "drift_radar.json"),
    (ROOT / "data" / "ui" / "cross_refs.json", APP_DATA / "cross_refs.json"),
    (ROOT / "data" / "raw" / "peec_actions.json", APP_DATA / "peec_actions.json"),
    (ROOT / "data" / "raw" / "trend_by_date.json", APP_DATA / "trend_by_date.json"),
]

for src, dst in FILES:
    if not src.exists():
        print(f"skip: {src.relative_to(ROOT.parent)} not found")
        continue
    shutil.copy2(src, dst)
    print(f"synced {src.relative_to(ROOT.parent)} -> {dst.relative_to(ROOT.parent)}")
