---
own_silence_visibility_max: 0.0
top_competitors_per_prompt: 5
wilson_ci_z: 1.96
min_chats_per_cell: 3
---

# Silence classifier

A prompt is silent for the own brand when the maximum visibility across all active engines is at most `own_silence_visibility_max` (default `0.0` — true zero across the board).

Silent prompts are then split into two failure modes:

- `full` silence — no tracked brand is mentioned by any engine. The category is being answered generically. Low-hanging content fruit: nobody owns the answer.
- `own_only` silence — at least one tracked competitor is cited. The brand is the only silent player. Highest content priority: the engine has decided the answer, and it is not us.

Active prompts (`silence_type = None`) drive the divergence axis. Silent prompts drive the brand-risk axis.

## Top-competitors cap

For each `own_only` prompt the classifier returns up to `top_competitors_per_prompt` brands sorted by max visibility across the active engines. Five is the largest list a deep-dive layout reads cleanly — raise it for connector exports, lower it for tightly limited UIs.

## Wilson 95 % CI parameters

Every visibility cell carries a Wilson score interval computed from raw `visibility_count / visibility_total` (chats with brand mention / total chats sampled).

- `wilson_ci_z = 1.96` — z-score for 95 % confidence. Lift to `2.576` for 99 %, drop to `1.645` for 90 %.
- `min_chats_per_cell = 3` — Peec runs 3 chats per engine per day on the Pro plan. Below 3 the CI is too wide to be informative; the UI labels these cells as »insufficient sample«.

## Why these defaults

The visibility-zero rule is intentionally strict: a prompt where one engine surfaces the brand at 0.5 visibility and the other two are silent is *drifting*, not *silent*. Treating that as silent would smear two failure modes into one.

The 95 % CI is industry-standard. The `N = 3` floor matches Peec's Pro-plan sampling rhythm and is the smallest sample where a Wilson interval is still meaningful (with `N = 1`, the CI is `[0, 0.79]` — useless).
