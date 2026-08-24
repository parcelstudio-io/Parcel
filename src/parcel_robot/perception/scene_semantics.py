"""Loader for the per-scene semantics sidecar (stratum 3, registry 2).

MJCF carries no per-element metadata, so the scene's *vocabulary* — which geom
name prefixes mean which class, what a person may call that class, which
spatial relations are achievable with it, what role it plays as a landmark —
had to live as literals in Python. This module reads it from one YAML sidecar
instead (``configs/scenes/<scene>.semantics.yaml``) and hands
:mod:`parcel_robot.perception.city_semantics` the same tables it used to spell out.

**Fail closed.** Every unknown key, at every level, is an error rather than a
silently ignored typo: an affordance that is not a registered relation, a
landmark role outside the closed vocabulary, an attribute key the attribute
matcher cannot read, a prefix pointing at an undeclared class, or a prefix
table whose ordering would file ``tree_top_1`` under ``tree_``. A sidecar that
loads is a sidecar whose every field has a consumer.

**Not a geometry source.** Positions, polygons, and radii come from the MJCF at
extraction time. The sidecar carries no coordinates, which is what keeps it
from becoming a second, drifting copy of the scene (the exact failure Wave 0
found between ``evals/nav_instruct/generator.py`` and the real scene).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from parcel_robot.navigation.attributes import SIZE_METADATA_KEYS
from parcel_robot.navigation.relation_registry import RELATIONS
from parcel_robot.paths import resolve_asset

#: Sidecar version this loader understands. Bump only for an incompatible key
#: change; the loader refuses any other value rather than guessing.
SCENE_SEMANTICS_SCHEMA_VERSION = 1

#: Repo-relative default sidecar (the only scene that exists today).
DEFAULT_SIDECAR = "configs/scenes/city_block.semantics.yaml"

#: Closed vocabulary of landmark roles. Roles describe what a class is *for* in
#: a route description; they are not affordances (which name relations) and not
#: safety categories (which the envelope authority owns).
LANDMARK_ROLES: frozenset[str] = frozenset(
    {
        "boundary",
        "meeting_point",
        "obstacle",
        "seating",
        "shelter",
        "traversable",
        "waypoint",
    }
)

#: How a class's size is derived. Declarative only — the value is read from the
#: MJCF, never from the sidecar.
SIZE_SOURCES: frozenset[str] = frozenset({"geom_radius_m", "polygon"})

CLASS_KINDS: frozenset[str] = frozenset({"object", "region"})

_TOP_LEVEL_KEYS = frozenset(
    {"schema_version", "scene", "geom_prefixes", "region_prefixes", "classes"}
)
_CLASS_KEYS = frozenset(
    {"kind", "aliases", "affordances", "landmark_roles", "size", "metadata"}
)
_SIZE_KEYS = frozenset({"source", "note"})
_PREFIX_KEYS = frozenset({"prefix", "class"})


class SceneSemanticsError(ValueError):
    """A sidecar that cannot be trusted. Never downgraded to a warning."""


@dataclass(frozen=True)
class SceneClass:
    """One semantic class in a scene."""

    name: str
    kind: str
    aliases: tuple[str, ...]
    affordances: tuple[str, ...]
    landmark_roles: tuple[str, ...]
    size_source: str
    size_note: str
    metadata: tuple[tuple[str, float], ...] = ()

    def metadata_dict(self) -> dict[str, float]:
        return {key: value for key, value in self.metadata}

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "aliases": list(self.aliases),
            "affordances": list(self.affordances),
            "landmark_roles": list(self.landmark_roles),
            "size_source": self.size_source,
            "size_note": self.size_note,
            "metadata": self.metadata_dict(),
        }


@dataclass(frozen=True)
class SceneSemantics:
    """The whole sidecar, validated."""

    schema_version: int
    scene: str
    source_path: str
    classes: tuple[SceneClass, ...]
    object_prefixes: tuple[tuple[str, str], ...]
    region_prefixes: tuple[tuple[str, str], ...]

    def by_name(self) -> dict[str, SceneClass]:
        return {item.name: item for item in self.classes}

    def get(self, name: str) -> SceneClass:
        clean = str(name).strip().lower()
        for item in self.classes:
            if item.name == clean:
                return item
        raise KeyError(f"scene has no class {name!r}")

    def has(self, name: str) -> bool:
        return any(item.name == str(name).strip().lower() for item in self.classes)

    def class_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.classes)

    def alias_table(self) -> dict[str, tuple[str, ...]]:
        """class → aliases, in declaration order (``CLASS_ALIASES``)."""

        return {item.name: item.aliases for item in self.classes}

    def object_prefix_table(self) -> tuple[tuple[str, str], ...]:
        return self.object_prefixes

    def region_prefix_table(self) -> tuple[tuple[str, str], ...]:
        return self.region_prefixes

    def resolve_class_word(self, word: str) -> SceneClass | None:
        """Return the class a name or alias refers to, else ``None``."""

        clean = " ".join(str(word).strip().lower().split())
        if not clean:
            return None
        for item in self.classes:
            if clean == item.name or clean in item.aliases:
                return item
        return None

    def classes_with_role(self, role: str) -> tuple[SceneClass, ...]:
        clean = str(role).strip().lower()
        return tuple(item for item in self.classes if clean in item.landmark_roles)

    def detector_query_set(self) -> tuple[str, ...]:
        """Every surface form a detector prompt list would need, sorted.

        The third derived view named in the plan. Its intended consumer — the
        open-vocabulary detector prompt list — does not exist in the tree yet;
        it is here so that step reads this sidecar rather than growing a fourth
        copy of the vocabulary. The clarify fallback
        (`voice/scene_reference.known_scene_words`) already reads it as the set
        of scene words an utterance may name, which is the same question.
        """

        words: set[str] = set()
        for item in self.classes:
            words.add(item.name)
            words.update(item.aliases)
        return tuple(sorted(words))


def load_scene_semantics(path: str | Path | None = None) -> SceneSemantics:
    """Read and validate a sidecar. Raises :class:`SceneSemanticsError`."""

    resolved = Path(path) if path is not None else resolve_asset(*DEFAULT_SIDECAR.split("/"))
    try:
        raw = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    except OSError as error:
        raise SceneSemanticsError(f"cannot read scene semantics sidecar: {resolved}") from error
    except yaml.YAMLError as error:
        raise SceneSemanticsError(f"scene semantics sidecar is not valid YAML: {resolved}") from error
    return parse_scene_semantics(raw, source_path=str(resolved))


@lru_cache(maxsize=4)
def scene_semantics(path: str | None = None) -> SceneSemantics:
    """Process-wide cached load. One sidecar per scene, read once."""

    return load_scene_semantics(path)


def parse_scene_semantics(raw: Any, *, source_path: str = "<memory>") -> SceneSemantics:
    """Validate an already-parsed sidecar mapping (pure; no file access)."""

    data = _mapping(raw, "scene semantics sidecar")
    _exact_keys(data, _TOP_LEVEL_KEYS, "scene semantics sidecar")
    version = data["schema_version"]
    if version != SCENE_SEMANTICS_SCHEMA_VERSION:
        raise SceneSemanticsError(
            f"scene semantics schema_version must be {SCENE_SEMANTICS_SCHEMA_VERSION}, "
            f"got {version!r}"
        )
    scene = _text(data["scene"], "scene")

    classes_raw = _mapping(data["classes"], "classes")
    if not classes_raw:
        raise SceneSemanticsError("scene semantics sidecar declares no classes")
    classes = tuple(
        _parse_class(str(name), body) for name, body in classes_raw.items()
    )
    known = {item.name: item for item in classes}
    if len(known) != len(classes):
        raise SceneSemanticsError("scene semantics sidecar declares a duplicate class")

    object_prefixes = _parse_prefixes(data["geom_prefixes"], known, "object", "geom_prefixes")
    region_prefixes = _parse_prefixes(data["region_prefixes"], known, "region", "region_prefixes")

    declared = {name for _, name in object_prefixes} | {name for _, name in region_prefixes}
    orphans = sorted(set(known) - declared)
    if orphans:
        raise SceneSemanticsError(
            f"classes with no geom prefix cannot ever match a scene element: {orphans}"
        )

    return SceneSemantics(
        schema_version=int(version),
        scene=scene,
        source_path=source_path,
        classes=classes,
        object_prefixes=object_prefixes,
        region_prefixes=region_prefixes,
    )


def _parse_class(name: str, body: Any) -> SceneClass:
    clean_name = name.strip().lower()
    if not clean_name or clean_name != name:
        raise SceneSemanticsError(f"class name must be lowercase and trimmed: {name!r}")
    data = _mapping(body, f"class {clean_name!r}")
    _exact_keys(data, _CLASS_KEYS, f"class {clean_name!r}")

    kind = _text(data["kind"], f"class {clean_name!r} kind")
    if kind not in CLASS_KINDS:
        raise SceneSemanticsError(
            f"class {clean_name!r} kind must be one of {sorted(CLASS_KINDS)}, got {kind!r}"
        )

    aliases = _lower_tuple(data["aliases"], f"class {clean_name!r} aliases")
    if clean_name in aliases:
        raise SceneSemanticsError(f"class {clean_name!r} lists its own name as an alias")

    affordances = _lower_tuple(data["affordances"], f"class {clean_name!r} affordances")
    if not affordances:
        raise SceneSemanticsError(f"class {clean_name!r} declares no affordances")
    for relation in affordances:
        if not RELATIONS.has(relation):
            raise SceneSemanticsError(
                f"class {clean_name!r} affordance {relation!r} is not a registered relation "
                f"(known: {sorted(RELATIONS.names())})"
            )
        anchor_kind = "region" if kind == "region" else "object"
        if not RELATIONS.get(relation).accepts(anchor_kind):
            raise SceneSemanticsError(
                f"class {clean_name!r} is a {kind} but relation {relation!r} does not "
                f"accept a {anchor_kind} anchor"
            )

    roles = _lower_tuple(data["landmark_roles"], f"class {clean_name!r} landmark_roles")
    unknown_roles = sorted(set(roles) - LANDMARK_ROLES)
    if unknown_roles:
        raise SceneSemanticsError(
            f"class {clean_name!r} has landmark roles outside the closed vocabulary: "
            f"{unknown_roles} (known: {sorted(LANDMARK_ROLES)})"
        )

    size = _mapping(data["size"], f"class {clean_name!r} size")
    _exact_keys(size, _SIZE_KEYS, f"class {clean_name!r} size")
    size_source = _text(size["source"], f"class {clean_name!r} size.source")
    if size_source not in SIZE_SOURCES:
        raise SceneSemanticsError(
            f"class {clean_name!r} size.source must be one of {sorted(SIZE_SOURCES)}"
        )

    metadata_raw = data["metadata"]
    metadata_map = _mapping(metadata_raw if metadata_raw is not None else {}, "metadata")
    metadata: list[tuple[str, float]] = []
    for key, value in metadata_map.items():
        # One authority for what a size means: the attribute matcher owns the
        # key vocabulary, the sidecar owns the values.
        if key not in SIZE_METADATA_KEYS:
            raise SceneSemanticsError(
                f"class {clean_name!r} metadata key {key!r} is not readable by the "
                f"attribute matcher (known: {list(SIZE_METADATA_KEYS)})"
            )
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise SceneSemanticsError(
                f"class {clean_name!r} metadata {key!r} must be a number"
            ) from error
        if not number > 0.0:
            raise SceneSemanticsError(f"class {clean_name!r} metadata {key!r} must be > 0")
        metadata.append((str(key), number))

    return SceneClass(
        name=clean_name,
        kind=kind,
        aliases=aliases,
        affordances=affordances,
        landmark_roles=roles,
        size_source=size_source,
        size_note=" ".join(str(size["note"]).split()),
        metadata=tuple(sorted(metadata)),
    )


def _parse_prefixes(
    raw: Any,
    known: Mapping[str, SceneClass],
    expected_kind: str,
    field: str,
) -> tuple[tuple[str, str], ...]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or not raw:
        raise SceneSemanticsError(f"{field} must be a non-empty ordered list")
    table: list[tuple[str, str]] = []
    for entry in raw:
        data = _mapping(entry, f"{field} entry")
        _exact_keys(data, _PREFIX_KEYS, f"{field} entry")
        prefix = _text(data["prefix"], f"{field} prefix")
        class_name = _text(data["class"], f"{field} class")
        target = known.get(class_name)
        if target is None:
            raise SceneSemanticsError(f"{field} prefix {prefix!r} names undeclared class {class_name!r}")
        if target.kind != expected_kind:
            raise SceneSemanticsError(
                f"{field} prefix {prefix!r} names {class_name!r}, which is a "
                f"{target.kind}, not a {expected_kind}"
            )
        table.append((prefix, class_name))

    seen: set[str] = set()
    for index, (prefix, _) in enumerate(table):
        if prefix in seen:
            raise SceneSemanticsError(f"{field} repeats prefix {prefix!r}")
        seen.add(prefix)
        # Ordering rule, enforced instead of commented: a longer prefix that
        # shares a shorter one's head MUST come first, or every `tree_top_*`
        # geom is filed under `tree_`.
        for later, _ in table[index + 1 :]:
            if later.startswith(prefix):
                raise SceneSemanticsError(
                    f"{field} ordering is unsafe: {later!r} would never match because "
                    f"{prefix!r} precedes it"
                )
    return tuple(table)


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SceneSemanticsError(f"{name} must be a mapping, got {type(value).__name__}")
    return value


def _exact_keys(data: Mapping[str, Any], allowed: frozenset[str], name: str) -> None:
    actual = {str(key) for key in data}
    missing = sorted(allowed - actual)
    unknown = sorted(actual - allowed)
    if missing or unknown:
        raise SceneSemanticsError(
            f"{name} keys are invalid (missing={missing}, unknown={unknown})"
        )


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SceneSemanticsError(f"{name} must be a non-empty string")
    return " ".join(value.strip().split())


def _lower_tuple(value: Any, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, Mapping)):
        raise SceneSemanticsError(f"{name} must be a list of strings")
    out: list[str] = []
    for item in value:
        text = _text(item, f"{name} entry").lower()
        if text in out:
            raise SceneSemanticsError(f"{name} repeats {text!r}")
        out.append(text)
    return tuple(out)


__all__ = [
    "CLASS_KINDS",
    "DEFAULT_SIDECAR",
    "LANDMARK_ROLES",
    "SCENE_SEMANTICS_SCHEMA_VERSION",
    "SIZE_SOURCES",
    "SceneClass",
    "SceneSemantics",
    "SceneSemanticsError",
    "load_scene_semantics",
    "parse_scene_semantics",
    "scene_semantics",
]
