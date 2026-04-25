---
top_n_full_deep_dives: 5
sort_key: divergence_score
require_chat_sample: true
fallback_strategy: highest_divergence
---

# Deep-dive selection

Drift Radar promotes the top `top_n_full_deep_dives` prompts to full deep-dive treatment on the dashboard — three-engine response columns, narrative claim matrix, source-mix block, gap URLs.

## Selection rule

1. Sort all prompts by `sort_key` descending (default `divergence_score`).
2. Filter by `require_chat_sample = true` — a deep dive needs an actual chat transcript to render the response columns. A prompt without a captured sample falls through to the compact list.
3. Take the first `top_n_full_deep_dives` that pass.
4. Promote the rest of the drifting set into the collapsible »remaining drifting prompts« group.

## Why top-5

Five is the upper bound a content team can absorb in one weekly cycle and still ship briefs. Six and up is psychologically a backlog; four and down is too thin to argue divergence as a systemic pattern.

The remaining drifting prompts stay one click away in the mini-group, so nothing is lost — the cap is on attention, not on data.

## Tuning

To run lighter weeks (4 deep dives + the rest in mini-groups), drop `top_n_full_deep_dives` to `4`. To re-rank by silence priority instead of pure divergence, change `sort_key` to `silence_priority` (own-only first, full second, drifting third) and the pipeline will sort accordingly — that path is wired in the selection helper.
