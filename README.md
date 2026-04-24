# Drift Radar

> Cross-model divergence + brand-silence radar. Built on Peec AI MCP. #BuiltWithPeec

Drift Radar finds the prompts where ChatGPT, Gemini and AI Overview describe the same brand *differently* – and the prompts where they stay brand-silent entirely. Both are brand risks, and both are invisible to classic visibility metrics.

Live report: **[drift-radar.pages.dev](https://drift-radar.pages.dev)**

Submission for the [Peec AI MCP Challenge 2026](https://peec.ai) · Content Optimization category.

---

## What it is

Three outputs, one weekly workflow:

1. **Divergence heatmap** – 50 prompts × 3 engines, scored by range + coefficient of variation of own-brand visibility. Prompts with divergence ≥ 0.30 are flagged `drifting`.
2. **Brand-silence split** – `own_only` (competitors cited, you absent) vs `full` (category silent, first-mover real estate).
3. **Content-brief library** – one structured Markdown/PDF brief per drifting prompt, with Wilson-95 % CIs, narrative claim matrix, gap-URL excerpts and search-intent context.

## How it runs

- **Scheduled**: `.github/workflows/drift-radar-weekly.yml` – Sunday 02:00 UTC. Pulls fresh data via the Peec REST API, recomputes metrics, rebuilds the site, commits. Cloudflare Pages auto-deploys.
- **On-demand**: `gh workflow run drift-radar-weekly.yml` or the »Re-run« button on the site.
- **Peec-native prompt**: [`slash_commands/peec_drift_radar.md`](slash_commands/peec_drift_radar.md) – ready to ship as a Peec slash-command alongside `/peec_engine_scorecard` and `/peec_campaign_tracker`.

## Repository layout

```
├── src/                       Astro site (the report UI)
├── public/                    Static assets incl. /downloads/*.csv, *.xlsx, *.pdf, *.rss
├── pipeline/
│   ├── fetch_peec.py          Peec REST API pull (skips cleanly if no API key)
│   ├── run.py                 Metrics + Wilson CIs + silence classification
│   ├── extract_claims.py      Claude Haiku narrative-claim extraction (optional)
│   ├── export_downloads.py    CSV / XLSX / PDF briefs / RSS exports
│   ├── sync_to_app.py         Copy JSON outputs into src/data/ for the build
│   ├── data/raw/              Cached Peec API responses (seed set committed)
│   └── data/ui/               drift_radar.json consumed by src/pages/index.astro
├── slash_commands/
│   └── peec_drift_radar.md    Peec-native slash-command spec
└── .github/workflows/
    └── drift-radar-weekly.yml Weekly refresh + deploy
```

## Local development

```bash
# Site
npm install
npm run dev            # localhost:4321

# Pipeline
cd pipeline
pip install -r requirements.txt
python run.py          # rebuild metrics from cached raw/
python sync_to_app.py  # copy outputs into ../src/data/
```

## Secrets

GitHub repo → Settings → Secrets and variables → Actions:

| Name | Needed for | Required |
|---|---|---|
| `PEEC_API_KEY` | Live Peec API pull (Enterprise, beta) | optional – without it the action falls back to the cached `pipeline/data/raw/*.json` |
| `PEEC_PROJECT_ID` | Scope the pull to one Peec project | optional, has a default for the Pferdegold case |
| `ANTHROPIC_API_KEY` | Narrative-claim extraction via Claude Haiku | optional |

No Cloudflare secrets required – deployment uses Cloudflare Pages' GitHub integration.

## Methodology

- **Divergence** = `0.7 × range(visibility) + 0.3 × min(CV, 2.0) / 2.0` across the active engines, per prompt.
- **Wilson 95 % CI** on raw `visibility_count / visibility_total` per prompt × model – makes N = 3 chats honest.
- **Silence split** from all-brands report: distinguishes own-only silence from category-wide silence so content teams can triage.
- Reference: Ethan Smith, »Demystifying Randomness in AI Search« (graphite.io).

## License

MIT. The Peec MCP Challenge IP-clause grants Peec a royalty-free worldwide licence to use the work.

---

Maintainer: Florian Meier · Challenge submission, April 2026 · #BuiltWithPeec
