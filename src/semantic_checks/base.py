"""Infrastructure shared by semantic checks.

A new check normally subclasses :class:`SemanticCheck`, implements ``run`` or
one or more ``visit_<ast-node-name>`` methods, and is registered with
``@register_check``.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, ClassVar

from semantic_context import SemanticContext

AstNode = dict[str, Any]


class SemanticPhase(IntEnum):
    DECLARATIONS = 10
    FLOW = 20
    CONSTANTS = 30
    TYPES = 40
    VALIDATION = 50
    FINALIZATION = 60


@dataclass(frozen=True, slots=True)
class CheckMetadata:
    name: str
    phase: SemanticPhase
    description: str = ""
    after: tuple[str, ...] = ()


class SemanticCheck:
    """Base class for one independent semantic analysis pass."""

    metadata: ClassVar[CheckMetadata]

    def __init__(self, context: SemanticContext):
        self.context = context

    def run(self, ast: AstNode) -> SemanticContext:
        self.visit(ast)
        return self.context

    def visit(self, node: AstNode | None) -> None:
        if not isinstance(node, dict):
            return
        method = getattr(self, f"visit_{node.get('name', '')}", self.generic_visit)
        method(node)

    def generic_visit(self, node: AstNode) -> None:
        for child in children(node):
            self.visit(child)

    def error(self, code: str, message: str, node: AstNode) -> None:
        self.context.error(code, message, node)

    def warning(self, code: str, message: str, node: AstNode) -> None:
        self.context.warning(code, message, node)


_REGISTRY: dict[str, type[SemanticCheck]] = {}


def register_check(
    *,
    name: str,
    phase: SemanticPhase,
    description: str = "",
    after: tuple[str, ...] = (),
):
    """Register a semantic check in the default pipeline."""

    def decorator(check_type: type[SemanticCheck]) -> type[SemanticCheck]:
        if name in _REGISTRY:
            raise ValueError(f"Semantic check '{name}' is already registered")
        check_type.metadata = CheckMetadata(name, phase, description, after)
        _REGISTRY[name] = check_type
        return check_type

    return decorator


def registered_checks() -> tuple[type[SemanticCheck], ...]:
    return tuple(_REGISTRY.values())


def children(node: AstNode) -> Iterator[AstNode]:
    for child in node.get("children", []):
        if isinstance(child, dict):
            yield child


def walk(node: AstNode | None) -> Iterator[AstNode]:
    if not isinstance(node, dict):
        return
    yield node
    for child in children(node):
        yield from walk(child)


def descendants(node: AstNode, *names: str) -> Iterator[AstNode]:
    accepted = set(names)
    for item in walk(node):
        if item.get("name") in accepted:
            yield item


def direct_children(node: AstNode) -> list[AstNode]:
    return list(children(node))
