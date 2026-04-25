#!/usr/bin/env python3
"""Drift Radar – Weekly Narrative Report.

Reads the current run's `drift_radar.json` and (if present) the previous run's
snapshot, diffs them, and asks Claude Haiku 4.5 to write a single-page markdown
narrative covering what changed week-over-week.

Outputs:
  - data/ui/narrative_latest.md
  - public/downloads/narrative_<DATE>.md
  - data/ui/previous_run.json  (current run becomes the baseline for next time)

If `ANTHROPIC_API_KEY` is missing, writes a deterministic fallback narrative
(structured data, no prose). Production runs always have the key from CI.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
UI = ROOT / "data" / "ui"
DOWNLOADS = ROOT.parent / "public" / "downloads"

CURRENT = UI / "drift_radar.json"
PREVIOUS = UI / "previous_run.json"
NARRATIVE_LATEST = UI / "narrative_latest.md"

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MODEL = os.environ.get("DRIFT_NARRATIVE_MODEL", "claude-haiku-4-5-20251001")


def load_env_key():
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("ANTHROPIC_API_KEY="):
                return line.split("=", 1)[1].strip()
    return os.environ.get("ANTHROPIC_API_KEY")


def prompt_index(run):
    return {p["prompt_id"]: p for p in run.get("prompts", [])}


def diff_runs(current, previous):
    """Return a list of structured change events between two runs."""
    if not previous:
        return None
    cur = prompt_index(current)
    prev = prompt_index(previous)
    drifting_threshold = current.get("rules", {}).get("divergence_formula", {}).get("drifting_threshold", 0.3)

    moved_into_drifting = []
    moved_out_of_drifting = []
    silence_changed = []
    biggest_score_jumps = []

    for pid, p_cur in cur.items():
        p_prev = prev.get(pid)
        if not p_prev:
            continue
        ds_cur = p_cur.get("divergence_score", 0)
        ds_prev = p_prev.get("divergence_score", 0)
        was_drifting = ds_prev >= drifting_threshold
        is_drifting = ds_cur >= drifting_threshold
        if is_drifting and not was_drifting:
            moved_into_drifting.append({"prompt_id": pid, "prompt_text": p_cur["prompt_text"], "score_now": ds_cur, "score_prev": ds_prev})
        elif was_drifting and not is_drifting:
            moved_out_of_drifting.append({"prompt_id": pid, "prompt_text": p_cur["prompt_text"], "score_now": ds_cur, "score_prev": ds_prev})
        if p_cur.get("silence_type") != p_prev.get("silence_type"):
            silence_changed.append({
                "prompt_id": pid,
                "prompt_text": p_cur["prompt_text"],
                "silence_now": p_cur.get("silence_type"),
                "silence_prev": p_prev.get("silence_type"),
            })
        biggest_score_jumps.append({"prompt_id": pid, "prompt_text": p_cur["prompt_text"], "delta": round(ds_cur - ds_prev, 3), "now": ds_cur, "prev": ds_prev})

    biggest_score_jumps.sort(key=lambda r: -abs(r["delta"]))
    return {
        "drifting_threshold": drifting_threshold,
        "moved_into_drifting": moved_into_drifting,
        "moved_out_of_drifting": moved_out_of_drifting,
        "silence_changed": silence_changed,
        "biggest_score_jumps": biggest_score_jumps[:10],
    }


def baseline_facts(current):
    s = current.get("summary", {})
    models = current.get("active_models", [])
    id_to_name = {m["id"]: m["name"] for m in models}
    top5 = []
    for p in current.get("prompts", [])[:5]:
        vis = p.get("visibility_by_model") or {}
        carriers = [(id_to_name.get(mid, mid), v) for mid, v in vis.items() if (v or 0) > 0]
        silent = [id_to_name.get(mid, mid) for mid, v in vis.items() if (v or 0) == 0]
        # Sort carriers by visibility desc so the lead engine reads first.
        carriers.sort(key=lambda r: -r[1])
        top5.append({
            "prompt_text": p["prompt_text"],
            "score": p["divergence_score"],
            "silence_type": p.get("silence_type"),
            "carriers": carriers,
            "silent_engines": silent,
        })
    return {
        "total_prompts": s.get("total_prompts", 0),
        "drifting_count": s.get("high_divergence_count", 0),
        "own_only_silence_count": s.get("own_only_silence_count", 0),
        "full_silence_count": s.get("full_silence_count", 0),
        "avg_own_visibility": s.get("avg_own_visibility", 0),
        "date_range": current.get("date_range", {}),
        "active_models": [m["name"] for m in models],
        "top_drifting_prompts": top5,
    }


def build_user_prompt(current, diff):
    facts = baseline_facts(current)
    if diff is None:
        return f"""You are writing the first weekly Drift Radar narrative for {current.get('project', 'this project')}. There is no previous run to compare against, so this is a baseline report.

