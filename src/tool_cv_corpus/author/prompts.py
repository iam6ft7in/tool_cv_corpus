"""Schema-driven prompts that build entities and claims from user input.

Design constraints:

1. **Pydantic introspection drives the form**. Every prompt label,
   help text, default, and required/optional flag comes from the model
   field, so adding a new field to a schema entity automatically
   surfaces in the wizard with no code change here.

2. **Prompter is a Protocol, not a concrete class**. The CLI passes a
   Rich-backed prompter; tests pass a ``ScriptedPrompter`` whose
   responses are a queue. The wizard never imports ``rich`` or
   ``typer``, so the engine is testable end-to-end without a TTY.

3. **Foreign-key fields are explicit, not inferred**. Field-name
   heuristics ("ends with ``_id``") would mis-fire on free-form
   identifier strings, so we declare the (model, field) -> target_kind
   mapping in ``_FK_TARGETS`` and walk it deliberately.

4. **Long-form prose escapes to ``$EDITOR``**. A career summary or a
   testimonial quote does not belong on one prompt line. The user can
   type ``:e`` at any string prompt that lists the escape; the
   prompter's ``editor`` callback opens an editor with the current
   value pre-filled and returns the edited result.
"""

from __future__ import annotations

import inspect
import types
import typing
from collections.abc import Iterable
from typing import Any, Protocol, get_args, get_origin

from pydantic import BaseModel, ValidationError
from pydantic.fields import FieldInfo

from ..schema import (
    AnyEntity,
    Claim,
)
from .state import CorpusState
from .writers import suggest_entity_id

# (Model class name, field name) -> target entity kind for FK pickers.
# Listed explicitly so a renamed field surfaces a KeyError in the test
# suite rather than silently falling back to a free-form prompt.
_FK_TARGETS: dict[tuple[str, str], str] = {
    ("Role", "organization_id"): "organization",
    ("Role", "project_ids"): "project",
    ("Role", "achievement_ids"): "achievement",
    ("Role", "skill_ids"): "skill",
    ("Project", "organization_id"): "organization",
    ("Project", "role_id"): "role",
    ("Project", "artifact_ids"): "artifact",
    ("Project", "achievement_ids"): "achievement",
    ("Project", "skill_ids"): "skill",
    ("Achievement", "role_id"): "role",
    ("Achievement", "project_id"): "project",
    ("Achievement", "skill_ids"): "skill",
    ("Skill", "parent_id"): "skill",
    ("Artifact", "role_id"): "role",
    ("Artifact", "project_id"): "project",
    ("Target", "emphasis_skill_ids"): "skill",
    ("Target", "avoid_skill_ids"): "skill",
    ("Target", "job_description_source_id"): "source_doc",
}

# Field names whose value is most usefully edited in ``$EDITOR``. The
# wizard surfaces the ``:e`` escape only for these so a plain ``name``
# or ``location`` prompt stays a single line.
_LONG_FORM_FIELDS: frozenset[str] = frozenset(
    {"summary", "description", "body", "quote", "headline", "purpose", "text"}
)


class Prompter(Protocol):
    """Surface the wizard uses to talk to the user.

    Concrete implementations (Rich, scripted-for-tests, etc.) only need
    to satisfy this Protocol; the wizard never reaches for terminal
    capabilities directly.
    """

    def text(
        self,
        label: str,
        *,
        default: str | None = None,
        long_form: bool = False,
        help_text: str | None = None,
    ) -> str:
        """Prompt for a string. Empty input returns ``""``.

        ``long_form`` advertises the ``:e`` editor escape; the prompter
        decides what that means (Rich opens ``$EDITOR``; scripted
        ignores).
        """

    def confirm(self, label: str, *, default: bool = False) -> bool: ...

    def choice(
        self,
        label: str,
        options: list[tuple[str, str]],
        *,
        default: str | None = None,
        allow_none: bool = False,
        allow_freeform: bool = False,
        help_text: str | None = None,
    ) -> str | None:
        """Pick one of ``options`` (value, label) pairs.

        ``allow_none`` adds a "skip" entry that returns ``None``.
        ``allow_freeform`` lets the user type a value not in the list,
        useful for FK pickers when the target entity does not yet exist.
        """

    def info(self, message: str) -> None: ...
    def error(self, message: str) -> None: ...


