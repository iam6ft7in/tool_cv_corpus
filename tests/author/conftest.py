"""Pytest configuration for tests/author.

Same workaround as ``tests/ingest/conftest.py``: the schema's
``Testimonial`` class starts with ``Test`` and pytest tries to collect
it as a test class on import. Setting ``__test__`` here keeps the
schema module free of test-runner plumbing.
"""

from __future__ import annotations

from tool_cv_corpus.schema import Testimonial

Testimonial.__test__ = False  # type: ignore[attr-defined]
