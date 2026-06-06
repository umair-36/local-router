from __future__ import annotations

from dataclasses import dataclass

from .catalog import ModelEntry


@dataclass(frozen=True)
class MemoryEstimate:
    load_gb: float
    kv_cache_gb: float
    overhead_gb: float

    @property
    def total_gb(self) -> float:
        return self.load_gb + self.kv_cache_gb + self.overhead_gb


def estimate_memory(model: ModelEntry, context_length: int, parallel: int = 1, overhead_ratio: float = 0.10) -> MemoryEstimate:
    """Return a deliberately rough local-serving memory estimate.

    Catalog load memory is sourced from model metadata. KV cache is an approximation
    when architecture-specific layer/hidden details are not present. It intentionally
    scales with context and parallelism so OpenCode profile estimates do not hide the
    major operational cost of long-running agent sessions.
    """
    load = model.memory_load_gb
    kv_per_8k_per_slot = max(load * 0.08, 0.25)
    kv = kv_per_8k_per_slot * (context_length / 8192) * parallel
    overhead = load * overhead_ratio
    return MemoryEstimate(load_gb=round(load, 2), kv_cache_gb=round(kv, 2), overhead_gb=round(overhead, 2))