Current state:
- Date range: {facts['date_range'].get('start')} → {facts['date_range'].get('end')}
- Active engines: {', '.join(facts['active_models'])}
- Total tracked prompts: {facts['total_prompts']}
- Drifting (≥ 0.30): {facts['drifting_count']}
- Own-only silence: {facts['own_only_silence_count']}
- Full silence: {facts['full_silence_count']}
- Average own-brand visibility: {round(facts['avg_own_visibility'] * 100, 1)}%
- Top 5 drifting prompts: {json.dumps(facts['top_drifting_prompts'], ensure_ascii=False)}

Write a short markdown report (≈ 250 words) that names the headline number, the two failure modes Drift Radar measures (drift + silence), and which prompts deserve attention this week. Do not invent numbers. Do not flatter. No triads. No »unlock / discover / dive into«. Plain reportage. End with a one-line forward look (»next week we will know whether X moved«). Use Halbgeviertstrich (–), not em-dash. Headings as H2 (##) for sections. Start with H1 (#) Drift Radar · {facts['date_range'].get('end', 'baseline')}."""

    return f"""You are writing the weekly Drift Radar narrative for {current.get('project', 'this project')}.

Current state:
- Date range: {facts['date_range'].get('start')} → {facts['date_range'].get('end')}
- Active engines: {', '.join(facts['active_models'])}
- Total tracked prompts: {facts['total_prompts']}
- Drifting (≥ {diff['drifting_threshold']}): {facts['drifting_count']}
- Own-only silence: {facts['own_only_silence_count']}
- Full silence: {facts['full_silence_count']}
- Average own-brand visibility: {round(facts['avg_own_visibility'] * 100, 1)}%

Diff vs previous run:
- {len(diff['moved_into_drifting'])} prompts moved INTO drifting range
- {len(diff['moved_out_of_drifting'])} prompts moved OUT of drifting range
- {len(diff['silence_changed'])} prompts changed silence-type
- Biggest score swings: {json.dumps(diff['biggest_score_jumps'][:5], ensure_ascii=False)}

Specifics:
- Moved into drifting: {json.dumps(diff['moved_into_drifting'][:6], ensure_ascii=False)}
- Moved out of drifting: {json.dumps(diff['moved_out_of_drifting'][:6], ensure_ascii=False)}
- Silence changes: {json.dumps(diff['silence_changed'][:6], ensure_ascii=False)}

Write a short markdown report (≈ 280 words) that names what changed, names the prompts that moved, and tells the operator where to look first this week. Do not invent numbers. Do not flatter. No triads. No »unlock / discover / dive into«. Plain reportage. End with a one-line forward look. Use Halbgeviertstrich (–), not em-dash. Headings as H2 (##). Start with H1 (#) Drift Radar · {facts['date_range'].get('end', 'this week')}."""


def call_claude(api_key, user_prompt, max_tokens=1100):
    body = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "system": "You are a marketing analytics writer. You write tight, factual reports in markdown. No fluff, no LLM clichés.",
        "messages": [{"role": "user", "content": user_prompt}],
    }
    data = json.dumps(body).encode("utf-8")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return payload["content"][0]["text"].strip()