class ScriptedPrompter:
    """Test prompter: replays canned responses in order.

    Each prompt method consumes one entry from ``responses``; mismatches
    raise so a test that goes off-script fails loudly rather than
    blocking on input. ``info`` and ``error`` accumulate into ``log``
    so assertions can inspect what the wizard reported.
    """

    def __init__(self, responses: Iterable[Any]) -> None:
        self._responses: list[Any] = list(responses)
        self._idx = 0
        self.log: list[tuple[str, str]] = []

    def _next(self, kind: str) -> Any:
        if self._idx >= len(self._responses):
            raise AssertionError(f"ScriptedPrompter exhausted on {kind!r}")
        value = self._responses[self._idx]
        self._idx += 1
        return value

    def text(
        self,
        label: str,
        *,
        default: str | None = None,
        long_form: bool = False,
        help_text: str | None = None,
    ) -> str:
        return str(self._next(f"text:{label}"))

    def confirm(self, label: str, *, default: bool = False) -> bool:
        return bool(self._next(f"confirm:{label}"))

    def choice(
        self,
        label: str,
        options: list[tuple[str, str]],
        *,
        default: str | None = None,
        allow_none: bool = False,
        allow_freeform: bool = False,
        help_text: str | None = None,
    ) -> str | None:
        v = self._next(f"choice:{label}")
        return None if v is None else str(v)

    def info(self, message: str) -> None:
        self.log.append(("info", message))

    def error(self, message: str) -> None:
        self.log.append(("error", message))

    @property
    def remaining(self) -> int:
        return len(self._responses) - self._idx


# --- Type unwrapping helpers ------------------------------------------


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    """Return ``(inner_type, is_optional)`` for ``X | None`` / ``Optional[X]``.

    Non-optional annotations come back as ``(annotation, False)``.
    """
    origin = get_origin(annotation)
    if origin is typing.Union or origin is types.UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return annotation, False


def _unwrap_list(annotation: Any) -> Any | None:
    """Return the element type for ``list[X]``, else ``None``.

    We only handle straight ``list[X]``; ``Sequence[X]`` and ``tuple``
    are intentionally not supported because the schema does not use
    them and conflating them would invite drift.
    """
    if get_origin(annotation) is list:
        args = get_args(annotation)
        if args:
            return args[0]
    return None


def _is_literal(annotation: Any) -> bool:
    return get_origin(annotation) is typing.Literal


def _literal_options(annotation: Any) -> list[str]:
    return [str(v) for v in get_args(annotation)]


def _is_basemodel(annotation: Any) -> bool:
    return inspect.isclass(annotation) and issubclass(annotation, BaseModel)


# --- Field-level prompt dispatch --------------------------------------


