# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Load target primitive implementations from bundled source files."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files


@dataclass(frozen=True, slots=True)
class Primitive:
    name: str
    dependencies: tuple[str, ...]
    source: str


@lru_cache(maxsize=2)
def _load_primitives(target: str) -> tuple[Primitive, ...]:
    extension = {"c": "c", "rust": "rs"}.get(target)
    if extension is None:
        raise ValueError(f"Unsupported primitive target: {target}")
    source = files("stc_runtime").joinpath(f"primitives.{extension}").read_text(encoding="utf-8")
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


def render_primitives(target: str, requested: set[str] | frozenset[str]) -> str:
    """Render requested primitives and their dependencies in source order."""
    primitives = _load_primitives(target)
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

    rendered = [primitive.source for primitive in primitives if primitive.name in selected]
    return "\n".join(rendered).rstrip() + "\n" if rendered else ""
