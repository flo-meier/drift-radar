#!/usr/bin/env python3
"""Drift Radar – Cross-Model Divergence + Own-Silence Metrics.

Reads cached Peec MCP JSON exports, computes:
  - Cross-model visibility divergence (range + CV) per prompt
  - Own-brand silence flag (no mention in any active model)
  - Silence split: own_only_silence (competitors active) vs full_silence (category silent)
  - Top competitors per own-only-silence prompt
  - Wilson score 95% CIs per prompt x model
  - Attaches hand-picked chat samples for deep-dive UI
Outputs UI-ready JSON and prints a top-divergence summary.
"""
import json
import math
from pathlib import Path
from statistics import mean, pstdev

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
UI = ROOT / "data" / "ui"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_prompt_matrix(brand_report):
    """{prompt_id: {model_id: metrics_dict}} from own-brand filtered report."""
    cols = brand_report["columns"]
    idx = {c: i for i, c in enumerate(cols)}
    matrix = {}
    for row in brand_report["rows"]:
        pid = row[idx["prompt_id"]]
        mid = row[idx["model_id"]]
        matrix.setdefault(pid, {})[mid] = {
            "visibility": row[idx["visibility"]] or 0,
            "mention_count": row[idx["mention_count"]] or 0,
            "share_of_voice": row[idx["share_of_voice"]] or 0,
            "sentiment": row[idx["sentiment"]],
            "position": row[idx["position"]],
            "visibility_count": row[idx["visibility_count"]] or 0,
            "visibility_total": row[idx["visibility_total"]] or 0,
        }
    return matrix


def build_competitor_index(all_brands_report, own_id):
    """{prompt_id: {brand_id: {model_id: visibility}}} for all non-own brands."""
    cols = all_brands_report["columns"]
    idx = {c: i for i, c in enumerate(cols)}
    index = {}
    for row in all_brands_report["rows"]:
        bid = row[idx["brand_id"]]
        if bid == own_id:
            continue
        pid = row[idx["prompt_id"]]
        mid = row[idx["model_id"]]
        vis = row[idx["visibility"]] or 0
        if vis <= 0:
            continue
        index.setdefault(pid, {}).setdefault(bid, {})[mid] = vis
    return index


def wilson_ci(successes, trials, z=1.96):
    if trials == 0:
        return (0.0, 1.0)
    p = successes / trials
    denom = 1 + z**2 / trials
    centre = (p + z**2 / (2 * trials)) / denom
    half = (z * math.sqrt(p * (1 - p) / trials + z**2 / (4 * trials**2))) / denom
    return (round(max(0, centre - half), 4), round(min(1, centre + half), 4))


def compute_prompt_metrics(per_model, active_models):
    vis_vals = [(per_model[m]["visibility"] if m in per_model else 0) for m in active_models]
    mean_vis = mean(vis_vals) if vis_vals else 0
    range_vis = max(vis_vals) - min(vis_vals) if vis_vals else 0
    cv_vis = pstdev(vis_vals) / mean_vis if mean_vis > 0 else 0

    own_silence = max(vis_vals) == 0
    divergence_score = round(0.7 * range_vis + 0.3 * min(cv_vis, 2.0) / 2.0, 3)

    wilson = {}
    for m in active_models:
        if m in per_model:
            s = per_model[m]["visibility_count"]
            n = per_model[m]["visibility_total"]
            wilson[m] = wilson_ci(s, n)
        else:
            wilson[m] = None

    def by_model(field, default=None):
        return {m: (per_model[m].get(field, default) if m in per_model else default) for m in active_models}

    return {
        "visibility_by_model": {m: round(per_model[m]["visibility"], 3) if m in per_model else 0 for m in active_models},
        "mentions_by_model": {m: per_model[m]["mention_count"] if m in per_model else 0 for m in active_models},
        "position_by_model": by_model("position"),
        "sentiment_by_model": by_model("sentiment"),
        "wilson_ci_by_model": wilson,
        "divergence_score": divergence_score,
        "cv_visibility": round(cv_vis, 3),
        "range_visibility": round(range_vis, 3),
        "mean_visibility": round(mean_vis, 3),
        "own_silence": own_silence,
    }


def classify_silence(prompt_id, own_silence, competitor_index, brands_lookup, model_names):
    """Returns silence_type ('full' | 'own_only' | None) + top competitors list."""
    if not own_silence:
        return None, []
    comp_data = competitor_index.get(prompt_id, {})
    if not comp_data:
        return "full", []

    # Aggregate competitor visibility across models (max per brand)
    comp_summary = []
    for bid, model_vis in comp_data.items():
        max_vis = max(model_vis.values())
        # Which models have them
        active = [{"model": model_names.get(m, m), "visibility": round(v, 2)} for m, v in model_vis.items()]
        active.sort(key=lambda x: -x["visibility"])
        comp_summary.append({
            "brand_id": bid,
            "brand_name": brands_lookup[bid]["name"],
            "max_visibility": round(max_vis, 2),
            "seen_in": active,
        })
    comp_summary.sort(key=lambda x: -x["max_visibility"])
    return "own_only", comp_summary[:5]


