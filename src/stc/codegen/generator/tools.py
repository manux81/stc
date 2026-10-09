"""Help, validation reports, and external generator scaffolding."""

from __future__ import annotations

from pathlib import Path
import re

from .loader import GeneratorBundle
from .schema import GENERATOR_API, generator_help


GENERATOR_FILES = (
    "language.gen", "types.gen", "expressions.gen", "statements.gen",
    "pou.gen", "oop.gen", "sfc.gen", "il.gen", "runtime.gen",
)

FILE_CATEGORIES = {
    "types.gen": {"types"},
    "expressions.gen": {"literals", "expressions", "conversions", "calls", "arrays", "references"},
    "statements.gen": {"assignments", "control flow"},
    "pou.gen": {"functions", "function blocks", "programs"},
    "oop.gen": {"properties", "OOP"},
    "sfc.gen": {"SFC"},
    "il.gen": {"IL"},
    "runtime.gen": {"runtime"},
    "language.gen": {"module"},
}


def validation_report(bundle: GeneratorBundle) -> str:
    implemented_categories: list[str] = []
    for spec in GENERATOR_API.values():
        if spec.required and spec.category not in implemented_categories:
            implemented_categories.append(spec.category)
    implemented = set(bundle.rules)
    lines = [f"Generator: {bundle.name}", ""]
    for category in implemented_categories:
        rules = {name for name, spec in GENERATOR_API.items() if spec.required and spec.category == category}
        lines.append(f"✓ {category}" if rules <= implemented else f"✗ {category}")
    status = "COMPLETE" if bundle.is_complete else "PARTIAL — not a standalone external backend"
    lines.extend((
        "", f"Phase 1 generator coverage: {bundle.coverage_for_phase(1):.0f}%",
        f"Phase 2 generator coverage: {bundle.coverage_for_phase(2):.0f}%",
        f"Phase 3 generator coverage: {bundle.coverage_for_phase(3):.0f}%",
        f"Phase 4 generator coverage: {bundle.coverage_for_phase(4):.0f}%",
        f"Full Generator API coverage: {bundle.full_coverage:.0f}%",
        f"Status: {status}",
    ))
    return "\n".join(lines) + "\n"


def create_generator_skeleton(name: str, destination: str | Path | None = None) -> Path:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
        raise ValueError("generator name must start with a letter and contain only letters, digits, '_' or '-'")
    root = Path(destination) if destination is not None else Path("generators") / name
    root = root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=False)
    assignments: dict[str, list] = {filename: [] for filename in GENERATOR_FILES}
    for spec in GENERATOR_API.values():
        filename = next(
            (item for item, categories in FILE_CATEGORIES.items() if spec.category in categories),
            "expressions.gen",
        )
        assignments[filename].append(spec)
    (root / "language.gen").write_text(
        f'# Generator metadata. Internal comments are not emitted.\n[generator]\nname = "{name}"\nextension = "txt"\n'
        + "".join(
            f'\n# {spec.description}\n# Variables:\n'
            + "\n".join(f"#   {{{value}}}" for value in spec.values)
            + f'\n[{spec.name}]\ndescription = {spec.description!r}\n'
            + ('mapping = {}\n' if spec.mapping else 'template = """\n"""\n')
            for spec in assignments["language.gen"]
        ),
        encoding="utf-8",
    )
    for filename in GENERATOR_FILES[1:]:
        chunks: list[str] = []
        for spec in assignments[filename]:
            variables = "\n".join(f"#   {{{value}}}" for value in spec.values)
            body = "mapping = {}" if spec.mapping else 'template = """\n"""'
            chunks.append(
                f"# {spec.description}\n# Variables:\n{variables}\n[{spec.name}]\n"
                f"description = {spec.description!r}\n{body}\n"
            )
        (root / filename).write_text("\n".join(chunks), encoding="utf-8")
    return root


__all__ = ["create_generator_skeleton", "generator_help", "validation_report"]