def _ask_field(
    *,
    model_name: str,
    field_name: str,
    info: FieldInfo,
    prompter: Prompter,
    state: CorpusState | None,
) -> Any:
    """Resolve one field's value by dispatching on its annotation.

    Returns whatever the prompter produced (with type coercion and
    optional/list wrapping); the caller stitches results into a dict
    and lets Pydantic validate the whole thing.
    """
    annotation = info.annotation
    inner, is_optional = _unwrap_optional(annotation)

    target_kind = _FK_TARGETS.get((model_name, field_name))

    list_inner = _unwrap_list(inner)
    if list_inner is not None:
        return _ask_list(
            model_name=model_name,
            field_name=field_name,
            element_type=list_inner,
            info=info,
            prompter=prompter,
            state=state,
            target_kind=target_kind,
        )

    label = _label(field_name, info, optional=is_optional)
    help_text = info.description or None

    if target_kind is not None and state is not None:
        chosen = _ask_fk(
            label=label,
            target_kind=target_kind,
            state=state,
            prompter=prompter,
            allow_none=is_optional,
            help_text=help_text,
        )
        return chosen

    if _is_literal(inner):
        opts = [(v, v) for v in _literal_options(inner)]
        default = info.default if info.default is not None else None
        return prompter.choice(
            label,
            opts,
            default=str(default) if default is not None else None,
            allow_none=is_optional,
            help_text=help_text,
        )

    if inner is bool:
        default_bool = bool(info.default) if info.default is not None else False
        return prompter.confirm(label, default=default_bool)

    if inner in (int, float):
        raw = prompter.text(label, default=None, help_text=help_text)
        if raw == "" and is_optional:
            return None
        try:
            return int(raw) if inner is int else float(raw)
        except ValueError:
            prompter.error(f"{field_name}: expected {inner.__name__}")
            return _ask_field(
                model_name=model_name,
                field_name=field_name,
                info=info,
                prompter=prompter,
                state=state,
            )

    if inner is dict or get_origin(inner) is dict:
        return _ask_dict(label, prompter, help_text=help_text)

    if _is_basemodel(inner):
        prompter.info(f"  -> nested {inner.__name__}:")
        return _ask_model_dict(inner, prompter=prompter, state=state)

    # Fallback: treat as string. ``PartialDate`` resolves here because
    # Pydantic flattens ``Annotated[str, AfterValidator]`` to ``str``;
    # the validator catches malformed dates so we do not reimplement
    # the regex here.
    long_form = field_name in _LONG_FORM_FIELDS
    raw = prompter.text(
        label,
        default=str(info.default) if info.default not in (None, ...) else None,
        long_form=long_form,
        help_text=help_text,
    )
    if raw == "" and is_optional:
        return None
    return raw


def _label(field_name: str, info: FieldInfo, *, optional: bool) -> str:
    pretty = field_name.replace("_", " ")
    suffix = " (optional)" if optional else ""
    return f"{pretty}{suffix}"


def _ask_list(
    *,
    model_name: str,
    field_name: str,
    element_type: Any,
    info: FieldInfo,
    prompter: Prompter,
    state: CorpusState | None,
    target_kind: str | None,
) -> list[Any]:
    """Loop, calling the appropriate sub-prompt until the user is done.

    The label is shown once at entry; each iteration prompts for one
    element with a ``(blank to finish)`` hint. List defaults are always
    treated as empty rather than a list of one because a singleton-list
    default is a footgun in this domain.
    """
    pretty = field_name.replace("_", " ")
    prompter.info(f"  {pretty} (enter values, blank to finish):")
    out: list[Any] = []
    inner_optional, _ = _unwrap_optional(element_type)
    while True:
        if target_kind is not None and state is not None:
            v = _ask_fk(
                label=f"  + {pretty} entry",
                target_kind=target_kind,
                state=state,
                prompter=prompter,
                allow_none=True,
                allow_freeform=True,
                help_text=info.description,
            )
            if v is None or v == "":
                break
            out.append(v)
            continue
        if _is_basemodel(inner_optional):
            if not prompter.confirm(f"  add another {inner_optional.__name__}?"):
                break
            out.append(_ask_model_dict(inner_optional, prompter=prompter, state=state))
            continue
        raw = prompter.text(f"  + {pretty} entry", default=None)
        if raw == "":
            break
        if inner_optional in (int, float):
            try:
                out.append(int(raw) if inner_optional is int else float(raw))
            except ValueError:
                prompter.error(f"expected {inner_optional.__name__}; skipped")
                continue
        else:
            out.append(raw)
    return out