CLAIM_TYPES = ("brand", "substance", "function", "condition", "criterion")


def summarize_claims(by_model, active_models):
    """Cross-model narrative-stability summary.
    Returns {
      "coverage": int,                 # how many engines have claim data
      "type_counts_by_model": {model_id: {type: count}},
      "shared_substances": [str],      # substance claim texts that appear in 2+ engines
      "shared_criteria": [str],        # criterion claim texts that appear in 2+ engines
      "unique_brands_by_model": {model_id: [brand_text]},
    }
    """
    coverage = 0
    type_counts = {}
    by_type_text = {t: {} for t in CLAIM_TYPES}  # type -> normalized text -> set of models
    unique_brands = {}

    for m in active_models:
        claims = (by_model.get(m) or {}).get("claims") or []
        if claims:
            coverage += 1
        counts = {t: 0 for t in CLAIM_TYPES}
        brand_texts = []
        for c in claims:
            t = c.get("type")
            if t not in CLAIM_TYPES:
                continue
            counts[t] += 1
            key = _normalize_claim_key(c.get("text", ""), t)
            if key:
                by_type_text[t].setdefault(key, {"text": c.get("text", ""), "models": set()})
                by_type_text[t][key]["models"].add(m)
            if t == "brand":
                brand_texts.append(c.get("text", ""))
        type_counts[m] = counts
        unique_brands[m] = brand_texts

    shared_substances = sorted(
        {v["text"] for v in by_type_text["substance"].values() if len(v["models"]) >= 2}
    )
    shared_criteria = sorted(
        {v["text"] for v in by_type_text["criterion"].values() if len(v["models"]) >= 2}
    )

    return {
        "coverage": coverage,
        "type_counts_by_model": type_counts,
        "shared_substances": shared_substances,
        "shared_criteria": shared_criteria,
        "unique_brands_by_model": unique_brands,
    }


def _normalize_claim_key(text, claim_type):
    """Cheap equivalence key for claim dedup across engines.
    For brand: lowercase first 2 words (brand identity tends to be the head noun).
    For substance/criterion: strip to significant tokens, lowercase, sorted.
    """
    import re
    if not text:
        return ""
    if claim_type == "brand":
        words = re.findall(r"\w+", text.lower())
        return " ".join(words[:2])
    STOP = {"the","a","an","is","are","be","has","have","contains","contain","offers",
            "with","for","of","and","or","to","from","as","that","this","these","those",
            "it","product","products","supports","support","pellets","pellet","brand",
            "brands","joint","joints","stomach","horse","horses","sensitive","recommended",
            "quality","should","made","in","on","their"}
    tokens = [t for t in re.findall(r"\w+", text.lower()) if len(t) > 3 and t not in STOP]
    return " ".join(sorted(set(tokens)))


def load_claims_map():
    """{(prompt_id, model_id): [claims]} from data/raw/claims.json, empty if absent."""
    path = RAW / "claims.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {}
    for entry in data.get("by_chat_id", {}).values():
        key = (entry.get("prompt_id"), entry.get("model_id"))
        if key[0] and key[1]:
            out[key] = entry.get("claims", [])
    return out


def load_sources_map():
    """{prompt_id: {by_class_normalized, top_domains, total_retrieved}} from sources_by_prompt.json."""
    path = RAW / "sources_by_prompt.json"
    if not path.exists():
        return {}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    return data.get("by_prompt", {}), sorted(data.get("classifications", []))


def aggregate_source_classes(by_prompt_sources):
    """Aggregate classification totals across all prompts for Overview block."""
    totals = {}
    for pid, entry in by_prompt_sources.items():
        for cls, val in entry.get("by_class", {}).items():
            totals[cls] = totals.get(cls, 0) + val
    grand = sum(totals.values())
    if grand == 0:
        return totals, {}
    return totals, {cls: round(v / grand, 4) for cls, v in totals.items()}


