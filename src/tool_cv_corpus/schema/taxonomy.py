"""Three-layer skill taxonomy.

Competence has layers, and flattening them into one bullet list hides the
structure recruiters and ATS systems both key off. We split into three:

- ``foundational``
    Languages, runtimes, and core CS primitives. Durable across jobs:
    Python, SQL, distributed systems, cryptography basics.

- ``applied``
    Frameworks, tools, methodologies built on the foundations. Changes
    with the industry: FastAPI, React, Kubernetes, TDD, gRPC.

- ``domain``
    Subject-matter expertise tied to an industry or problem class.
    Scarcely portable, very high signal: ad-tech attribution modeling,
    flight telemetry, medical imaging pipelines, payment fraud.

A single skill may legitimately sit in more than one layer over a career
(e.g., "React" starts ``applied`` and becomes ``foundational`` for a
frontend specialist). That is encoded per-person, not in a shared
ontology, so callers are free to re-tier as their narrative changes.
"""

from __future__ import annotations

from typing import Literal

SkillTier = Literal["foundational", "applied", "domain"]

SkillConfidence = Literal["beginner", "working", "proficient", "expert"]
"""Self-rated competence level.

Kept coarse deliberately: finer grades invite dishonesty on one side and
false modesty on the other. Four buckets are the most ATS systems use in
practice.
"""
