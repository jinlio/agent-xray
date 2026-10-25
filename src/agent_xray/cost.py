"""Token → USD cost estimation against a local, user-overridable price table.

Conventions follow ccusage: prices are USD per million tokens; cache reads are
billed at 0.1x the input price and cache writes at 1.25x (both factors are
configurable). All numbers are *estimates*.

Price resolution order (first match wins per model, case-insensitive prefix):
1. entries from ``--price-file`` (or the auto-loaded ``~/.agent-xray/prices.json``),
2. built-in DEFAULT_PRICES — unless the file sets ``"replace_defaults": true``.

File format (the ``models`` list may also be the top level alone):

    {
      "cache_read_factor": 0.1,
      "cache_write_factor": 1.25,
      "replace_defaults": false,
      "models": [
        {"match": "gpt-5.6-terra", "input": 2.5, "output": 10.0},
        {"match": "internal-model", "input": null, "output": null}
      ]
    }

``input``/``output`` are USD per million tokens; ``null`` excludes a model from
cost math entirely. Run ``agent-xray --dump-prices`` to export the currently
effective table as a starting point.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import Usage

MTOK = 1_000_000.0
CACHE_READ_FACTOR = 0.1
CACHE_WRITE_FACTOR = 1.25

DEFAULT_PRICES: list[dict[str, Any]] = [
    # "match" is matched case-insensitively as a prefix of the model id
    {"match": "glm-5.3-flash", "input": 0.2, "output": 1.1},
    {"match": "glm-5.3", "input": 0.6, "output": 2.2},
    {"match": "glm-4", "input": 0.6, "output": 2.2},
    {"match": "qwen3.8-flash", "input": 0.05, "output": 0.4},
    {"match": "qwen", "input": 0.3, "output": 1.2},
    {"match": "minimax-m3.1", "input": 0.3, "output": 1.2},
    {"match": "minimax", "input": 0.5, "output": 2.0},
    {"match": "deepseek-v4.1", "input": 0.3, "output": 1.2},
    {"match": "deepseek", "input": 0.5, "output": 2.0},
    {"match": "mimo-v2.6-pro", "input": 0.6, "output": 2.4},
    {"match": "mimo", "input": 0.2, "output": 1.0},
    {"match": "claude-opus", "input": 15.0, "output": 75.0},
    {"match": "claude-sonnet", "input": 3.0, "output": 15.0},
    {"match": "claude-haiku", "input": 1.0, "output": 5.0},
    {"match": "claude", "input": 3.0, "output": 15.0},
    {"match": "gpt-6", "input": 2.5, "output": 10.0},
    {"match": "gpt-5", "input": 2.5, "output": 10.0},
    {"match": "gpt", "input": 2.0, "output": 8.0},
    # codex-auto-review & other internal Codex models have no public pricing
    {"match": "codex", "input": None, "output": None},
]

_FALLBACK_PRICE = {"input": 1.0, "output": 3.0}


def user_price_path() -> Path:
    """Auto-loaded user price file (no --price-file needed once it exists)."""
    return Path.home() / ".agent-xray" / "prices.json"


class PriceTable:
    def __init__(
        self,
        entries: list[dict[str, Any]],
        cache_read_factor: float = CACHE_READ_FACTOR,
        cache_write_factor: float = CACHE_WRITE_FACTOR,
    ):
        self.entries = [(str(e["match"]).lower(), e) for e in entries]
        self.cache_read_factor = float(cache_read_factor)
        self.cache_write_factor = float(cache_write_factor)

    def lookup(self, model: str) -> dict[str, Any] | None:
        m = (model or "").lower()
        for prefix, entry in self.entries:
            if m.startswith(prefix):
                return entry
        return None

    def as_file(self) -> dict[str, Any]:
        """The effective table serialized back into price-file form."""
        return {
            "cache_read_factor": self.cache_read_factor,
            "cache_write_factor": self.cache_write_factor,
            "models": [dict(e) for _, e in self.entries],
        }


def _parse_price_file(data: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """→ (entries, {cache_read_factor?, cache_write_factor?, replace_defaults?})."""
    opts: dict[str, Any] = {}
    if isinstance(data, dict):
        entries = data.get("models", [])
        for key in ("cache_read_factor", "cache_write_factor", "replace_defaults"):
            if key in data:
                opts[key] = data[key]
    else:
        entries = data
    if not isinstance(entries, list) or not all(isinstance(e, dict) and "match" in e for e in entries):
        raise ValueError("price file must contain model entries under 'models' (or be a list itself)")
    return entries, opts


def load_price_table(path: str | Path | None = None) -> PriceTable:
    """Built-in prices overlaid by a user file: explicit --price-file wins,
    else ~/.agent-xray/prices.json is picked up automatically when present."""
    if path is None:
        auto = user_price_path()
        if not auto.exists():
            return PriceTable(DEFAULT_PRICES)
        path = auto
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except ValueError as e:
        raise ValueError(f"invalid price file {path}: {e}") from e
    entries, opts = _parse_price_file(data)
    base = [] if opts.get("replace_defaults") else DEFAULT_PRICES
    try:
        cr = float(opts.get("cache_read_factor", CACHE_READ_FACTOR))
        cw = float(opts.get("cache_write_factor", CACHE_WRITE_FACTOR))
    except (TypeError, ValueError) as e:
        raise ValueError(f"invalid price file {path}: cache factors must be numbers") from e
    return PriceTable(entries + base, cache_read_factor=cr, cache_write_factor=cw)


def estimate_cost(table: PriceTable, model: str, usage: Usage) -> Any:
    from .model import Cost  # local import to avoid cycle

    entry = table.lookup(model) or _FALLBACK_PRICE
    if entry.get("input") is None or entry.get("output") is None:
        return None  # model explicitly unpriced
    pin = float(entry["input"])
    pout = float(entry["output"])
    cost = Cost(
        input=usage.input / MTOK * pin,
        output=usage.output / MTOK * pout,
        cache_read=usage.cache_read / MTOK * pin * table.cache_read_factor,
        cache_write=usage.cache_write / MTOK * pin * table.cache_write_factor,
    )
    cost.total = cost.input + cost.output + cost.cache_read + cost.cache_write
    return cost
