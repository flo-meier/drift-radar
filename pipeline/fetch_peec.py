#!/usr/bin/env python3
"""Fetch raw Peec data via Customer API v1 for Drift Radar.

Auth: x-api-key header (Pro plan supported as of 2026-04-27)
Base: https://api.peec.ai/customer/v1

Replaces former MCP-based pipeline. Writes JSON files in the legacy
schema downstream code (run.py, build_cross_refs.py, ...) expects:
    - {columns, rows, date_range, ...} for reports
    - {by_prompt, total} for digested queries
    - {by_prompt, classifications, date_range} for sources

Files written:
    - lookup_tables.json
    - prompts_meta.json     (volume column merged from previous snapshot)
    - tags.json
    - pferdegold_brand_report.json
    - all_brands_report.json
    - sources_by_prompt.json
    - search_queries_digested.json
    - shopping_queries_digested.json

Files NOT touched (frozen at submission state):
    - peec_actions.json     (REST has no /actions endpoint)
    - trend_by_date.json    (separate fetch path, out of scope)
    - chat_samples.json     (hand-picked, illustrative)
    - claims.json           (extract_claims.py output, depends on chat_samples)
"""
import json
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)

API_BASE = os.environ.get("PEEC_API_BASE", "https://api.peec.ai/customer/v1")
API_KEY = os.environ.get("PEEC_API_KEY")
PROJECT_ID = os.environ.get("PEEC_PROJECT_ID", "or_1caa4808-fd8b-44d9-b330-cc7909741cb4")
DATE_RANGE_DAYS = int(os.environ.get("PEEC_DATE_RANGE_DAYS", "3"))

THROTTLE_S = 0.4   # 200 req/min limit -> ~150 req/min ceiling
TOP_DOMAINS_PER_PROMPT = 8

session = requests.Session()


def _require_key():
    if not API_KEY:
        print(
            "PEEC_API_KEY not set – fetch step skipped.\n"
            "Pipeline will re-compute from cached data/raw/*.json.",
            file=sys.stderr,
        )
        sys.exit(0)


def _headers():
    return {
        "x-api-key": API_KEY,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _get(path, params=None):
    time.sleep(THROTTLE_S)
    p = {"project_id": PROJECT_ID, **(params or {})}
    r = session.get(f"{API_BASE}{path}", headers=_headers(), params=p, timeout=30)
    if not r.ok:
        print(f"GET {path} -> {r.status_code}: {r.text[:300]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def _post(path, body):
    time.sleep(THROTTLE_S)
    payload = {"project_id": PROJECT_ID, **body}
    r = session.post(f"{API_BASE}{path}", headers=_headers(), json=payload, timeout=60)
    if not r.ok:
        print(f"POST {path} -> {r.status_code}: {r.text[:300]}", file=sys.stderr)
        r.raise_for_status()
    return r.json()


def _paginate_post(path, body, limit=10000):
    rows = []
    offset = 0
    while True:
        body["limit"] = limit
        body["offset"] = offset
        res = _post(path, body)
        items = res.get("data", [])
        rows.extend(items)
        if len(items) < limit:
            break
        offset += limit
    return rows


def _paginate_get(path, params=None, limit=200):
    rows = []
    offset = 0
    p = dict(params or {})
    while True:
        p["limit"] = limit
        p["offset"] = offset
        res = _get(path, p)
        data = res.get("data", [])
        rows.extend(data)
        if len(data) < limit:
            break
        offset += limit
    return rows


def _write(name, data):
    target = RAW / name
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT.parent)} ({target.stat().st_size:,} bytes)")


def _utc_today():
    return datetime.now(timezone.utc).date()


def _date_range():
    """Inclusive N-day window ending yesterday (today may be incomplete on Peec side).

    Override: set PEEC_END_DATE=YYYY-MM-DD to anchor the window for validation runs.
    """
    end_override = os.environ.get("PEEC_END_DATE")
    if end_override:
        end = datetime.fromisoformat(end_override).date()
    else:
        end = _utc_today() - timedelta(days=1)
    start = end - timedelta(days=DATE_RANGE_DAYS - 1)
    return start.isoformat(), end.isoformat()


def _now_stamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def _prompt_text(p):
    msgs = p.get("messages") or []
    if msgs and isinstance(msgs, list):
        return msgs[0].get("content", "") or ""
    return p.get("text", "") or ""


# ---------------- Brand reports ----------------

BRAND_COLUMNS = [
    "brand_id", "brand_name", "visibility", "visibility_count", "visibility_total",
    "mention_count", "share_of_voice", "sentiment", "sentiment_sum", "sentiment_count",
    "position", "position_sum", "position_count", "prompt_id", "model_id",
]


def _r2(v):
    """Round to 2 decimal places, preserving None."""
    return round(v, 2) if v is not None else None


def _r1(v):
    """Round to 1 decimal place, preserving None."""
    return round(v, 1) if v is not None else None


