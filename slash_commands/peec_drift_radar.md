---
name: peec_drift_radar
description: Find the prompts where ChatGPT, Gemini and AI Overview describe the same brand – differently – and the prompts where they stay brand-silent entirely. Prompt-level complement to /peec_engine_scorecard.
author: Drift Radar · Peec AI MCP Challenge 2026
version: 0.1
---

# peec_drift_radar

Peec-native slash-command spec for the Drift Radar workflow. Ships the prompt-level divergence + brand-silence report that the Drift Radar frontend renders weekly.

## Inputs

| Argument | Required | Default | Notes |
|---|---|---|---|
| `brand` | yes | – | Peec brand name or brand-ID (e.g. `Pferdegold`, `br_…`) |
| `date_range` | no | last 7 days | Absolute (`2026-04-20:2026-04-22`) or relative (`7d`, `30d`) |
| `min_chats_per_cell` | no | `3` | Minimum `visibility_total` per prompt × model before a divergence score is computed |
| `divergence_threshold` | no | `0.30` | Prompts at or above this score are flagged `drifting` |
| `output` | no | `report` | `report` · `slack` · `notion` · `briefs` |

## Peec MCP calls (sequential)

1. `list_projects` → resolve workspace (cache).
2. `list_prompts` → all prompts tracked for the project.
3. `list_tags` → topic + branded/non-branded dimensions.
4. `get_brand_report` with `dimensions=[prompt_id, model_id]`, `is_own=true` → own-brand per-prompt per-model visibility + `visibility_count` + `visibility_total`.
5. `get_brand_report` with `dimensions=[prompt_id, model_id]` (no `is_own`) → competitor matrix for silence classification.
6. `get_domain_report` with `gap=true` → URLs where competitors are cited but the brand is not.
7. `list_chats` per high-divergence prompt × model → one representative chat per cell.
8. `get_chat` → full `messages` for the chosen samples (drives the narrative-claims extract).
9. `list_search_queries` + `list_shopping_queries` → search-intent context per prompt.

## Metrics computed client-side

- **Divergence score** per prompt: `0.7 × range(visibility) + 0.3 × min(CV, 2.0) / 2.0`
- **Silence type**: `active` (own ≥ 1 model) · `own_only` (all own = 0, ≥ 1 competitor) · `full` (own = 0, all competitors = 0)
- **Wilson 95 % CI** per prompt × model, using `visibility_count / visibility_total`
- **Top competitors** per own-only-silence prompt, by `max_visibility` across active models

## Output formats

- `report` → Notion page »{Brand} · Drift Radar · {date}« with heatmap, ranked drifting prompts, silence tables, content-brief library links
- `slack` → channel post: »⚠ Drift Radar · {Brand}: {N} drifting prompts, {M} own-only silences, divergence peak {x}. Top action: {prompt}«
- `notion` → same as `report` but pushed to a specified database
- `briefs` → one Markdown content brief per drifting prompt, saved to the provided Notion database or a Google Drive folder

## Cadence

- **Default**: weekly cron (Sunday 02:00 UTC) via GitHub Action – see `.github/workflows/drift-radar-weekly.yml`
- **On-demand**: `/peec_drift_radar brand="Pferdegold" date_range=3d output=slack`
- **Campaign window**: `/peec_drift_radar brand="X" date_range=2026-04-01:2026-04-22` mirrors the `campaign-shift` use-case

## Why it lives next to `/peec_engine_scorecard`

| | `/peec_engine_scorecard` | `/peec_drift_radar` |
|---|---|---|
| Granularity | brand-aggregate, one score per model | prompt-level, N = tracked prompts |
| Core question | which model is weak for me? | which prompts destroy my narrative? |
| Diagnostic | source / domain preferences | narrative divergence + silence type |
| Output | 3–5 source-strategy recommendations | N prompt-level content briefs + Wilson-CI heatmap |
| Action field | digital PR / domain authority | content / narrative strategy |

Two instruments on the same problem, different altitudes. A team running both gets »fix ChatGPT's source set« *and* »ship these 17 briefs to close the narrative gaps«.

## Shipping this as a Peec-native command

- `peec_drift_radar` slug follows the `/peec_campaign_tracker` / `/peec_engine_scorecard` convention.
- Pure MCP read-calls – no write-back to Peec.
- Computation is stateless and deterministic, so caching is trivial at Peec side.
- Frontend reference implementation: [drift-radar.pages.dev](https://drift-radar.pages.dev).

— Drift Radar · #BuiltWithPeec
