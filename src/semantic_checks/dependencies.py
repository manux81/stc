"""Declaration dependency collection and topological ordering."""
from __future__ import annotations

from symbol_table import normalize_identifier
from .base import SemanticCheck, SemanticPhase, register_check, walk


@register_check(
    name="dependencies",
    phase=SemanticPhase.FINALIZATION,
    after=("collect-types",),
)
class DependencyAnalysis(SemanticCheck):
    def run(self, ast):
        names = set(self.context.declaration_order)
        for owner in names:
            self.context.dependencies.setdefault(owner, set())

        for declaration in walk(ast):
            owner = next(
                (
                    normalize_identifier(node["value"])
                    for node in walk(declaration)
                    if isinstance(node.get("value"), str)
                    and normalize_identifier(node["value"]) in names
                ),
                None,
            )
            if owner is None:
                continue
            references = {
                normalize_identifier(node["value"])
                for node in walk(declaration)
                if isinstance(node.get("value"), str)
                and normalize_identifier(node["value"]) in names
                and normalize_identifier(node["value"]) != owner
            }
            self.context.dependencies[owner].update(references)
        return self.context


def topological_declaration_order(context) -> list[str]:
    dependencies = {name: set(required) for name, required in context.dependencies.items()}
    result: list[str] = []
    while dependencies:
        ready = sorted(name for name, required in dependencies.items() if not required)
        if not ready:
            cycle = ", ".join(sorted(dependencies))
            raise ValueError(f"Cyclic declaration dependency: {cycle}")
        result.extend(ready)
        for name in ready:
            dependencies.pop(name)
        for required in dependencies.values():
            required.difference_update(ready)
    return result
