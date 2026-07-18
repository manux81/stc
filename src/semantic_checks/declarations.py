"""Declaration and name-resolution checks."""
from __future__ import annotations

from semantic_types import BUILTIN_TYPES, DataType, TypeCategory, UNKNOWN_TYPE
from symbol_table import normalize_identifier
from .base import SemanticCheck, SemanticPhase, descendants, register_check, walk


@register_check(name="enum-declarations", phase=SemanticPhase.DECLARATIONS)
class EnumDeclarationCheck(SemanticCheck):
    def run(self, ast):
        for declaration in walk(ast):
            if declaration.get("name") not in {
                "enumerated_type_declaration",
                "enumerated_spec_init",
            }:
                continue

            seen: dict[str, dict] = {}
            for value in descendants(declaration, "enumerated_value"):
                if not isinstance(value.get("value"), str):
                    continue
                key = normalize_identifier(value["value"])
                if key in seen:
                    self.error(
                        "duplicate-enum-element",
                        f"Duplicate enum element '{value['value']}'.",
                        value,
                    )
                else:
                    seen[key] = value
        return self.context


@register_check(
    name="collect-types",
    phase=SemanticPhase.DECLARATIONS,
    after=("enum-declarations",),
)
class TypeDeclarationCollector(SemanticCheck):
    DECLARATION_NODES = {
        "simple_type_declaration",
        "array_type_declaration",
        "structure_type_declaration",
        "enumerated_type_declaration",
    }
    NAME_NODES = {
        "simple_type_name",
        "derived_type_name",
        "array_type_name",
        "structure_type_name",
    }

    def run(self, ast):
        self.context.declared_types.update(BUILTIN_TYPES)

        for declaration in walk(ast):
            if declaration.get("name") not in self.DECLARATION_NODES:
                continue
            name_node = next(
                (
                    node
                    for node in walk(declaration)
                    if node is not declaration
                    and node.get("name") in self.NAME_NODES
                    and isinstance(node.get("value"), str)
                ),
                None,
            )
            if name_node is None:
                continue

            key = normalize_identifier(name_node["value"])
            self.context.declared_types.setdefault(
                key,
                DataType(name_node["value"], TypeCategory.UNKNOWN),
            )
            self.context.declaration_order.append(key)

        for symbol in self.context.symbols.iter_symbols():
            if symbol.type_ref is None:
                continue
            type_name = normalize_identifier(symbol.type_ref.name or "")
            symbol.attributes["datatype"] = self.context.declared_types.get(
                type_name,
                UNKNOWN_TYPE,
            )
        return self.context


@register_check(
    name="declarations",
    phase=SemanticPhase.VALIDATION,
    after=("collect-types",),
)
class DeclarationCheck(SemanticCheck):
    def run(self, ast):
        for diagnostic in self.context.symbols.diagnostics:
            self.error(diagnostic.code, diagnostic.message, diagnostic.node)

        for node_id, symbol in self.context.symbols._references.items():
            if symbol is not None:
                continue
            node = self.context.symbols._reference_nodes[node_id]
            self.error(
                "undeclared-variable",
                f"Undeclared variable '{node.get('value')}'.",
                node,
            )

        for symbol in self.context.symbols.iter_symbols():
            if symbol.type_ref is None:
                continue
            type_name = normalize_identifier(symbol.type_ref.name or "")
            if type_name not in self.context.declared_types:
                self.error(
                    "unknown-type",
                    f"Unknown type '{symbol.type_ref.name}'.",
                    symbol.type_ref.node or symbol.declaration,
                )
        return self.context
