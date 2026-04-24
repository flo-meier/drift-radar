#!/usr/bin/env python3
"""Build cross_refs.json – aggregates every external-source connector
(GSC, GA4, Ahrefs) into a single payload consumed by the Stack tab.

Each connector returns its own sub-payload with:
    - source: "live" | "live-stub" | "demo"
    - note: one-line message for the UI
    - by_prompt: {prompt_id: {…}}
    - top_priority: [{…}]

This script calls each connector and writes the result to data/ui/cross_refs.json.
"""
import json
from pathlib import Path

from connectors import gsc, ga4

ROOT = Path(__file__).parent
UI = ROOT / "data" / "ui" / "drift_radar.json"
OUT = ROOT / "data" / "ui" / "cross_refs.json"


def main():
    data = json.loads(UI.read_text(encoding="utf-8"))
    prompts = data.get("prompts", [])

    gsc_payload = gsc.fetch(prompts)
    ga4_payload = ga4.fetch(prompts, gsc=gsc_payload)

    payload = {
        "gsc": gsc_payload,
        "ga4": ga4_payload,
        # Ahrefs lands here in wave 8.
    }

    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    size_kb = OUT.stat().st_size / 1024
    sources = {k: v["source"] for k, v in payload.items()}
    print(f"wrote {OUT.relative_to(ROOT.parent)}: sources={sources}, {size_kb:.1f} KB")


if __name__ == "__main__":
    main()
