"""Structured impact metrics.

Prose like "increased revenue by 20%" is hostile to a generator: it cannot
rephrase, re-unit, or bound-check without parsing the sentence back. We keep
the numbers structured and let renderers format them.

``direction`` is kept separate from ``delta_pct`` so a negative direction
with a positive magnitude ("reduced error rate by 30%") remains
unambiguous and renderers can phrase it as a win or a loss as appropriate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Direction = Literal["increase", "decrease", "neutral"]


class ImpactMetric(BaseModel):
    """One numeric outcome, optionally relative to a baseline."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(
        ...,
        min_length=1,
        description="Short label, e.g. 'ARR', 'p99 latency', 'weekly actives'.",
    )
    value: float | None = Field(
        default=None,
        description="Absolute value after the change; units below.",
    )
    unit: str | None = Field(
        default=None,
        description="Free-form unit, e.g. 'USD', 'ms', 'users'.",
    )
    delta_pct: float | None = Field(
        default=None,
        description="Percent change vs baseline; positive magnitude only.",
    )
    baseline: float | None = Field(
        default=None,
        description="Value before the change; same unit as ``value``.",
    )
    direction: Direction | None = Field(
        default=None,
        description=(
            "Separate from delta_pct so 'reduced X by 30%' stays unambiguous."
        ),
    )
    timeframe: str | None = Field(
        default=None,
        description="Window over which the change was measured, e.g. 'Q2 2023'.",
    )
