---
model: claude-haiku-4-5-20251001
max_claims_per_chat: 5
request_interval_seconds: 0.35
max_retries: 3
claim_types:
  - brand
  - substance
  - function
  - condition
  - criterion
priority_order:
  - brand
  - substance
  - function
  - condition
  - criterion
---

# Claim extraction

Every assistant response on a deep-dive prompt is passed to Claude Haiku 4.5 with a single instruction: extract at most `max_claims_per_chat` atomic claims, classified by type.

## System prompt

> You extract structured claims from AI-generated product recommendations. Return ONLY valid JSON, no prose, no markdown fencing. Never include ```json.

## User prompt template

```
User query to an AI search engine:
{query}

The AI engine responded with:
"""{response_text}"""

Extract up to {max_claims_per_chat} atomic claims this response makes. For each claim, categorize:
- "brand"       : mentions a specific product or brand by name
- "substance"   : mentions an active ingredient or material (e.g. Glucosamin, MSM)
- "function"    : a functional benefit the response asserts (e.g. supports joints)
- "condition"   : a health condition or use case (e.g. arthrose)
- "criterion"   : a quality or selection criterion (e.g. sugar-free, natural)

Return a JSON array with up to {max_claims_per_chat} objects, each:
{
  "text": "claim in ≤10 words",
  "type": "brand|substance|function|condition|criterion",
  "evidence": "short verbatim quote ≤20 words"
}

Prioritize brand claims first when present, then substance, then the rest.
Return the JSON array and nothing else.
```

## Why these claim types

The five categories cover the failure modes Drift Radar measures:

- `brand` reveals which competitor surfaced when the own brand was silent
- `substance` reveals which active ingredients the engines treat as canonical (cross-engine substance overlap = stable narrative)
- `function` and `condition` reveal whether the engines agree on *what* the product does
- `criterion` reveals which quality cues the engines use to rank brands

The cross-engine narrative-stability summary (`shared_substances`, `shared_criteria`) groups claims that surface in 2+ engines — those are the content anchors a brief can build on.

## Tuning

To extract more claims per chat (richer narrative-mix bars at the cost of API spend), lift `max_claims_per_chat`. To use a different model, change `model` — the pipeline reads this file at startup.
