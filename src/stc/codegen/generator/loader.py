"""Load and validate deliberately small TOML-like ``.gen`` files."""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .schema import GENERATOR_API


class GeneratorError(ValueError):
    """A generator cannot be parsed or does not implement the public API."""


@dataclass(frozen=True, slots=True)
class GeneratorRule:
    name: str
    template: str | None = None
    each: str | None = None
    separator: str = ""
    when: str | None = None
    description: str | None = None
    mapping: dict[str, str] | None = None
    uses: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GeneratorBundle:
    path: Path
    name: str
    extension: str
    rules: dict[str, GeneratorRule]
    adapter: str = "c"

    @property
    def coverage(self) -> float:
        required = {name for name, spec in GENERATOR_API.items() if spec.required}
        return 100.0 * len(required & self.rules.keys()) / len(required)

    def coverage_for_phase(self, phase: int) -> float:
        required = {name for name, spec in GENERATOR_API.items() if spec.required and spec.phase <= phase}
        return 100.0 * len(required & self.rules.keys()) / len(required)

    @property
    def full_coverage(self) -> float:
        return 100.0 * len(self.rules.keys() & GENERATOR_API.keys()) / len(GENERATOR_API)

    @property
    def is_complete(self) -> bool:
        return set(GENERATOR_API) <= self.rules.keys()


_RULE_KEYS = {"template", "each", "separator", "when", "description", "mapping", "uses"}


def _fields(template: str) -> set[str]:
    # Only identifier-shaped braces are placeholders. Target-language braces
    # remain literal, so C/Rust authors do not have to escape ordinary blocks.
    return set(re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", template))


def _validate_graph(rules: dict[str, GeneratorRule]) -> None:
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str, trail: tuple[str, ...]) -> None:
        if name in visiting:
            raise GeneratorError("circular template composition: " + " -> ".join(trail + (name,)))
        if name in visited:
            return
        visiting.add(name)
        for dependency in rules[name].uses:
            if dependency not in rules:
                raise GeneratorError(f"section [{name}] uses missing section [{dependency}]")
            visit(dependency, trail + (name,))
        visiting.remove(name)
        visited.add(name)

    for name in rules:
        visit(name, ())


def load_generator(path: str | Path, *, require_complete: bool = True) -> GeneratorBundle:
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise GeneratorError(f"generator directory does not exist: {root}")
    documents: dict[str, dict[str, Any]] = {}
    metadata: dict[str, Any] = {}
    files = sorted(root.glob("*.gen"))
    if not files:
        raise GeneratorError(f"no .gen files found in {root}")
    for source in files:
        try:
            parsed = tomllib.loads(source.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise GeneratorError(f"{source.name}: {exc}") from exc
        for name, value in parsed.items():
            if name == "generator":
                if metadata:
                    raise GeneratorError("duplicate [generator] section")
                metadata = value
                continue
            if name in documents:
                raise GeneratorError(f"duplicate section [{name}]")
            documents[name] = value

    if not isinstance(metadata, dict):
        raise GeneratorError("[generator] must be a table")
    metadata_unknown = sorted(set(metadata) - {"name", "extension", "adapter"})
    if metadata_unknown:
        raise GeneratorError("[generator] has unknown fields: " + ", ".join(metadata_unknown))

    adapter = metadata.get("adapter", "rust" if metadata.get("extension") == "rs" else "c")
    if adapter not in {"c", "rust"}:
        raise GeneratorError("[generator].adapter must be c or rust")

    unknown = sorted(set(documents) - GENERATOR_API.keys())
    if unknown:
        raise GeneratorError("unknown generator sections: " + ", ".join(unknown))
    rules: dict[str, GeneratorRule] = {}
    for name, raw in documents.items():
        if not isinstance(raw, dict):
            raise GeneratorError(f"section [{name}] must be a table")
        extra = sorted(set(raw) - _RULE_KEYS)
        if extra:
            raise GeneratorError(f"section [{name}] has unknown fields: {', '.join(extra)}")
        spec = GENERATOR_API[name]
        mapping = raw.get("mapping")
        if mapping is not None and (not isinstance(mapping, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in mapping.items())):
            raise GeneratorError(f"section [{name}].mapping must contain string keys and values")
        if name == "layout_patterns" and mapping is not None:
            required_patterns = {"reference", "array", "array_value", "vector", "attached_name"}
            if set(mapping) != required_patterns:
                raise GeneratorError("layout_patterns must define reference, array, array_value, vector and attached_name")
            for key, pattern in mapping.items():
                try:
                    compiled = re.compile(pattern)
                except re.error as exc:
                    raise GeneratorError(f"invalid layout pattern {key}: {exc}") from exc
                expected = {"type", "dimensions"} if key == "array" else {"type", "size"} if key == "array_value" else set()
                # (?!) is the explicit disabled matcher used by reference bundles.
                if pattern != "(?!)" and set(compiled.groupindex) != expected:
                    raise GeneratorError(f"layout pattern {key} requires named groups {sorted(expected)}")
        template, each = raw.get("template"), raw.get("each")
        if template is None and each is None and mapping is None:
            raise GeneratorError(f"section [{name}] is unreachable: provide template, each, or mapping")
        uses = tuple(raw.get("uses", ()))
        allowed = set(spec.values) | set(uses) | {"items"}
        placeholders = _fields(template or "") | _fields(each or "") | _fields(raw.get("when") or "")
        unknown_values = sorted(placeholders - allowed)
        if unknown_values:
            raise GeneratorError(f"section [{name}] has unknown placeholders: " + ", ".join("{" + item + "}" for item in unknown_values))
        missing_values = sorted(set(spec.required_values) - placeholders)
        if missing_values:
            raise GeneratorError(f"section [{name}] is missing required placeholders: " + ", ".join("{" + item + "}" for item in missing_values))
        if spec.mapping and mapping is None:
            raise GeneratorError(f"section [{name}] requires a mapping")
        rules[name] = GeneratorRule(
            name=name, template=template, each=each, separator=raw.get("separator", ""),
            when=raw.get("when"), description=raw.get("description"), mapping=mapping,
            uses=uses,
        )
    if require_complete:
        missing = sorted(name for name, spec in GENERATOR_API.items() if spec.required and name not in rules)
        if missing:
            raise GeneratorError("missing required generator sections: " + ", ".join(missing))
    _validate_graph(rules)
    return GeneratorBundle(root, str(metadata.get("name", root.name)), str(metadata.get("extension", "txt")), rules, adapter)


def bundled_generator(name: str) -> Path:
    return Path(__file__).resolve().parents[2] / "generators" / name