def main():
    lookup = load_json(RAW / "lookup_tables.json")
    own_report = load_json(RAW / "pferdegold_brand_report.json")
    all_report = load_json(RAW / "all_brands_report.json")
    chat_samples = load_json(RAW / "chat_samples.json")
    claims_map = load_claims_map()
    sources_by_prompt, all_classifications = load_sources_map()

    active_models = [m for m, info in lookup["models"].items() if info["is_active"]]
    model_names = {m: info["name"] for m, info in lookup["models"].items()}
    own_id = lookup["own_brand_id"]

    matrix = build_prompt_matrix(own_report)
    competitor_index = build_competitor_index(all_report, own_id)

    # Build chat-samples lookup (prompt_id -> sample) and attach extracted claims
    samples_by_prompt = {}
    for sample in chat_samples["samples"]:
        pid = sample["prompt_id"]
        enriched = json.loads(json.dumps(sample))  # deep copy, no extra imports
        for model_id, per_model in enriched.get("by_model", {}).items():
            claims = claims_map.get((pid, model_id))
            if claims:
                per_model["claims"] = claims
        enriched["claim_summary"] = summarize_claims(enriched.get("by_model", {}), active_models)
        samples_by_prompt[pid] = enriched

    results = []
    for pid, per_model in matrix.items():
        prompt_info = lookup["prompts"].get(pid, {"text": "?", "topic_id": None, "volume": None})
        metrics = compute_prompt_metrics(per_model, active_models)
        silence_type, top_competitors = classify_silence(
            pid, metrics["own_silence"], competitor_index, lookup["brands"], model_names
        )
        entry = {
            "prompt_id": pid,
            "prompt_text": prompt_info["text"],
            "topic": lookup["topics"].get(prompt_info.get("topic_id"), "?"),
            "volume": prompt_info.get("volume"),
            **metrics,
            "silence_type": silence_type,
            "top_competitors": top_competitors,
        }
        if pid in samples_by_prompt:
            entry["chat_sample"] = samples_by_prompt[pid]
        if pid in sources_by_prompt:
            entry["source_mix"] = {
                "by_class": sources_by_prompt[pid]["by_class"],
                "by_class_normalized": sources_by_prompt[pid]["by_class_normalized"],
                "top_domains": sources_by_prompt[pid]["top_domains"],
                "total_retrieved": sources_by_prompt[pid]["total_retrieved"],
            }
        results.append(entry)

    results.sort(key=lambda x: x["divergence_score"], reverse=True)

    total = len(results)
    silence_count = sum(1 for r in results if r["own_silence"])
    own_only = sum(1 for r in results if r["silence_type"] == "own_only")
    full_silence = sum(1 for r in results if r["silence_type"] == "full")
    high_divergence = [r for r in results if r["divergence_score"] >= 0.3]
    avg_vis = round(mean([r["mean_visibility"] for r in results]), 3) if results else 0

    source_totals, source_shares = aggregate_source_classes(sources_by_prompt)

    output = {
        "project": lookup["project"]["name"],
        "own_brand": lookup["brands"][own_id]["name"],
        "date_range": own_report["date_range"],
        "active_models": [{"id": m, "name": lookup["models"][m]["name"]} for m in active_models],
        "competitors": [
            {"id": bid, "name": info["name"], "domain": info["domain"]}
            for bid, info in lookup["brands"].items() if not info["is_own"]
        ],
        "summary": {
            "total_prompts": total,
            "own_silence_count": silence_count,
            "own_silence_percent": round(100 * silence_count / total, 1) if total else 0,
            "own_only_silence_count": own_only,
            "full_silence_count": full_silence,
            "high_divergence_count": len(high_divergence),
            "avg_own_visibility": avg_vis,
        },
        "source_classifications": all_classifications,
        "source_overview": {
            "by_class_weight": source_totals,
            "by_class_share": source_shares,
            "prompts_with_sources": len(sources_by_prompt),
        },
        "prompts": results,
    }

    UI.mkdir(parents=True, exist_ok=True)
    (UI / "drift_radar.json").write_text(json.dumps(output, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"\n=== DRIFT RADAR – {output['project']} ===")
    print(f"Date range: {own_report['date_range']['start']} -> {own_report['date_range']['end']}")
    print(f"Active models: {', '.join(m['name'] for m in output['active_models'])}")
    print(f"Total prompts: {total}")
    print(f"Own-brand silence (zero mentions across ALL models): {silence_count}/{total} ({output['summary']['own_silence_percent']}%)")
    print(f"  ├─ OWN-ONLY silence (competitors active, you are not): {own_only}")
    print(f"  └─ FULL silence (category silent on all engines):     {full_silence}")
    print(f"High divergence prompts (score >= 0.3): {len(high_divergence)}")
    print(f"Avg own-brand visibility across prompts: {avg_vis}")

    print("\n--- TOP 10 HIGH-DIVERGENCE PROMPTS ---")
    hdr = "     score  " + "  ".join(f"{m['name']:>10s}" for m in output['active_models']) + "   prompt"
    print(hdr)
    for r in results[:10]:
        vis_str = "  ".join(f"{r['visibility_by_model'][m['id']]:10.2f}" for m in output['active_models'])
        print(f"  {r['divergence_score']:5.2f}  {vis_str}   {r['prompt_text'][:70]}")

    print("\n--- TOP OWN-ONLY SILENCE PROMPTS (competitor opportunity) ---")
    own_only_prompts = [r for r in results if r["silence_type"] == "own_only"]
    own_only_prompts.sort(key=lambda r: -(r["volume"] or 0))
    print(f"Total: {len(own_only_prompts)} prompts where Pferdegold is silent but at least one competitor is cited.")
    for r in own_only_prompts[:10]:
        top3 = ", ".join(c["brand_name"] for c in r["top_competitors"][:3])
        print(f"  vol={r['volume']}  [{top3}]  {r['prompt_text'][:70]}")

    print("\n--- FULL SILENCE PROMPTS (category is brand-neutral) ---")
    full = [r for r in results if r["silence_type"] == "full"]
    print(f"Total: {len(full)} prompts where NO tracked brand is mentioned by any model.")
    for r in full[:10]:
        print(f"  vol={r['volume']}  {r['prompt_text'][:80]}")


if __name__ == "__main__":
    main()
