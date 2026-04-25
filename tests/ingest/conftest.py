"""Pytest configuration for tests/ingest.

The schema's ``Testimonial`` entity matches pytest's default heuristic for
test classes (name starts with ``Test``), so importing it into a test
module triggers a ``PytestCollectionWarning`` even though it is plainly a
domain class. The documented escape hatch is the ``__test__`` attribute,
set here at collection time so the schema module stays free of test-only
plumbing.
"""

from __future__ import annotations

from tool_cv_corpus.schema import Testimonial

Testimonial.__test__ = False  # type: ignore[attr-defined]
