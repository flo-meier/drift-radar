#!/usr/bin/env python3
"""Claim Extraction – runs Claude over every assistant response in chat_samples.json
(and any additional chat dumps under data/raw/chats/) and writes structured
top-5 claims per chat to data/raw/claims.json.

No SDK dependency — pure stdlib + urllib so it survives any Python 3.9+ env.
Model defaults to haiku 4.5 for cost; override with DRIFT_MODEL env var.
"""
import json
import os
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
CLAIMS_OUT = RAW / "claims.json"
CHATS_DIR = RAW / "chats"

MODEL = os.environ.get("DRIFT_MODEL", "claude-haiku-4-5-20251001")
API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
MAX_CLAIMS = 5
REQUEST_INTERVAL = 0.35  # seconds between calls, well inside tier-1 limits


def load_env_key():
    env_file = ROOT / ".env"
    if not env_file.exists():
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(f"No ANTHROPIC_API_KEY found in env or {env_file}")
        return key
    for line in env_file.read_text().splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError(f"{env_file} found but has no ANTHROPIC_API_KEY= line")


SYSTEM = (
    "You extract structured claims from AI-generated product recommendations. "
    "Return ONLY valid JSON, no prose, no markdown fencing. Never include ```json."
)


def build_prompt(query: str, response_text: str) -> str:
    return f"""User query to an AI search engine:
{query!r}

The AI engine responded with:
\"\"\"{response_text}\"\"\"

Extract up to {MAX_CLAIMS} atomic claims this response makes. For each claim, categorize:
- "brand"       : mentions a specific product or brand by name
- "substance"   : mentions an active ingredient or material (e.g. Glucosamin, MSM)
- "function"    : a functional benefit the response asserts (e.g. supports joints)
- "condition"   : a health condition or use case (e.g. arthrose)
- "criterion"   : a quality or selection criterion (e.g. sugar-free, natural)

Return a JSON array with up to {MAX_CLAIMS} objects, each:
{{
  "text": "claim in ≤10 words",
  "type": "brand|substance|function|condition|criterion",
  "evidence": "short verbatim quote ≤20 words"
}}

Prioritize brand claims first when present, then substance, then the rest.
Return the JSON array and nothing else."""


def call_claude(api_key: str, query: str, response_text: str, retries: int = 3) -> list:
    body = {
        "model": MODEL,
        "max_tokens": 800,
        "system": SYSTEM,
        "messages": [{"role": "user", "content": build_prompt(query, response_text)}],
    }
    data = json.dumps(body).encode("utf-8")
    headers = {
        "x-api-key": api_key,
        "anthropic-version": API_VERSION,
        "content-type": "application/json",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(API_URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=60) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            text = payload["content"][0]["text"].strip()
            # Strip accidental fencing if model misbehaves
            if text.startswith("```"):
                text = text.strip("`")
                if text.startswith("json"):
                    text = text[4:]
                text = text.strip()
            return json.loads(text)
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            if e.code in (429, 503, 529) and attempt < retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  retry {attempt+1}/{retries} after {wait}s (HTTP {e.code})")
                time.sleep(wait)
                continue
            raise RuntimeError(f"Anthropic API {e.code}: {body_text}") from e
        except (urllib.error.URLError, json.JSONDecodeError) as e:
            if attempt < retries - 1:
                time.sleep(2)
                continue
            raise RuntimeError(f"Call failed after {retries} retries: {e}") from e
    return []


def chat_records():
    """Yield (chat_id, prompt_id, model_id, query, response_text) from available sources."""
    # 1. chat_samples.json (hand-picked deep-dive chats)
    samples_path = RAW / "chat_samples.json"
    if samples_path.exists():
        data = json.loads(samples_path.read_text(encoding="utf-8"))
        for sample in data["samples"]:
            query = sample["prompt_text"]
            for model_id, by in sample["by_model"].items():
                chat_id = by.get("chat_id")
                excerpt = by.get("response_excerpt")
                if chat_id and excerpt:
                    yield chat_id, sample["prompt_id"], model_id, query, excerpt

    # 2. Any per-chat dumps dropped under data/raw/chats/*.json
    # Each file expected to look like: { "id", "messages": [...], "prompt": {"id"}, "model": {"id"} }
    if CHATS_DIR.exists():
        for path in sorted(CHATS_DIR.glob("*.json")):
            chat = json.loads(path.read_text(encoding="utf-8"))
            msgs = chat.get("messages", [])
            user_msg = next((m for m in msgs if m.get("role") == "user"), None)
            asst_msg = next((m for m in msgs if m.get("role") == "assistant"), None)
            if user_msg and asst_msg:
                yield (
                    chat.get("id"),
                    chat.get("prompt", {}).get("id"),
                    chat.get("model", {}).get("id"),
                    user_msg.get("content", ""),
                    asst_msg.get("content", ""),
                )


def main():
    api_key = load_env_key()

    cache = {}
    if CLAIMS_OUT.exists():
        cache = json.loads(CLAIMS_OUT.read_text(encoding="utf-8")).get("by_chat_id", {})
        print(f"Loaded {len(cache)} cached claims")

    records = list(chat_records())
    print(f"Found {len(records)} chats to process")

    processed = 0
    failed = 0
    for chat_id, prompt_id, model_id, query, response_text in records:
        if not chat_id:
            continue
        if chat_id in cache:
            continue
        if not response_text or len(response_text.strip()) < 30:
            continue

        print(f"  [{processed+1}] {model_id}  {chat_id}")
        try:
            claims = call_claude(api_key, query, response_text)
            if not isinstance(claims, list):
                raise ValueError(f"Expected list, got {type(claims).__name__}")
            cache[chat_id] = {
                "prompt_id": prompt_id,
                "model_id": model_id,
                "claims": claims[:MAX_CLAIMS],
            }
            processed += 1
            time.sleep(REQUEST_INTERVAL)
        except Exception as e:
            print(f"    FAILED: {e}")
            failed += 1
            if failed >= 5:
                print("Too many consecutive failures — aborting run.")
                break

        # persist after every chat so nothing is lost on interrupt
        CLAIMS_OUT.write_text(
            json.dumps(
                {"model": MODEL, "by_chat_id": cache},
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    print(f"\nDone. Processed {processed} new, {failed} failed, {len(cache)} total cached.")
    print(f"Output: {CLAIMS_OUT}")


if __name__ == "__main__":
    main()
