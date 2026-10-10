"""Help, validation reports, and external generator scaffolding."""

from __future__ import annotations

from pathlib import Path
import re
import shutil

from .loader import GeneratorBundle, bundled_generator, load_generator
from .schema import GENERATOR_API, generator_help


GENERATOR_FILES = (
    "language.gen", "types.gen", "expressions.gen", "statements.gen",
    "pou.gen", "oop.gen", "sfc.gen", "il.gen", "runtime.gen",
)


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
        f"Phase 5 generator coverage: {bundle.coverage_for_phase(5):.0f}%",
        f"Full Generator API coverage: {bundle.full_coverage:.0f}%",
        f"Status: {status}",
    ))
    return "\n".join(lines) + "\n"


def create_generator_skeleton(name: str, destination: str | Path | None = None, *, base: str = "c") -> Path:
    """Create a runnable backend by copying a validated reference bundle."""
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
        raise ValueError("generator name must start with a letter and contain only letters, digits, '_' or '-'")
    if base not in {"c", "rust"}:
        raise ValueError("generator base must be c or rust")
    source = bundled_generator(base)
    load_generator(source)
    root = Path(destination) if destination is not None else Path("generators") / name
    root = root.expanduser().resolve()
    shutil.copytree(source, root)
    metadata = root / "language.gen"
    metadata.write_text(metadata.read_text(encoding="utf-8").replace(
        f'name = "{base}"', f'name = "{name}"', 1), encoding="utf-8")
    # Include runtime bodies so the reference copy is self-contained.
    runtime = Path(__file__).resolve().parents[2] / "runtime"
    extension = "rs" if base == "rust" else "c"
    shutil.copy2(runtime / f"primitives.{extension}", root / f"primitives.{extension}")
    shutil.copy2(runtime / f"byte_arrays.{extension}", root / f"byte_arrays.{extension}")
    load_generator(root)
    return root


__all__ = ["create_generator_skeleton", "generator_help", "validation_report"]
