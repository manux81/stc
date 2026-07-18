# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run independent lvalue, control-flow, CASE, and array validations."""
from __future__ import annotations

from dataclasses import dataclass

from symbol_table import SymbolKind
from .base import SemanticCheck, SemanticPhase, direct_children, descendants, register_check, walk


@register_check(name="flow-control", phase=SemanticPhase.FLOW)
class FlowControlAnalysis(SemanticCheck):
    def run(self, ast):
        for node in walk(ast):
            self.context.reachable_nodes.add(id(node))

        for statement_list in descendants(ast, "statement_list"):
            terminated = False
            for statement in direct_children(statement_list):
                if terminated:
                    self.context.reachable_nodes.discard(id(statement))
                    self.warning("unreachable-code", "Unreachable statement.", statement)
                if any(node.get("name") == "return_statement" for node in walk(statement)):
                    terminated = True
        return self.context


@register_check(
    name="lvalues",
    phase=SemanticPhase.VALIDATION,
    after=("declarations",),
)
class LValueCheck(SemanticCheck):
    WRITABLE_KINDS = {
        SymbolKind.VARIABLE,
        SymbolKind.PARAMETER,
        SymbolKind.RETURN_VALUE,
    }

    def is_lvalue(self, node) -> bool:
        cached = self.context.lvalues.get(id(node))
        if cached is not None:
            return cached

        variable_nodes = list(descendants(node, "variable_name"))
        symbol = None
        if variable_nodes:
            symbol = self.context.symbols.symbol_for_reference(variable_nodes[-1])
        result = bool(
            symbol
            and symbol.kind in self.WRITABLE_KINDS
            and not symbol.attributes.get("constant")
        )
        self.context.lvalues[id(node)] = result
        return result

    def has_unresolved_reference(self, node) -> bool:
        for variable_node in descendants(node, "variable_name"):
            if (
                self.context.symbols.reference_was_indexed(variable_node)
                and self.context.symbols.symbol_for_reference(variable_node) is None
            ):
                return True
        return False

    def run(self, ast):
        for node in walk(ast):
            if node.get("name") == "assignment_statement":
                node_children = direct_children(node)
                if (
                    node_children
                    and not self.has_unresolved_reference(node_children[0])
                    and not self.is_lvalue(node_children[0])
                ):
                    self.error(
                        "invalid-lvalue",
                        "Assignment target is not writable.",
                        node_children[0],
                    )
        return self.context


@dataclass(frozen=True, slots=True)
class CaseInterval:
    lower: int
    upper: int
    node: dict


@register_check(
    name="case-elements",
    phase=SemanticPhase.VALIDATION,
    after=("constant-folding",),
)
class CaseElementsCheck(SemanticCheck):
    def run(self, ast):
        for case_statement in descendants(ast, "case_statement"):
            intervals: list[CaseInterval] = []
            for label in descendants(case_statement, "case_list_element"):
                constants = [
                    self.context.constant_of(node)
                    for node in walk(label)
                    if self.context.constant_of(node) is not None
                ]
                if not constants:
                    self.error(
                        "non-constant-case-label",
                        "CASE label must be constant.",
                        label,
                    )
                    continue
                value = int(constants[-1].value)
                intervals.append(CaseInterval(value, value, label))

            intervals.sort(key=lambda interval: (interval.lower, interval.upper))
            for previous, current in zip(intervals, intervals[1:]):
                if current.lower <= previous.upper:
                    self.error(
                        "overlapping-case-elements",
                        f"Duplicate or overlapping CASE label {current.lower}.",
                        current.node,
                    )
        return self.context


@register_check(
    name="array-ranges",
    phase=SemanticPhase.VALIDATION,
    after=("constant-folding",),
)
class ArrayRangeCheck(SemanticCheck):
    def run(self, ast):
        for range_node in walk(ast):
            if range_node.get("name") not in {"subrange", "subrange_specification"}:
                continue
            values = [
                self.context.constant_of(node)
                for node in walk(range_node)
                if self.context.constant_of(node) is not None
            ]
            if len(values) >= 2 and int(values[0].value) > int(values[1].value):
                self.error(
                    "invalid-array-range",
                    f"Invalid range {values[0].value}..{values[1].value}.",
                    range_node,
                )
        return self.context
