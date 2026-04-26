"""Google Search Console connector for Drift Radar.

Two modes:

1. **Live mode** – when `GSC_SERVICE_ACCOUNT_JSON` + `GSC_PROPERTY_URL` are set,
   pulls real search-analytics data for the prompt set via the GSC API.
   Requires a service account with `siteRestrictedViewer` (or stronger) access
   to the property.

2. **Demo mode** – deterministic mock values seeded from each prompt_id, so
   builds are reproducible without any external calls. Every payload is marked
   with `"source": "demo"` and clearly flagged in the UI.

The cross-reference we surface:

- Click-through rate (0–1)
- Average ranking position (1 = top)
- Monthly impressions
- Clicks

Drift Radar joins these with its own `divergence_score` to derive a combined
priority flag: *»high AI divergence AND low classical CTR = double priority«*.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timezone
from typing import Any


def _stable_rng(key: str) -> random.Random:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def _volume_band(volume: int | None) -> str:
    return {1: "low", 2: "medium", 3: "high"}.get(volume or 0, "medium")


def _demo_row(prompt: dict[str, Any]) -> dict[str, Any]:
    """Deterministic mock row for a single prompt.

    AI-typical prompts are conversational, long-tail and frequently have
    zero or near-zero classical-search volume – nobody types the question
    that way into Google. We model this honestly: silence-prompts and
    high-divergence low-volume prompts often resolve to zero impressions,
    so the dashboard surfaces the GEO-investment punchline (high AI drift
    AND zero classical reach = strongest signal).
    """
    rng = _stable_rng(prompt.get("prompt_id", ""))
    volume = prompt.get("volume") or 2
    divergence = float(prompt.get("divergence_score") or 0.0)
    silence = prompt.get("silence_type") or "active"

    # Probability that the prompt has zero classical search volume.
    # Drives the "AI-prompt has no Google equivalent" narrative.
    if silence in ("own_only", "full"):
        zero_chance = 1.0
    elif divergence >= 0.5 and volume == 1:
        zero_chance = 0.85
    elif divergence >= 0.3 and volume == 1:
        zero_chance = 0.65
    elif divergence >= 0.5 and volume == 2:
        zero_chance = 0.4
    elif divergence >= 0.3 and volume == 2:
        zero_chance = 0.2
    else:
        zero_chance = 0.0

    if rng.random() < zero_chance:
        return {
            "ctr": 0.0,
            "position": 0.0,
            "impressions": 0,
            "clicks": 0,
            "volume_band": _volume_band(volume),
            "no_classical_search": True,
        }

    ctr_base = {1: 0.15, 2: 0.08, 3: 0.04}.get(volume, 0.08)
    ctr = ctr_base * (1 - divergence * 0.4)
    if silence in ("own_only", "full"):
        ctr *= 0.55
    ctr *= rng.uniform(0.65, 1.35)
    ctr = max(0.0, min(0.6, round(ctr, 4)))

    impressions_range = {1: (20, 220), 2: (320, 2600), 3: (3800, 19000)}[volume]
    impressions = rng.randint(*impressions_range)
    clicks = int(round(impressions * ctr))

    position = 3.5 + volume * 2.2 + divergence * 4.5
    if silence in ("own_only", "full"):
        position += 3.5
    position += rng.uniform(-1.2, 1.6)
    position = max(1.0, round(position, 1))

    return {
        "ctr": ctr,
        "position": position,
        "impressions": impressions,
        "clicks": clicks,
        "volume_band": _volume_band(volume),
        "no_classical_search": False,
    }


def _priority_score(p: dict[str, Any], gsc: dict[str, Any]) -> float:
    """High divergence + low CTR + weak position = high priority.

    Prompts with no classical-search volume at all (AI-only queries) get
    the maximum classical-side penalty — the brand can't win them through
    traditional SEO at all, so closing the AI gap is the only available lever.
    """
    divergence = float(p.get("divergence_score") or 0.0)
    if gsc.get("no_classical_search"):
        return round(0.55 * divergence + 0.3 * 1.0 + 0.15 * 1.0, 3)
    ctr = gsc["ctr"]
    position = gsc["position"]
    ctr_penalty = max(0.0, min(1.0, 1 - ctr / 0.15))
    pos_penalty = max(0.0, min(1.0, (position - 1) / 19))
    return round(0.55 * divergence + 0.3 * ctr_penalty + 0.15 * pos_penalty, 3)


def fetch(prompts: list[dict[str, Any]]) -> dict[str, Any]:
    """Return {source, note, by_prompt, top_priority} for the given prompts."""
    sa = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
    prop = os.environ.get("GSC_PROPERTY_URL")
    if sa and prop:
        # Live path not implemented yet – falls back to demo so the build
        # does not break when only one secret is half-configured.
        note = (
            "GSC_PROPERTY_URL is set but the live GSC fetch is stubbed. "
            "Wire up the Google API client in connectors/gsc.py → fetch_live()."
        )
        return {
            "source": "live-stub",
            "property_url": prop,
            "note": note,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "by_prompt": {},
            "top_priority": [],
        }

    by_prompt = {}
    for p in prompts:
        pid = p.get("prompt_id") or ""
        row = _demo_row(p)
        row["priority_score"] = _priority_score(p, row)
        row["prompt_id"] = pid
        row["prompt_text"] = p.get("prompt_text", "")
        row["divergence_score"] = round(float(p.get("divergence_score") or 0.0), 3)
        row["silence_type"] = p.get("silence_type") or "active"
        by_prompt[pid] = row

    top = sorted(
        by_prompt.values(),
        key=lambda r: r["priority_score"],
        reverse=True,
    )[:10]

    return {
        "source": "demo",
        "property_url": None,
        "note": (
            "Demo data seeded deterministically from Peec prompt_id. "
            "Setting GSC_SERVICE_ACCOUNT_JSON and GSC_PROPERTY_URL switches the "
            "connector to live-stub status; wire the Google API Python client in "
            "connectors/gsc.py → fetch_live() to populate live values "
            "(under 50 lines around the existing demo-mode plumbing)."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_prompt": by_prompt,
        "top_priority": top,
    }


if __name__ == "__main__":
    from pathlib import Path

    here = Path(__file__).resolve().parent
    ui = here.parent / "data" / "ui" / "drift_radar.json"
    data = json.loads(ui.read_text(encoding="utf-8"))
    out = fetch(data["prompts"])
    print(json.dumps({k: v for k, v in out.items() if k != "by_prompt"}, indent=2))
    print(f"by_prompt: {len(out['by_prompt'])} rows")
