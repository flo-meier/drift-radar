# Drift Radar – Python Core

Computes cross-model visibility divergence and own-brand silence metrics from Peec MCP exports.

## Run

```
python3 run.py
```

Reads `data/raw/*.json`, writes `data/ui/drift_radar.json`, prints summary.

## Data sources

`data/raw/pferdegold_brand_report.json` — `get_brand_report` with dimensions=[prompt_id, model_id], filtered to own brand.
`data/raw/lookup_tables.json` — project meta, brand/model/topic/prompt lookup tables.

## No dependencies

Pure Python 3.8+. Wilson CI implemented inline.