def fallback_narrative(current, diff):
    """Deterministic markdown when no API key is available."""
    facts = baseline_facts(current)
    end_date = facts["date_range"].get("end", "baseline")
    lines = [
        f"# Drift Radar · {end_date}",
        "",
        f"Snapshot of {facts['total_prompts']} tracked prompts across {len(facts['active_models'])} engines: {', '.join(facts['active_models'])}.",
        "",
        "## Headline numbers",
        "",
        f"- Drifting (score ≥ 0.30): {facts['drifting_count']} prompts",
        f"- Own-only silence: {facts['own_only_silence_count']} prompts",
        f"- Full silence: {facts['full_silence_count']} prompts",
        f"- Average own-brand visibility: {round(facts['avg_own_visibility'] * 100, 1)} %",
        "",
    ]
    if diff is None:
        lines.extend([
            "## What this means",
            "",
            "First run – no previous snapshot to compare against. Next run will report movement.",
            "",
        ])
    else:
        lines.append("## Movement vs previous run")
        lines.append("")
        lines.append(f"- {len(diff['moved_into_drifting'])} prompts moved into drifting range")
        lines.append(f"- {len(diff['moved_out_of_drifting'])} prompts moved out of drifting range")
        lines.append(f"- {len(diff['silence_changed'])} prompts changed silence-type")
        lines.append("")
        if diff["moved_into_drifting"]:
            lines.append("### New drifting prompts")
            lines.append("")
            for p in diff["moved_into_drifting"][:6]:
                lines.append(f"- {p['score_prev']:.2f} → {p['score_now']:.2f}: »{p['prompt_text']}«")
            lines.append("")
        if diff["silence_changed"]:
            lines.append("### Silence shifts")
            lines.append("")
            for p in diff["silence_changed"][:6]:
                lines.append(f"- {p['silence_prev']} → {p['silence_now']}: »{p['prompt_text']}«")
            lines.append("")

    # Top-drifting list always present so the report is useful even when nothing moved.
    lines.append("## Top drifting prompts")
    lines.append("")
    for p in facts["top_drifting_prompts"]:
        carriers = p.get("carriers") or []
        silent = p.get("silent_engines") or []
        if carriers:
            lead_name, lead_vis = carriers[0]
            lead_pct = round(lead_vis * 100)
            if silent:
                hint = f"{lead_name} leads at {lead_pct} %, silent on {', '.join(silent)}"
            else:
                hint = f"{lead_name} leads at {lead_pct} %"
        elif silent:
            hint = f"silent on {', '.join(silent)}"
        else:
            hint = ""
        line = f"- {p['score']:.2f} – »{p['prompt_text']}«"
        if hint:
            line += f"  \n  _{hint}_"
        lines.append(line)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"*Generated: {datetime.utcnow().isoformat(timespec='seconds')}Z*")
    return "\n".join(lines)


def main():
    if not CURRENT.exists():
        raise FileNotFoundError(f"Run pipeline first: {CURRENT} missing")
    current = json.loads(CURRENT.read_text(encoding="utf-8"))
    previous = json.loads(PREVIOUS.read_text(encoding="utf-8")) if PREVIOUS.exists() else None
    diff = diff_runs(current, previous) if previous else None

    api_key = load_env_key()
    if api_key:
        try:
            narrative = call_claude(api_key, build_user_prompt(current, diff))
            print(f"narrative generated via Claude ({MODEL}), {len(narrative)} chars")
        except Exception as e:
            print(f"  WARN: API call failed ({e}); falling back to deterministic writer")
            narrative = fallback_narrative(current, diff)
    else:
        narrative = fallback_narrative(current, diff)
        print("no API key; deterministic writer used")

    end_date = current.get("date_range", {}).get("end", datetime.utcnow().date().isoformat())
    UI.mkdir(parents=True, exist_ok=True)
    NARRATIVE_LATEST.write_text(narrative, encoding="utf-8")
    print(f"wrote {NARRATIVE_LATEST}")

    DOWNLOADS.mkdir(parents=True, exist_ok=True)
    historical = DOWNLOADS / f"narrative_{end_date}.md"
    historical.write_text(narrative, encoding="utf-8")
    print(f"wrote {historical}")
    latest = DOWNLOADS / "narrative_latest.md"
    latest.write_text(narrative, encoding="utf-8")
    print(f"wrote {latest}")

    # Save current as baseline for next run
    PREVIOUS.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"saved {PREVIOUS} for next run's diff")


if __name__ == "__main__":
    main()
