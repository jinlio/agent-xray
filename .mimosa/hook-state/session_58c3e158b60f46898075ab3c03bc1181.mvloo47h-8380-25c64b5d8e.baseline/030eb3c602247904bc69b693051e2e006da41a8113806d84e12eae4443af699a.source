"""Token → USD cost estimation against a local, user-overridable price table.

Conventions follow ccusage: prices are USD per million tokens; cache reads are
billed at 0.1x the input price and cache writes at 1.25x. All numbers are
*estimates* — pass ``--price-file`` to override, or set a model's price to
``null`` to exclude it from cost math entirely.
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
]

_FALLBACK_PRICE = {"input": 1.0, "output": 3.0}


class PriceTable:
    def __init__(self, entries: list[dict[str, Any]]):
        self.entries = [(str(e["match"]).lower(), e) for e in entries]

    def lookup(self, model: str) -> dict[str, Any] | None:
        m = (model or "").lower()
        for prefix, entry in self.entries:
            if m.startswith(prefix):
                return entry
        return None


def load_price_table(path: str | Path | None = None) -> PriceTable:
    if path is None:
        return PriceTable(DEFAULT_PRICES)
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("models", data) if isinstance(data, dict) else data
    if not isinstance(entries, list):
        raise ValueError("price file must contain a list under 'models' (or be a list itself)")
    return PriceTable(entries)


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
        cache_read=usage.cache_read / MTOK * pin * CACHE_READ_FACTOR,
        cache_write=usage.cache_write / MTOK * pin * CACHE_WRITE_FACTOR,
    )
    cost.total = cost.input + cost.output + cost.cache_read + cost.cache_write
    return cost
