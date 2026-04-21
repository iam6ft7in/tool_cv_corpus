"""Partial-date and date-range primitives.

Career data is almost never known to day precision: a role's "start" is a
month, a publication is a year, an achievement may be "Q2 2023". Forcing
``datetime.date`` would push authors into fabricating precision they do not
have. We accept YYYY, YYYY-MM, or YYYY-MM-DD and carry the string through
losslessly. Renderers format as they see fit.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator

_PARTIAL_DATE_RE = re.compile(r"^\d{4}(-(0[1-9]|1[0-2])(-(0[1-9]|[12]\d|3[01]))?)?$")


def _check_partial_date(value: str) -> str:
    if not _PARTIAL_DATE_RE.match(value):
        raise ValueError(f"expected YYYY, YYYY-MM, or YYYY-MM-DD; got {value!r}")
    # For full dates, verify the calendar rejects impossible days
    # (e.g. 2021-02-30, 2024-04-31) that the regex cannot catch.
    if len(value) == 10:
        y, m, d = value.split("-")
        try:
            date(int(y), int(m), int(d))
        except ValueError as exc:
            raise ValueError(f"invalid calendar date {value!r}: {exc}") from exc
    return value


PartialDate = Annotated[str, AfterValidator(_check_partial_date)]
"""A string constrained to YYYY, YYYY-MM, or YYYY-MM-DD.

Using ``Annotated[str, ...]`` rather than a wrapper model keeps YAML
round-trips trivial: the value on disk is the value in memory.
"""


class DateRange(BaseModel):
    """Half-open career date range; ``end is None`` means ongoing.

    We compare only when both ends share at least year granularity; the
    validator rejects ``end < start`` to catch copy-paste errors early, but
    mixed granularities (e.g., start="2021-03", end="2023") are permitted and
    compared on the common prefix.
    """

    model_config = ConfigDict(extra="forbid")

    start: PartialDate
    end: PartialDate | None = Field(
        default=None,
        description="Omit or set to null for ongoing engagements.",
    )

    @model_validator(mode="after")
    def _end_not_before_start(self) -> DateRange:
        if self.end is None:
            return self
        common = min(len(self.start), len(self.end))
        if self.end[:common] < self.start[:common]:
            raise ValueError(f"end ({self.end}) precedes start ({self.start})")
        return self
