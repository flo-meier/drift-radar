"""Drift Radar – rule loader.

Every analytical parameter lives in a markdown file under `pipeline/rules/`.
This module parses the YAML frontmatter without an external dependency, so a
fresh clone has nothing to install beyond the existing requirements.

Usage:
    from rules import load_rule
    DIV = load_rule("divergence_formula")
    score = DIV["range_weight"] * range_vis + ...
"""
from pathlib import Path

RULES_DIR = Path(__file__).parent / "rules"


def _coerce(value: str):
    """Cast a YAML scalar to int / float / bool / str without external deps."""
    v = value.strip()
    if v.lower() in ("true", "yes"):
        return True
    if v.lower() in ("false", "no"):
        return False
    if v.lower() in ("null", "none", ""):
        return None
    # quoted string
    if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
        return v[1:-1]
    # numeric
    try:
        if "." in v or "e" in v.lower():
            return float(v)
        return int(v)
    except ValueError:
        return v


def _parse_frontmatter(text: str) -> dict:
    """Parse the YAML-ish frontmatter at the top of a markdown file.
    Supports flat scalars and one-level lists (`- item`). No nested dicts.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
    if end is None:
        return {}

    out: dict = {}
    pending_key = None
    pending_list: list = []
    for raw in lines[1:end]:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.startswith("  - ") or line.startswith("- "):
            # list item under most recent key
            item = line.lstrip(" -").strip()
            pending_list.append(_coerce(item))
            continue
        # flush pending list to its key
        if pending_key is not None and pending_list:
            out[pending_key] = pending_list
            pending_list = []
            pending_key = None
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        if val == "":
            # next lines should be a list
            pending_key = key
            pending_list = []
            out.setdefault(key, [])
        else:
            out[key] = _coerce(val)
    if pending_key is not None and pending_list:
        out[pending_key] = pending_list
    return out


def load_rule(name: str) -> dict:
    """Return the parsed frontmatter of `pipeline/rules/<name>.md` as a dict."""
    path = RULES_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Rule file not found: {path}")
    return _parse_frontmatter(path.read_text(encoding="utf-8"))


def load_rule_with_body(name: str) -> tuple[dict, str]:
    """Return (frontmatter_dict, markdown_body) for embedding methodology in outputs."""
    path = RULES_DIR / f"{name}.md"
    text = path.read_text(encoding="utf-8")
    fm = _parse_frontmatter(text)
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        body = "\n".join(lines[end + 1 :]).lstrip() if end is not None else text
    else:
        body = text
    return fm, body


if __name__ == "__main__":
    # Smoke-test: print every rule to confirm parsing
    for name in ("divergence_formula", "silence_classifier", "claim_extraction", "deep_dive_selection"):
        print(f"=== {name} ===")
        for k, v in load_rule(name).items():
            print(f"  {k}: {v!r}")
        print()
