---
range_weight: 0.7
cv_weight: 0.3
cv_cap: 2.0
drifting_threshold: 0.3
two_versions_threshold: 0.5
non_overlapping_threshold: 0.8
---

# Divergence formula

`divergence_score = range_weight × range(visibility) + cv_weight × min(cv(visibility), cv_cap) / cv_cap`

Where `range = max(visibility) − min(visibility)` and `cv = pstdev / mean` of own-brand visibility across active engines for one prompt.

## Why this shape

Range is bounded `[0, 1]` and intuitively reads as »how far apart are the engines«. It dominates with `0.7` weight because it is the metric a stakeholder can hold in their head.

CV is unbounded but catches the long tail where all engines have non-zero coverage but disagree by ratio (e.g. 5 % / 10 % / 30 %). It contributes `0.3` weight, capped at `cv_cap` to keep the score in `[0, 1]`.

Capping CV at 2.0 is the conservative cut: above CV = 2.0 the prompt is already extreme on the range axis, so the CV addition saturates rather than blowing the score past 1.

## Reading thresholds

- `score >= 0.30` — narrative is drifting (`drifting_threshold`)
- `score >= 0.50` — two versions of the brand compete (`two_versions_threshold`)
- `score >= 0.80` — three non-overlapping answers (`non_overlapping_threshold`)

These thresholds drive the badge text on each deep-dive header and the colour ramp on the heatmap.

## Tuning per project

To raise the alert threshold for projects with very low overall visibility, lift `drifting_threshold` to `0.4`. To favour CV over range (e.g. for B2B brands where ratios matter more than raw points), invert to `range_weight: 0.3 / cv_weight: 0.7`.

The pipeline reads this file at startup. No Python edits needed.
