# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Load target primitive implementations from backend-owned source files.

Dependency resolution is generic: the certificates (names and dependencies)
are parsed from ``STC_PRIMITIVE_BEGIN`` markers in whatever
``primitives.<extension>`` file the active generator bundle owns.  The bundle
directory wins; the historical ``stc.runtime`` directory remains as a
fallback for the bundled C and Rust backends.  Rendering goes through the
backend's ``[runtime_primitive]`` template, so no target branch lives here.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Primitive:
    name: str
    dependencies: tuple[str, ...]
    source: str


def _parse_primitives(source: str, extension: str) -> tuple[Primitive, ...]:
    primitives: list[Primitive] = []
    current_name: str | None = None
    dependencies: tuple[str, ...] = ()
    body: list[str] = []

    for line in source.splitlines(keepends=True):
        stripped = line.strip()
        if stripped.startswith("// STC_PRIMITIVE_BEGIN "):
            if current_name is not None:
                raise ValueError(f"Nested primitive block in primitives.{extension}")
            fields = stripped.split()
            current_name = fields[2].upper()
            dependencies = tuple(field.upper() for field in fields[3:])
            body = []
        elif stripped.startswith("// STC_PRIMITIVE_END "):
            end_name = stripped.split()[2].upper()
            if current_name != end_name:
                raise ValueError(f"Mismatched primitive block {current_name!r}/{end_name!r}")
            primitives.append(Primitive(current_name, dependencies, "".join(body).strip() + "\n"))
            current_name = None
            dependencies = ()
            body = []
        elif current_name is not None:
            body.append(line)

    if current_name is not None:
        raise ValueError(f"Unterminated primitive block {current_name!r}")
    return tuple(primitives)


def _primitive_source(extension: str, bundle_path: str | Path | None) -> str:
    candidates: list[Path] = []
    if bundle_path is not None:
        candidates.append(Path(bundle_path) / f"primitives.{extension}")
    try:
        candidates.append(Path(str(files("stc.runtime").joinpath(f"primitives.{extension}"))))
    except (OSError, ValueError, TypeError):
        pass
    for candidate in candidates:
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise ValueError(f"Unsupported primitive target: no primitives.{extension} found")


@lru_cache(maxsize=8)
def _load_primitives(target: str, bundle_path: str = "") -> tuple[Primitive, ...]:
    extension = {"c": "c", "rust": "rs"}.get(target, target)
    source = _primitive_source(extension, bundle_path or None)
    byte_arrays = Path(bundle_path) / f"byte_arrays.{extension}" if bundle_path else None
    if byte_arrays is None or not byte_arrays.is_file():
        byte_arrays = Path(__file__).with_name(f"byte_arrays.{extension}")
    if byte_arrays.is_file():
        source += "\n" + byte_arrays.read_text(encoding="utf-8")
    return _parse_primitives(source, extension)


def _select(primitives: tuple[Primitive, ...], requested: set[str] | frozenset[str]) -> list[Primitive]:
    by_name = {primitive.name: primitive for primitive in primitives}
    selected = {"CORE"}

    def select(name: str) -> None:
        normalized = name.upper()
        primitive = by_name.get(normalized)
        if primitive is None or normalized in selected:
            return
        selected.add(normalized)
        for dependency in primitive.dependencies:
            select(dependency)

    for name in requested:
        select(name)
    return [primitive for primitive in primitives if primitive.name in selected]


def render_primitives(
    target: str,
    requested: set[str] | frozenset[str],
    engine: Any | None = None,
    bundle_path: str | Path | None = None,
) -> str:
    """Render requested primitives and their dependencies in source order.

    When a generator engine is supplied, each primitive is rendered through
    its ``[runtime_primitive]`` template; otherwise raw sources are joined
    for backward compatibility.
    """
    primitives = _load_primitives(target, str(bundle_path or ""))
    selected = _select(primitives, requested)
    if engine is None:
        rendered = [primitive.source for primitive in selected]
        return "\n".join(rendered).rstrip() + "\n" if rendered else ""
    chunks = [
        engine.render(
            "runtime_primitive",
            name=primitive.name,
            dependencies=", ".join(primitive.dependencies),
            declaration="",
            implementation=primitive.source,
        )
        for primitive in selected
    ]
    return "".join(chunks)
