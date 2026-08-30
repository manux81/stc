# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Infer candidate types, narrow them, and report type errors."""
from __future__ import annotations

from ..types import (
    ArrayType, ERROR_TYPE, NULL_REFERENCE, ReferenceType, TypeCategory, UNKNOWN_TYPE,
    conversion_cost, is_assignable,
)
from ..symbol_table import ScopeKind, StorageClass
from .base import SemanticCheck, SemanticPhase, direct_children, register_check, walk


@register_check(
    name="fill-candidate-types",
    phase=SemanticPhase.TYPES,
    after=("constant-folding", "collect-types"),
)
class FillCandidateDatatypes(SemanticCheck):
    def run(self, ast):
        nodes = list(walk(ast))
        for node in nodes:
            if node.get("name") == "variable_name":
                symbol = (
                    self.context.symbols.symbol_for_reference(node)
                    or self.context.symbols.symbol_for_declaration(node)
                )
                if symbol is not None:
                    datatype = symbol.attributes.get("datatype", UNKNOWN_TYPE)
                    self.context.candidate_types[id(node)] = {datatype}
            if id(node) in self.context.constants:
                constant = self.context.constants[id(node)]
                self.context.candidate_types.setdefault(id(node), {constant.datatype})

            if node.get("name") == "reference_constructor":
                variable = next(
                    (item for item in walk(node) if item.get("name") == "variable_name"),
                    None,
                )
                symbol = self.context.symbols.symbol_for_reference(variable) if variable else None
                referenced = symbol.attributes.get("datatype", UNKNOWN_TYPE) if symbol else UNKNOWN_TYPE
                if any(item.get("name") == "array_variable" for item in walk(node)) and isinstance(referenced, ArrayType):
                    referenced = referenced.element_type or UNKNOWN_TYPE
                self.context.candidate_types[id(node)] = {
                    ReferenceType(
                        f"REF_TO {referenced.name}", TypeCategory.REFERENCE,
                        referenced_type=referenced,
                    )
                }
            elif node.get("name") == "reference_value" and node.get("value") == "NULL":
                self.context.candidate_types[id(node)] = {NULL_REFERENCE}
            elif node.get("name") == "dereferenced_variable":
                variable = next(
                    (item for item in walk(node) if item.get("name") == "variable_name"),
                    None,
                )
                symbol = self.context.symbols.symbol_for_reference(variable) if variable else None
                datatype = symbol.attributes.get("datatype", UNKNOWN_TYPE) if symbol else UNKNOWN_TYPE
                if isinstance(datatype, ReferenceType):
                    self.context.candidate_types[id(node)] = {
                        datatype.referenced_type or UNKNOWN_TYPE
                    }

        self._propagate_expression_types(nodes)
        return self.context

    @staticmethod
    def _operator_operands(node):
        return [
            child
            for child in direct_children(node)
            if not child.get("name", "").endswith("_operator")
            and child.get("name") != "comparison_operator"
        ]

    def _propagate_expression_types(self, nodes) -> None:
        changed = True
        while changed:
            changed = False
            for node in reversed(nodes):
                node_children = direct_children(node)
                if node.get("name") in {"reference_constructor", "dereferenced_variable"}:
                    continue
                if node.get("name") == "reference_value" and node.get("value") == "NULL":
                    continue
                if node.get("name") == "unary_expression" and len(node_children) == 1:
                    child_candidates = self.context.candidates(node_children[0])
                    if node.get("value") == "-":
                        child_candidates = {
                            datatype
                            for datatype in child_candidates
                            if datatype.category in {TypeCategory.SIGNED_INT, TypeCategory.REAL}
                        }
                    if child_candidates != self.context.candidates(node):
                        self.context.candidate_types[id(node)] = set(child_candidates)
                        changed = True
                    continue

                if node.get("name") in {"add_expression", "term"}:
                    operands = self._operator_operands(node)
                    if len(operands) >= 2 and all(self.context.candidates(item) for item in operands):
                        first_candidates = self.context.candidates(operands[0])
                        compatible = {
                            candidate
                            for candidate in first_candidates
                            if all(
                                any(
                                    is_assignable(other, candidate)
                                    and is_assignable(candidate, other)
                                    for other in self.context.candidates(operand)
                                )
                                for operand in operands[1:]
                            )
                        }
                        if compatible != self.context.candidates(node):
                            self.context.candidate_types[id(node)] = compatible
                            changed = True
                        continue

                if len(node_children) != 1:
                    continue
                child_candidates = self.context.candidates(node_children[0])
                node_candidates = self.context.candidates(node)
                if child_candidates and not child_candidates.issubset(node_candidates):
                    self.context.candidate_types[id(node)] = (
                        set(node_candidates) | set(child_candidates)
                    )
                    changed = True