def _flatten_brand_row(item):
    b = item.get("brand", {})
    p = item.get("prompt", {})
    m = item.get("model", {})
    return [
        b.get("id"),
        b.get("name"),
        _r2(item.get("visibility")),       # MCP rounded these; match for bit-exact validation
        item.get("visibility_count"),
        item.get("visibility_total"),
        item.get("mention_count"),
        _r2(item.get("share_of_voice")),
        item.get("sentiment"),
        item.get("sentiment_sum"),
        item.get("sentiment_count"),
        _r1(item.get("position")),         # MCP rounded position to 1 decimal
        item.get("position_sum"),
        item.get("position_count"),
        p.get("id"),
        m.get("id"),
    ]


def fetch_brand_report(start, end, own_brand_id=None):
    body = {
        "start_date": start,
        "end_date": end,
        "dimensions": ["prompt_id", "model_id"],
    }
    if own_brand_id:
        body["filters"] = [{"field": "brand_id", "operator": "in", "values": [own_brand_id]}]
    items = _paginate_post("/reports/brands", dict(body))
    return [_flatten_brand_row(i) for i in items]


# ---------------- Domain digestion ----------------

def fetch_domains_digested(start, end):
    body = {
        "start_date": start,
        "end_date": end,
        "dimensions": ["prompt_id"],
    }
    items = _paginate_post("/reports/domains", dict(body))
    by_prompt_raw = defaultdict(list)
    for item in items:
        pid = (item.get("prompt") or {}).get("id")
        if pid:
            by_prompt_raw[pid].append(item)

    by_prompt = {}
    for pid, prompt_items in by_prompt_raw.items():
        by_class = defaultdict(float)
        for item in prompt_items:
            cls = item.get("classification") or "OTHER"
            # Round before summing (matches MCP behaviour, makes by_class match submission stand)
            by_class[cls] += round(item.get("retrieved_percentage") or 0, 2)
        total = sum(by_class.values())
        by_class_normalized = {
            cls: (v / total) if total else 0
            for cls, v in by_class.items()
        }
        items_sorted = sorted(
            prompt_items, key=lambda i: -(i.get("retrieved_percentage") or 0)
        )
        top_domains = [
            {
                "domain": i["domain"],
                "classification": i.get("classification"),
                "retrieved_percentage": round(i.get("retrieved_percentage") or 0, 2),
                "retrieval_rate": round(i.get("retrieval_rate") or 0, 2),
                "citation_rate": round(i.get("citation_rate") or 0, 2),
            }
            for i in items_sorted[:TOP_DOMAINS_PER_PROMPT]
        ]
        by_prompt[pid] = {
            "by_class": dict(by_class),
            "top_domains": top_domains,
            "by_class_normalized": by_class_normalized,
            "total_retrieved": total,   # full precision; matches submission stand
        }

    classifications = sorted({i.get("classification") for i in items if i.get("classification")})
    return {
        "date_range": {"start": start, "end": end},
        "classifications": classifications,
        "by_prompt": by_prompt,
    }


# ---------------- Queries digestion ----------------

def fetch_search_queries(start, end):
    """Search fanouts: {model, query} per item."""
    body = {"start_date": start, "end_date": end}
    items = _paginate_post("/queries/search", dict(body))
    by_prompt = defaultdict(list)
    for item in items:
        pid = (item.get("prompt") or {}).get("id")
        q = (item.get("query") or {}).get("text")
        model = (item.get("model") or {}).get("id")
        if pid and q:
            by_prompt[pid].append({"model": model, "query": q})
    return dict(by_prompt), len(items)


def fetch_shopping_queries(start, end):
    """Shopping fanouts: {query, products} per item (no model key in legacy schema)."""
    body = {"start_date": start, "end_date": end}
    items = _paginate_post("/queries/shopping", dict(body))
    by_prompt = defaultdict(list)
    for item in items:
        pid = (item.get("prompt") or {}).get("id")
        query = item.get("query") or {}
        q_text = query.get("text")
        products = query.get("products") or []
        if pid and q_text:
            by_prompt[pid].append({"query": q_text, "products": products})
    return dict(by_prompt), len(items)


# ---------------- Lookups + meta ----------------

def fetch_lookups():
    brands = _paginate_get("/brands")
    own_brand = next((b for b in brands if b.get("is_own")), None)
    if not own_brand:
        print("ERROR: no is_own=true brand found in /brands", file=sys.stderr)
        sys.exit(1)

    models = _paginate_get("/models")
    topics = _paginate_get("/topics")
    prompts = _paginate_get("/prompts")
    tags = _paginate_get("/tags")
    return brands, models, topics, prompts, tags, own_brand


def build_lookup_tables(brands, models, topics, prompts, own_brand):
    return {
        "project": {
            "id": PROJECT_ID,
            "name": "Pferdegold",
            "status": "TRIAL",
        },
        "own_brand_id": own_brand["id"],
        "brands": {
            b["id"]: {
                "name": b["name"],
                "domain": (b.get("domains") or [None])[0],
                "is_own": b.get("is_own", False),
            }
            for b in brands
        },
        "models": {
            m["id"]: {"name": m.get("name", m["id"]), "is_active": m.get("is_active", True)}
            for m in models
        },
        "topics": {t["id"]: t.get("name", "?") for t in topics},
        "prompts": {
            p["id"]: {
                "text": _prompt_text(p),
                "topic_id": (p.get("topic") or {}).get("id"),
                "volume": p.get("volume"),   # numeric volume from REST
            }
            for p in prompts
        },
    }


