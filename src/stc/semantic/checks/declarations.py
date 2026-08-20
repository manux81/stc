# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate declarations, type names, and identifier resolution."""
from __future__ import annotations

from ..types import BUILTIN_TYPES, DataType, EnumType, TypeCategory, UNKNOWN_TYPE
from ..symbol_table import StorageClass, normalize_identifier
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
        "subrange_type_declaration",
        "array_type_declaration",
        "structure_type_declaration",
        "enumerated_type_declaration",
    }
    NAME_NODES = {
        "simple_type_name",
        "subrange_type_name",
        "enumerated_type_name",
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
            if declaration.get("name") == "enumerated_type_declaration":
                elements = tuple(
                    node["value"]
                    for node in walk(declaration)
                    if node.get("name") == "enumerated_value"
                    and isinstance(node.get("value"), str)
                )
                datatype = EnumType(name_node["value"], TypeCategory.ENUM, elements=elements)
            elif declaration.get("name") == "array_type_declaration":
                datatype = DataType(name_node["value"], TypeCategory.ARRAY)
            elif declaration.get("name") == "structure_type_declaration":
                datatype = DataType(name_node["value"], TypeCategory.STRUCT)
            else:
                underlying = next(
                    (
                        BUILTIN_TYPES[normalize_identifier(node["value"])]
                        for node in walk(declaration)
                        if node is not name_node
                        and isinstance(node.get("value"), str)
                        and normalize_identifier(node["value"]) in BUILTIN_TYPES
                    ),
                    None,
                )
                datatype = (
                    DataType(name_node["value"], underlying.category, underlying.bits)
                    if underlying is not None
                    else DataType(name_node["value"], TypeCategory.UNKNOWN)
                )
            self.context.declared_types.setdefault(key, datatype)
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
    name="external-bindings",
    phase=SemanticPhase.VALIDATION,
    after=("collect-types",),
)
class ExternalBindingCheck(SemanticCheck):
    """Bind each VAR_EXTERNAL declaration to a matching VAR_GLOBAL symbol."""

    @staticmethod
    def _section_is_constant(section):
        return any(
            str(node.get("value", "")).upper() == "CONSTANT"
            for node in walk(section)
        )

    def run(self, ast):
        constant_declarations = set()
        for section in descendants(ast, "global_var_declarations"):
            if self._section_is_constant(section):
                constant_declarations.update(
                    id(node) for node in descendants(section, "global_var_name")
                )
        for section in descendants(ast, "external_var_declarations"):
            if self._section_is_constant(section):
                constant_declarations.update(
                    id(node) for node in descendants(section, "global_var_name")
                )

        globals_by_name = {}
        externals = []
        for symbol in self.context.symbols.iter_symbols():
            if id(symbol.declaration) in constant_declarations:
                symbol.attributes["constant"] = True
            if symbol.storage == StorageClass.GLOBAL:
                globals_by_name.setdefault(symbol.key, []).append(symbol)
            elif symbol.storage == StorageClass.EXTERNAL:
                externals.append(symbol)

        for external in externals:
            candidates = globals_by_name.get(external.key, [])
            if not candidates:
                self.error(
                    "unbound-external",
                    f"External variable '{external.name}' has no matching VAR_GLOBAL declaration.",
                    external.declaration,
                )
                continue
            external_type = external.attributes.get("datatype")
            compatible = [
                candidate for candidate in candidates
                if external_type is UNKNOWN_TYPE
                or candidate.attributes.get("datatype") is UNKNOWN_TYPE
                or (
                    candidate.attributes.get("datatype").category == external_type.category
                    and candidate.attributes.get("datatype").bits == external_type.bits
                )
            ]
            if not compatible:
                self.error(
                    "external-type-mismatch",
                    f"External variable '{external.name}' does not match the type of its VAR_GLOBAL declaration.",
                    external.declaration,
                )
                continue
            target = compatible[0]
            external.attributes["global"] = target
            if target.attributes.get("constant"):
                external.attributes["constant"] = True
        return self.context


@register_check(
    name="declarations",
    phase=SemanticPhase.VALIDATION,
    after=("external-bindings",),
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