@register_check(
    name="narrow-candidate-types",
    phase=SemanticPhase.TYPES,
    after=("fill-candidate-types",),
)
class NarrowCandidateDatatypes(SemanticCheck):
    def run(self, ast):
        nodes = list(walk(ast))
        for node in nodes:
            candidates = self.context.candidates(node)
            if len(candidates) == 1:
                self.context.set_type(node, next(iter(candidates)))

        for assignment in (node for node in nodes if node.get("name") == "assignment_statement"):
            node_children = direct_children(assignment)
            if len(node_children) < 2:
                continue
            target, expression = node_children[0], node_children[-1]
            pairs = [
                (source, destination)
                for source in self.context.candidates(expression)
                for destination in self.context.candidates(target)
                if is_assignable(source, destination)
            ]
            if not pairs:
                continue
            source, destination = min(pairs, key=lambda pair: conversion_cost(*pair))
            self.context.set_type(target, destination)
            self.context.set_type(expression, source)
        return self.context


@register_check(
    name="type-errors",
    phase=SemanticPhase.VALIDATION,
    after=("narrow-candidate-types", "narrow-call-candidates"),
)
class PrintDatatypesError(SemanticCheck):
    def run(self, ast):
        for assignment in (
            node for node in walk(ast) if node.get("name") == "assignment_statement"
        ):
            if id(assignment) in self.context.oop_assignments:
                continue
            node_children = direct_children(assignment)
            if len(node_children) < 2:
                continue
            target, expression = node_children[0], node_children[-1]
            destinations = self.context.candidates(target)
            sources = self.context.candidates(expression)
            if destinations and sources and not any(
                is_assignable(source, destination)
                for source in sources
                for destination in destinations
            ):
                source_names = sorted(datatype.name for datatype in sources)
                destination_names = sorted(datatype.name for datatype in destinations)
                self.error(
                    "incompatible-assignment",
                    f"Cannot assign {source_names} to {destination_names}.",
                    assignment,
                )

        for declaration in (
            node for node in walk(ast) if node.get("name") == "var1_init_decl"
        ):
            reference_value = next(
                (item for item in walk(declaration) if item.get("name") == "reference_value"),
                None,
            )
            if reference_value is None:
                continue
            declared_name = next(
                (item for item in walk(declaration) if item.get("name") == "variable_name"),
                None,
            )
            symbol = self.context.symbols.symbol_for_declaration(declared_name) if declared_name else None
            destination = symbol.attributes.get("datatype", UNKNOWN_TYPE) if symbol else UNKNOWN_TYPE
            sources = self.context.candidates(reference_value)
            if sources and not any(is_assignable(source, destination) for source in sources):
                self.error(
                    "incompatible-reference-initializer",
                    f"Cannot initialize '{symbol.name}' with this reference value.",
                    reference_value,
                )

        for node in walk(ast):
            if node.get("name") == "dereferenced_variable":
                variable = next(
                    (item for item in walk(node) if item.get("name") == "variable_name"),
                    None,
                )
                symbol = self.context.symbols.symbol_for_reference(variable) if variable else None
                datatype = symbol.attributes.get("datatype", UNKNOWN_TYPE) if symbol else UNKNOWN_TYPE
                if not isinstance(datatype, ReferenceType) and datatype is not UNKNOWN_TYPE:
                    self.error(
                        "dereference-non-reference",
                        f"Cannot dereference non-reference variable '{variable.get('value')}'.",
                        node,
                    )
            elif node.get("name") == "reference_constructor":
                variable = next(
                    (item for item in walk(node) if item.get("name") == "variable_name"),
                    None,
                )
                symbol = self.context.symbols.symbol_for_reference(variable) if variable else None
                if symbol is not None and (
                    symbol.storage == StorageClass.TEMP
                    or symbol.scope.kind == ScopeKind.FUNCTION
                ):
                    self.error(
                        "reference-to-temporary",
                        f"REF cannot be applied to temporary variable '{symbol.name}'.",
                        node,
                    )

        for symbol in self.context.symbols.iter_symbols():
            if (
                symbol.storage == StorageClass.IN_OUT
                and isinstance(symbol.attributes.get("datatype"), ReferenceType)
            ):
                self.error(
                    "reference-in-out",
                    f"Reference variable '{symbol.name}' cannot be declared VAR_IN_OUT.",
                    symbol.declaration,
                )
        return self.context


@register_check(
    name="force-types",
    phase=SemanticPhase.FINALIZATION,
    after=("type-errors",),
)
class ForcedNarrowCandidateDatatypes(SemanticCheck):
    def run(self, ast):
        for node in walk(ast):
            if self.context.type_of(node) is not None:
                continue
            candidates = self.context.candidates(node)
            if candidates:
                chosen = min(
                    candidates,
                    key=lambda datatype: (
                        datatype.category == TypeCategory.UNKNOWN,
                        datatype.bits or 999,
                        datatype.name,
                    ),
                )
            else:
                chosen = ERROR_TYPE
            self.context.set_type(node, chosen)
        return self.context
