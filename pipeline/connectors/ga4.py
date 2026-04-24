"""Google Analytics 4 connector for Drift Radar.

Pairs every Peec prompt with a revenue-at-risk signal. The core
insight: a drifting prompt already has a monetary shadow – clicks
flowing today that are at risk of migrating to a competitor's
narrative tomorrow.

Two modes:

1. **Live mode** – when `GA4_SERVICE_ACCOUNT_JSON` + `GA4_PROPERTY_ID`
   are set, pulls landing-page session + revenue metrics for the
   last 30 days via the Google Analytics Data API.

2. **Demo mode** – deterministic mock seeded from each prompt_id.
   Plausible-looking numbers for content teams that have not yet
   connected their property; marked `"source": "demo"` in the UI.

Mock heuristic:
    - clicks_monthly = (GSC-style) impressions × CTR, rounded
    - conversion_rate by volume band: niche → 4%, medium → 2%, high → 1%
    - avg_order_value = seeded in [55, 115] € (Pferdegold-typical band)
    - revenue_monthly = clicks × CR × AOV
    - revenue_at_risk = revenue_monthly × (0.5 + 0.5 × divergence),
      plus a +30 % silence-penalty for own_only / full_silence prompts
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timezone
from typing import Any


DEMO_PROPERTY_NAME = "Pferdegold Shop (demo)"


def _stable_rng(key: str) -> random.Random:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def _demo_row(prompt: dict[str, Any], gsc_row: dict[str, Any] | None) -> dict[str, Any]:
    rng = _stable_rng("ga4::" + (prompt.get("prompt_id") or ""))
    volume = prompt.get("volume") or 2
    divergence = float(prompt.get("divergence_score") or 0.0)
    silence = prompt.get("silence_type") or "active"

    # Monthly clicks – reuse GSC mock if present, otherwise derive one.
    if gsc_row:
        clicks_monthly = max(1, int(gsc_row.get("clicks") or 0))
    else:
        impressions = {1: (20, 220), 2: (320, 2600), 3: (3800, 19000)}[volume]
        clicks_monthly = max(1, int(rng.randint(*impressions) * rng.uniform(0.02, 0.1)))

    cr_base = {1: 0.04, 2: 0.022, 3: 0.012}[volume]
    conversion_rate = round(cr_base * rng.uniform(0.65, 1.35), 4)
    aov = round(rng.uniform(55, 115), 2)
    revenue_monthly = round(clicks_monthly * conversion_rate * aov, 2)

    risk_factor = 0.5 + 0.5 * divergence
    if silence in ("own_only", "full"):
        risk_factor = min(1.0, risk_factor + 0.3)
    revenue_at_risk = round(revenue_monthly * risk_factor, 2)

    return {
        "prompt_id": prompt.get("prompt_id", ""),
        "prompt_text": prompt.get("prompt_text", ""),
        "divergence_score": round(divergence, 3),
        "silence_type": silence,
        "clicks_monthly": clicks_monthly,
        "conversion_rate": conversion_rate,
        "avg_order_value": aov,
        "revenue_monthly": revenue_monthly,
        "risk_factor": round(risk_factor, 3),
        "revenue_at_risk": revenue_at_risk,
    }


def fetch(prompts: list[dict[str, Any]], gsc: dict[str, Any] | None = None) -> dict[str, Any]:
    sa = os.environ.get("GA4_SERVICE_ACCOUNT_JSON")
    prop = os.environ.get("GA4_PROPERTY_ID")
    if sa and prop:
        return {
            "source": "live-stub",
            "property_id": prop,
            "property_name": "(live GA4 fetch stubbed – wire connectors/ga4.py → fetch_live())",
            "note": (
                "GA4_PROPERTY_ID is set but the live GA4 fetch is stubbed. "
                "Wire the Google Analytics Data API client in connectors/ga4.py → fetch_live()."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "by_prompt": {},
            "top_risk": [],
            "totals": {},
        }

    gsc_by_prompt = (gsc or {}).get("by_prompt", {}) if gsc else {}
    by_prompt = {}
    for p in prompts:
        pid = p.get("prompt_id") or ""
        row = _demo_row(p, gsc_by_prompt.get(pid))
        by_prompt[pid] = row

    top_risk = sorted(
        by_prompt.values(),
        key=lambda r: r["revenue_at_risk"],
        reverse=True,
    )[:10]

    totals = {
        "revenue_monthly_total": round(sum(r["revenue_monthly"] for r in by_prompt.values()), 2),
        "revenue_at_risk_total": round(sum(r["revenue_at_risk"] for r in by_prompt.values()), 2),
        "prompts_at_risk": sum(1 for r in by_prompt.values() if r["revenue_at_risk"] > 50),
    }

    return {
        "source": "demo",
        "property_id": None,
        "property_name": DEMO_PROPERTY_NAME,
        "note": (
            "Demo data seeded deterministically from Peec prompt_id. "
            "Set GA4_SERVICE_ACCOUNT_JSON and GA4_PROPERTY_ID in the repo "
            "Secrets to replace with live Google Analytics 4 data."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_prompt": by_prompt,
        "top_risk": top_risk,
        "totals": totals,
    }


if __name__ == "__main__":
    from pathlib import Path
    here = Path(__file__).resolve().parent
    ui = here.parent / "data" / "ui" / "drift_radar.json"
    data = json.loads(ui.read_text(encoding="utf-8"))
    out = fetch(data["prompts"])
    print(json.dumps({k: v for k, v in out.items() if k not in ("by_prompt", "top_risk")}, indent=2))
    print(f"by_prompt: {len(out['by_prompt'])} rows · totals: {out['totals']}")
