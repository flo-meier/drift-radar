"""Google Ads connector for Drift Radar.

Pairs every Peec prompt with the paid-search shadow: how much spend is
already running on this query, and how much of that spend is at risk if
the AI narrative keeps drifting away from the brand.

Two modes:

1. **Live mode** – when `GOOGLE_ADS_DEVELOPER_TOKEN` and
   `GOOGLE_ADS_CUSTOMER_ID` are set, would pull search-term-report data
   from the Google Ads API for the last 30 days.

2. **Demo mode** – deterministic mock seeded from each prompt_id.
   Plausible-looking numbers for performance teams that have not yet
   connected their Ads account; marked `"source": "demo"` in the UI.

Mock heuristic (Pferdegold-typical performance bands):
    - cpc      seeded in [0.30, 1.50] € per click
    - clicks   = function of (volume_band × paid_share)
    - spend_monthly = clicks × cpc
    - conversion_rate slightly below organic (paid pulls broader intent)
    - revenue  = clicks × CR × AOV(seeded 55–115 €)
    - spend_at_risk = spend_monthly × (0.5 + 0.5 × divergence)
                      + 30 % surcharge if silence_type ∈ {own_only, full}
                      capped at spend_monthly
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timezone
from typing import Any


DEMO_ACCOUNT_NAME = "Pferdegold Performance (demo)"


def _stable_rng(key: str) -> random.Random:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def _demo_row(prompt: dict[str, Any], gsc_row: dict[str, Any] | None) -> dict[str, Any]:
    rng = _stable_rng("ads::" + (prompt.get("prompt_id") or ""))
    volume = prompt.get("volume") or 2
    divergence = float(prompt.get("divergence_score") or 0.0)
    silence = prompt.get("silence_type") or "active"
    no_classical = bool(gsc_row and gsc_row.get("no_classical_search"))

    # Paid-click bands by volume tier. Long-tail terms get fewer paid
    # clicks because intent is more conversational than commercial.
    paid_clicks_band = {1: (3, 35), 2: (45, 380), 3: (520, 2400)}[volume]
    if no_classical:
        # No classical search volume means no Google Ads inventory either:
        # you cannot buy clicks on a query Google has zero impressions for.
        clicks_monthly = 0
        cpc = 0.0
    else:
        clicks_monthly = rng.randint(*paid_clicks_band)
        cpc = round(rng.uniform(0.30, 1.50), 2)
    spend_monthly = round(clicks_monthly * cpc, 2)

    # Paid CR sits slightly below organic CR – broader intent, more research clicks.
    cr_base = {1: 0.032, 2: 0.018, 3: 0.010}[volume]
    conversion_rate = round(cr_base * rng.uniform(0.65, 1.35), 4)
    aov = round(rng.uniform(55, 115), 2)
    revenue_monthly = round(clicks_monthly * conversion_rate * aov, 2)

    risk_factor = 0.5 + 0.5 * divergence
    if silence in ("own_only", "full"):
        risk_factor = min(1.0, risk_factor + 0.3)
    spend_at_risk = round(spend_monthly * risk_factor, 2)

    return {
        "prompt_id": prompt.get("prompt_id", ""),
        "prompt_text": prompt.get("prompt_text", ""),
        "divergence_score": round(divergence, 3),
        "silence_type": silence,
        "no_classical_search": no_classical,
        "ad_clicks_monthly": clicks_monthly,
        "ad_cpc": cpc,
        "ad_spend_monthly": spend_monthly,
        "ad_conversion_rate": conversion_rate,
        "ad_avg_order_value": aov,
        "ad_revenue_monthly": revenue_monthly,
        "risk_factor": round(risk_factor, 3),
        "ad_spend_at_risk": spend_at_risk,
    }


def fetch(prompts: list[dict[str, Any]], gsc: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {source, note, by_prompt, top_risk, totals} for the given prompts."""
    token = os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN")
    customer = os.environ.get("GOOGLE_ADS_CUSTOMER_ID")
    if token and customer:
        return {
            "source": "live-stub",
            "customer_id": customer,
            "account_name": "(live Google Ads fetch stubbed – wire connectors/google_ads.py → fetch_live())",
            "note": (
                "GOOGLE_ADS_CUSTOMER_ID is set but the live Google Ads fetch is stubbed. "
                "Wire the google-ads-python client in connectors/google_ads.py → fetch_live()."
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
        by_prompt[pid] = _demo_row(p, gsc_by_prompt.get(pid))

    top_risk = sorted(
        (r for r in by_prompt.values() if r["ad_clicks_monthly"] > 0),
        key=lambda r: r["ad_spend_at_risk"],
        reverse=True,
    )[:10]

    totals = {
        "ad_spend_monthly_total": round(sum(r["ad_spend_monthly"] for r in by_prompt.values()), 2),
        "ad_spend_at_risk_total": round(sum(r["ad_spend_at_risk"] for r in by_prompt.values()), 2),
        "prompts_at_risk": sum(1 for r in by_prompt.values() if r["ad_spend_at_risk"] > 100),
        "prompts_no_classical": sum(1 for r in by_prompt.values() if r["no_classical_search"]),
    }

    return {
        "source": "demo",
        "customer_id": None,
        "account_name": DEMO_ACCOUNT_NAME,
        "note": (
            "Demo data seeded deterministically from Peec prompt_id. "
            "Setting GOOGLE_ADS_DEVELOPER_TOKEN and GOOGLE_ADS_CUSTOMER_ID switches the "
            "connector to live-stub status; wire the google-ads-python client in "
            "connectors/google_ads.py → fetch_live() to populate live values "
            "(roughly 50 lines around the demo-mode plumbing)."
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
