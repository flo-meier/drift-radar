"""Ahrefs connector for Drift Radar.

Pairs every Peec prompt with:
    - the URL that actually ranks for it today (real, from Peec gap-URL data)
    - a mocked keyword difficulty (KD 0–100)
    - a mocked monthly search volume
    - a mocked backlink count for the ranking URL

Core insight surfaced on the Stack tab: *»where can I kip the narrative
cheapest?«* High divergence (the engines already disagree – space for your
version) combined with low KD (no SEO fortress guarding the keyword) =
low-hanging fruit.

Demo mode uses real top-competitor URLs harvested by Peec MCP itself –
pipeline/data/raw/gap_urls_digested.json – so the list of URLs on the
Stack tab is live and clickable, only the Ahrefs-side numbers are demo.
Set AHREFS_API_KEY to replace the KD/volume/backlinks with live metrics.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
GAP_URLS = ROOT / "data" / "raw" / "gap_urls_digested.json"


def _stable_rng(key: str) -> random.Random:
    h = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return random.Random(int(h[:16], 16))


def _load_gap_urls() -> dict[str, list[dict[str, Any]]]:
    if not GAP_URLS.exists():
        return {}
    data = json.loads(GAP_URLS.read_text(encoding="utf-8"))
    return data.get("by_prompt", {}) if isinstance(data, dict) else {}


def _pick_top_url(entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Highest-cited URL for the prompt – best proxy for »today's ranker«."""
    if not entries:
        return None
    return max(
        entries,
        key=lambda e: (
            (e.get("citation_count") or 0),
            (e.get("retrieval_count") or 0),
            (e.get("citation_rate") or 0),
        ),
    )


def _domain_strength(domain: str, rng: random.Random) -> int:
    """Heuristic base KD per-domain. Deterministic via the rng seed."""
    well_known = {
        "marstall.de": 55,
        "pavo-futter.de": 60,
        "st-hippolyt.de": 58,
        "hoeveler.com": 48,
        "josera.de": 52,
        "eggersmann.info": 45,
        "iwest.de": 42,
        "reiterrevue.de": 68,
        "pferdewissen.de": 52,
        "cavallo.de": 70,
        "stroeh.de": 40,
    }
    base = well_known.get(domain.lower(), 38)
    return int(max(5, min(95, base + rng.randint(-8, 8))))


def _demo_row(prompt: dict[str, Any], gap_entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if not gap_entry or not gap_entry.get("url"):
        return None

    url = gap_entry["url"]
    try:
        domain = url.split("/")[2]
    except IndexError:
        domain = ""

    rng = _stable_rng("ahrefs::" + (prompt.get("prompt_id") or "") + "::" + url)
    volume = prompt.get("volume") or 2
    divergence = float(prompt.get("divergence_score") or 0.0)

    kd = _domain_strength(domain, rng)
    search_volume_range = {1: (40, 520), 2: (520, 4800), 3: (4800, 32000)}[volume]
    search_volume = rng.randint(*search_volume_range)
    backlinks = int(kd * rng.uniform(1.8, 5.2) + rng.randint(10, 90))

    opportunity_score = round(divergence * (100 - kd) / 100, 3)

    return {
        "prompt_id": prompt.get("prompt_id", ""),
        "prompt_text": prompt.get("prompt_text", ""),
        "divergence_score": round(divergence, 3),
        "silence_type": prompt.get("silence_type") or "active",
        "top_ranking_url": url,
        "top_ranking_domain": domain,
        "top_ranking_title": gap_entry.get("title") or "",
        "top_ranking_classification": gap_entry.get("classification") or "",
        "keyword_difficulty": kd,
        "monthly_search_volume": search_volume,
        "backlinks_to_url": backlinks,
        "opportunity_score": opportunity_score,
    }


def fetch(prompts: list[dict[str, Any]]) -> dict[str, Any]:
    if os.environ.get("AHREFS_API_KEY"):
        return {
            "source": "live-stub",
            "note": (
                "AHREFS_API_KEY is set but the live Ahrefs fetch is stubbed. "
                "Wire the Ahrefs v3 API client in connectors/ahrefs.py → fetch_live()."
            ),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "by_prompt": {},
            "top_opportunity": [],
            "coverage": {},
        }

    gap_by_prompt = _load_gap_urls()
    by_prompt = {}
    tracked = 0
    for p in prompts:
        pid = p.get("prompt_id") or ""
        top = _pick_top_url(gap_by_prompt.get(pid) or [])
        row = _demo_row(p, top)
        if row:
            by_prompt[pid] = row
            tracked += 1

    top_opportunity = sorted(
        by_prompt.values(),
        key=lambda r: r["opportunity_score"],
        reverse=True,
    )[:10]

    coverage = {
        "prompts_with_live_url": tracked,
        "prompts_total": len(prompts),
    }

    return {
        "source": "demo",
        "note": (
            "Top-ranking URLs are real – harvested by Peec MCP from "
            "data/raw/gap_urls_digested.json. Keyword difficulty, search "
            "volume and backlink counts are deterministic mock rows per "
            "(prompt, domain) pair. Setting AHREFS_API_KEY switches the "
            "connector to live-stub status; wire the Ahrefs v3 client in "
            "connectors/ahrefs.py → fetch_live() to populate live metrics "
            "(under 50 lines around the existing demo-mode plumbing)."
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_prompt": by_prompt,
        "top_opportunity": top_opportunity,
        "coverage": coverage,
    }


if __name__ == "__main__":
    here = Path(__file__).resolve().parent
    ui = here.parent / "data" / "ui" / "drift_radar.json"
    data = json.loads(ui.read_text(encoding="utf-8"))
    out = fetch(data["prompts"])
    print(json.dumps({k: v for k, v in out.items() if k not in ("by_prompt", "top_opportunity")}, indent=2))
    print(f"rows: {len(out['by_prompt'])} · top_opportunity[0]:")
    if out["top_opportunity"]:
        print(json.dumps(out["top_opportunity"][0], indent=2))