def load_volume_map():
    """Volume bucket per prompt (qualitative, e.g. 'low'/'medium').

    Sourced from pipeline/prompts_volume.json - manually curated config that
    fetch_peec.py does NOT overwrite. Created once from the submission snapshot;
    update by hand when new prompts are added to the project.
    """
    path = ROOT / "prompts_volume.json"
    if not path.exists():
        print("note: prompts_volume.json missing – volume column will be null", file=sys.stderr)
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def merge_volume_into_lookup(lookup, volume_map):
    for pid, vol in volume_map.items():
        if pid in lookup["prompts"]:
            lookup["prompts"][pid]["volume"] = vol


def build_prompts_meta(prompts, volume_map):
    columns = ["id", "text", "tag_ids", "topic_id", "volume"]
    rows = []
    for p in prompts:
        rows.append([
            p["id"],
            _prompt_text(p),
            [t["id"] for t in (p.get("tags") or [])],
            (p.get("topic") or {}).get("id"),
            volume_map.get(p["id"]),
        ])
    return {"fetched_at": _now_stamp(), "columns": columns, "rows": rows}


def build_tags(tags):
    rows = [[t["id"], t.get("name", "")] for t in tags]
    return {"fetched_at": _now_stamp(), "rows": rows}


# ---------------- Sanity gate ----------------

def _sanity_check(named_outputs, start, end):
    errors = []
    own_rows = named_outputs["pferdegold_brand_report"]["rows"]
    all_rows = named_outputs["all_brands_report"]["rows"]
    if not own_rows:
        errors.append("pferdegold_brand_report has 0 rows")
    if len(all_rows) < len(own_rows):
        errors.append(f"all_brands has fewer rows ({len(all_rows)}) than own ({len(own_rows)})")

    sources = named_outputs["sources_by_prompt"]
    if not sources["by_prompt"]:
        errors.append("sources_by_prompt empty")
    for pid, entry in sources["by_prompt"].items():
        if not entry["by_class"]:
            errors.append(f"sources by_class empty for {pid}")
            break

    lookup = named_outputs["lookup_tables"]
    if not lookup["brands"]:
        errors.append("lookup brands empty")
    if not lookup["prompts"]:
        errors.append("lookup prompts empty")

    dr = named_outputs["pferdegold_brand_report"]["date_range"]
    if dr["start"] != start or dr["end"] != end:
        errors.append(f"date_range mismatch: {dr} vs requested {start}-{end}")

    if errors:
        print("\nSANITY GATE FAILED:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)


# ---------------- Main ----------------

def fetch_all():
    _require_key()
    start, end = _date_range()
    print(f"Peec fetch · project={PROJECT_ID} · range={start} → {end} · base={API_BASE}")

    brands, models, topics, prompts, tags, own_brand = fetch_lookups()
    print(f"  · own brand: {own_brand['name']} ({own_brand['id']})")
    print(f"  · {len(brands)} brands, {len(models)} models, {len(topics)} topics, {len(prompts)} prompts, {len(tags)} tags")

    lookup = build_lookup_tables(brands, models, topics, prompts, own_brand)
    # prompts_volume.json holds the qualitative SISTRIX bucket per prompt — used in
    # prompts_meta.json (downstream csv exports). lookup.prompts.volume keeps the
    # numeric REST volume.
    volume_map = load_volume_map()

    own_rows = fetch_brand_report(start, end, own_brand_id=own_brand["id"])
    all_rows = fetch_brand_report(start, end)
    print(f"  · brand report: {len(own_rows)} own rows, {len(all_rows)} all rows")

    sources = fetch_domains_digested(start, end)
    print(f"  · sources: {len(sources['by_prompt'])} prompts × {len(sources['classifications'])} classifications")

    search_by_prompt, search_total = fetch_search_queries(start, end)
    shop_by_prompt, shop_total = fetch_shopping_queries(start, end)
    print(f"  · queries: {search_total} search items, {shop_total} shopping items")

    outputs = {
        "lookup_tables": lookup,
        "prompts_meta": build_prompts_meta(prompts, volume_map),
        "tags": build_tags(tags),
        "pferdegold_brand_report": {
            "columns": BRAND_COLUMNS,
            "rows": own_rows,
            "date_range": {"start": start, "end": end},
            "brand_filter": own_brand["id"],
        },
        "all_brands_report": {
            "columns": BRAND_COLUMNS,
            "rows": all_rows,
            "rowCount": len(all_rows),
        },
        "sources_by_prompt": sources,
        "search_queries_digested": {"by_prompt": search_by_prompt, "total": search_total},
        "shopping_queries_digested": {"by_prompt": shop_by_prompt, "total_entries": shop_total},
    }

    _sanity_check(outputs, start, end)

    for name, data in outputs.items():
        _write(f"{name}.json", data)
    print("\nfetch complete.")


if __name__ == "__main__":
    fetch_all()