def _ask_fk(
    *,
    label: str,
    target_kind: str,
    state: CorpusState,
    prompter: Prompter,
    allow_none: bool,
    allow_freeform: bool = True,
    help_text: str | None = None,
) -> str | None:
    """Pick an existing entity ID, or accept a free-form string.

    Free-form is allowed by default because the corpus is built
    incrementally: a Role often references skills the user has not
    declared yet. The validator's ``_c05_foreign_keys`` check catches
    dangling refs at validate time, which is the right place for
    that signal.
    """
    existing = state.list_kind(target_kind)
    options: list[tuple[str, str]] = [(e.id, _entity_summary(e)) for e in existing]
    return prompter.choice(
        label,
        options,
        allow_none=allow_none,
        allow_freeform=allow_freeform,
        help_text=help_text,
    )


def _entity_summary(entity: Any) -> str:
    """Best-effort one-line description for a picker row."""
    eid = str(getattr(entity, "id", ""))
    for attr in ("full_name", "name", "title", "headline", "institution"):
        v = getattr(entity, attr, None)
        if isinstance(v, str) and v:
            return f"{eid} - {v}"
    return eid


def _ask_dict(
    label: str, prompter: Prompter, *, help_text: str | None
) -> dict[str, str]:
    prompter.info(f"  {label} (key=value pairs, blank key to finish):")
    out: dict[str, str] = {}
    while True:
        key = prompter.text("    key")
        if key == "":
            break
        value = prompter.text(f"    value for {key}")
        out[key] = value
    return out


# Fields the wizard never prompts for: ``kind`` is the discriminator
# (set by the model default), ``schema_version`` is internal, and ``id``
# is always handled at the end of ``prompt_for_entity`` so the user can
# accept a slug suggestion built from the values they just typed.
_NEVER_PROMPT: frozenset[str] = frozenset({"kind", "schema_version", "id"})

# Fields better asked *after* the interesting subclass fields. These all
# come from ``Entity`` (or are equivalents on ``Claim``) and they show
# up first in ``model_fields`` order; promoting them to the end gives a
# more natural UX where the user fills the meaningful content before
# being asked about visibility and tags.
_LATE_FIELDS: tuple[str, ...] = ("visibility", "tags")


def _ask_model_dict(
    model_cls: type[BaseModel],
    *,
    prompter: Prompter,
    state: CorpusState | None,
) -> dict[str, Any]:
    """Walk every field on ``model_cls`` and collect a dict of values.

    The dict is what the wizard hands to ``model_cls(**values)`` so
    Pydantic validates the whole structure at once. We deliberately
    re-order the walk: subclass-specific fields first ("title",
    "organization_id", "period", ...), then ``visibility`` and ``tags``,
    so the user does not have to commit to metadata before they have
    typed any actual content.
    """
    values: dict[str, Any] = {}

    field_names = list(model_cls.model_fields)
    early = [f for f in field_names if f not in _NEVER_PROMPT and f not in _LATE_FIELDS]
    late = [
        f
        for f in _LATE_FIELDS
        if f in model_cls.model_fields and f not in _NEVER_PROMPT
    ]

    for field_name in (*early, *late):
        info = model_cls.model_fields[field_name]
        v = _ask_field(
            model_name=model_cls.__name__,
            field_name=field_name,
            info=info,
            prompter=prompter,
            state=state,
        )
        # An optional field that came back empty stays absent so the
        # default takes effect (vs. setting it to None which would
        # override a default_factory list, for example).
        if v is None and not info.is_required():
            continue
        if v == "" and not info.is_required():
            continue
        if v == [] and not info.is_required():
            continue
        values[field_name] = v
    return values


# --- Public entry points ----------------------------------------------


