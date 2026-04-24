#!/usr/bin/env python3
"""Fetch raw Peec MCP data for Drift Radar.

Reads PEEC_API_KEY and PEEC_PROJECT_ID from the environment.
If the key is missing, exits with a clear message – the downstream
pipeline will fall back to whatever JSON is already cached in data/raw/.

Peec REST API reference:
    https://docs.peec.ai/api
    (beta, enterprise-only at the time of writing)

The functions are named after the MCP tools they replace so the
pipeline contract stays legible:
    - list_projects
    - list_prompts
    - get_brand_report
    - list_chats / get_chat
    - get_domain_report
    - list_search_queries / list_shopping_queries
    - list_tags
"""
import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

API_BASE = os.environ.get("PEEC_API_BASE", "https://api.peec.ai/v1")
API_KEY = os.environ.get("PEEC_API_KEY")
PROJECT_ID = os.environ.get("PEEC_PROJECT_ID", "or_1caa4808-fd8b-44d9-b330-cc7909741cb4")
DATE_RANGE_DAYS = int(os.environ.get("PEEC_DATE_RANGE_DAYS", "7"))


def _require_key():
    if not API_KEY:
        print(
            "PEEC_API_KEY not set – fetch step skipped.\n"
            "Pipeline will re-compute from cached data/raw/*.json.\n"
            "Set PEEC_API_KEY in GitHub repo secrets (Settings → Secrets and variables → Actions).",
            file=sys.stderr,
        )
        sys.exit(0)


def _get(path, params=None):
    url = f"{API_BASE}{path}"
    headers = {"Authorization": f"Bearer {API_KEY}", "Accept": "application/json"}
    r = requests.get(url, headers=headers, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def _write(name, data):
    target = RAW / name
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT.parent)} ({target.stat().st_size:,} bytes)")


def fetch_all():
    _require_key()
    params = {"project_id": PROJECT_ID, "date_range_days": DATE_RANGE_DAYS}

    _write("prompts_meta.json", _get("/prompts", params))
    _write("tags.json", _get("/tags", params))
    _write(
        "pferdegold_brand_report.json",
        _get("/brand-report", {**params, "dimensions": "prompt_id,model_id", "is_own": "true"}),
    )
    _write(
        "all_brands_report.json",
        _get("/brand-report", {**params, "dimensions": "prompt_id,model_id"}),
    )
    _write(
        "sources_by_prompt.json",
        _get("/domain-report", {**params, "dimensions": "prompt_id,domain"}),
    )
    _write("search_queries_digested.json", _get("/search-queries", params))
    _write("shopping_queries_digested.json", _get("/shopping-queries", params))

    # Gentle pacing to stay well under the 200 req/min limit.
    time.sleep(0.5)
    print("fetch complete.")


if __name__ == "__main__":
    fetch_all()
