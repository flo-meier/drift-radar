# Drift Radar · Rules

Every analytical decision Drift Radar makes lives in this folder, not in Python.

Each `.md` file has a YAML frontmatter block (parameters the pipeline reads) and a markdown body (the methodology, version-controlled in the same file). The pipeline loads the frontmatter at startup. To tune the tool for a new project, edit the markdown — no code change.

## Files

- [`divergence_formula.md`](divergence_formula.md) — drift-score weighting and the three reading thresholds
- [`silence_classifier.md`](silence_classifier.md) — own-only vs full silence, Wilson-CI parameters, top-competitors cap
- [`claim_extraction.md`](claim_extraction.md) — Haiku 4.5 prompt + claim types + per-chat caps
- [`deep_dive_selection.md`](deep_dive_selection.md) — how the top deep dives are picked

## How it works

`rules.py` provides one function: `load_rule(name)` returns the parsed frontmatter dict for a given rule file. The four pipeline scripts call it on startup:

```python
from rules import load_rule
DIV = load_rule("divergence_formula")
score = DIV["range_weight"] * range_vis + DIV["cv_weight"] * min(cv_vis, DIV["cv_cap"]) / DIV["cv_cap"]
```

Methodology drift is git-trackable: a PR that changes a weighting also changes the markdown explaining why, in the same diff. Single source of truth for behaviour and documentation.

## Per-project tuning

Fork the repo, change one file, redeploy. The CI re-runs the pipeline against the new parameters and the dashboard reflects the new scores on the next deploy. No formula touches the rest of the pipeline.