def prompt_for_entity(
    model_cls: type[AnyEntity],
    *,
    prompter: Prompter,
    state: CorpusState,
    suggested_id: str | None = None,
) -> AnyEntity:
    """Run the schema-driven wizard for one entity kind.

    The flow is:

    1. Walk every model field, prompting per type.
    2. Build a default ID from the recipe in ``writers``.
    3. Offer the user a chance to override the suggested ID.
    4. Construct the model. On ``ValidationError``, surface the field
       errors and re-prompt only the offending fields. The retry loop
       caps at three attempts so a hopelessly invalid input does not
       trap the user.
    """
    raw = _ask_model_dict(model_cls, prompter=prompter, state=state)
    kind = model_cls.model_fields["kind"].default

    existing_ids = state.ids_by_kind.get(str(kind), set())
    suggested = suggested_id or suggest_entity_id(str(kind), raw, existing_ids)
    chosen_id = prompter.text(
        f"id for this {kind}",
        default=suggested,
        help_text="Stable slug used by other entities to reference this one.",
    )
    raw["id"] = chosen_id or suggested

    return _build_with_retry(model_cls, raw, prompter)


def prompt_for_claim(
    *,
    prompter: Prompter,
    state: CorpusState,
    subject_kind: str | None = None,
    subject_id: str | None = None,
) -> Claim:
    """Build a ``Claim`` interactively.

    When called from inside the entity wizard, ``subject_kind`` and
    ``subject_id`` are pre-filled and the user is not re-asked. When
    invoked standalone, the user picks a subject kind (menu) then
    picks an entity of that kind (FK picker).
    """
    if subject_kind is None:
        kinds = sorted(state.by_kind.keys())
        if not kinds:
            prompter.error("no entities exist yet; create one before adding a claim")
            raise RuntimeError("empty corpus")
        chosen = prompter.choice(
            "subject kind",
            [(k, k) for k in kinds],
            allow_none=False,
            help_text="Which kind of entity is this claim about?",
        )
        subject_kind = chosen or kinds[0]

    if subject_id is None:
        chosen = _ask_fk(
            label="subject",
            target_kind=subject_kind,
            state=state,
            prompter=prompter,
            allow_none=False,
            allow_freeform=True,
            help_text="The entity ID this claim is about.",
        )
        subject_id = chosen or ""

    raw = _ask_model_dict(Claim, prompter=prompter, state=state)
    raw["subject_kind"] = subject_kind
    raw["subject_id"] = subject_id
    if "id" not in raw or not raw["id"]:
        existing = state.ids_by_kind.get("claim", set())
        suggestion = f"{subject_id}_claim"
        n = 2
        candidate = suggestion
        while candidate in existing:
            candidate = f"{suggestion}_{n}"
            n += 1
        raw["id"] = candidate

    return _build_with_retry_claim(raw, prompter)


def _build_with_retry(
    model_cls: type[AnyEntity],
    raw: dict[str, Any],
    prompter: Prompter,
    *,
    max_attempts: int = 3,
) -> AnyEntity:
    last_exc: ValidationError | None = None
    for _ in range(max_attempts):
        try:
            return model_cls(**raw)
        except ValidationError as exc:
            last_exc = exc
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                prompter.error(f"{loc}: {err['msg']}")
            for err in exc.errors():
                top = str(err["loc"][0]) if err["loc"] else None
                if top is None or top not in model_cls.model_fields:
                    continue
                info = model_cls.model_fields[top]
                raw[top] = _ask_field(
                    model_name=model_cls.__name__,
                    field_name=top,
                    info=info,
                    prompter=prompter,
                    state=None,
                )
    assert last_exc is not None
    raise last_exc


def _build_with_retry_claim(
    raw: dict[str, Any],
    prompter: Prompter,
    *,
    max_attempts: int = 3,
) -> Claim:
    last_exc: ValidationError | None = None
    for _ in range(max_attempts):
        try:
            return Claim(**raw)
        except ValidationError as exc:
            last_exc = exc
            for err in exc.errors():
                loc = ".".join(str(p) for p in err["loc"])
                prompter.error(f"{loc}: {err['msg']}")
            for err in exc.errors():
                top = str(err["loc"][0]) if err["loc"] else None
                if top is None or top not in Claim.model_fields:
                    continue
                info = Claim.model_fields[top]
                raw[top] = _ask_field(
                    model_name="Claim",
                    field_name=top,
                    info=info,
                    prompter=prompter,
                    state=None,
                )
    assert last_exc is not None
    raise last_exc
