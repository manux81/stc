# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collect and narrow IEC function overload candidates, following matiec's two-pass model."""
from __future__ import annotations

import re
from dataclasses import dataclass

from semantic_types import UNKNOWN_TYPE, conversion_cost, is_assignable
from symbol_table import StorageClass, Symbol, SymbolKind, normalize_identifier
from .base import SemanticCheck, SemanticPhase, direct_children, register_check, walk


@dataclass(frozen=True, slots=True)
class CallArgument:
    node: dict
    expression: dict
    name: str | None


def _function_name(call: dict) -> str | None:
    children = direct_children(call)
    if not children or children[0].get("name") != "function_name":
        return None
    for node in walk(children[0]):
        if node.get("name") == "derived_function_name" and isinstance(node.get("value"), str):
            return node["value"]
    return None


def _arguments(call: dict) -> list[CallArgument]:
    result = []
    for argument in direct_children(call)[1:]:
        if argument.get("name") != "param_assignment":
            continue
        children = direct_children(argument)
        expression = next((child for child in reversed(children) if child.get("name") == "expression"), None)
        if expression is None:
            continue
        raw_children = argument.get("children", [])
        name = None
        if len(raw_children) > 1 and raw_children[1].get("value") in {":=", "=>"}:
            value = raw_children[0].get("value")
            name = value if isinstance(value, str) else None
        result.append(CallArgument(argument, expression, name))
    return result


def _parameters(context, function: Symbol) -> list[Symbol]:
    function_scope = next(
        (scope for scope in context.symbols.global_scope.children if scope.node is function.declaration),
        None,
    )
    if function_scope is None:
        return []
    return [symbol for symbol in function_scope.symbols.values() if symbol.kind == SymbolKind.PARAMETER]


def _ordered_arguments(arguments: list[CallArgument], parameters: list[Symbol]) -> list[CallArgument] | None:
    if len(arguments) != len(parameters):
        return None
    formal = any(argument.name is not None for argument in arguments)
    if not formal:
        return arguments
    if any(argument.name is None for argument in arguments):
        return None
    by_name = {normalize_identifier(argument.name or ""): argument for argument in arguments}
    if len(by_name) != len(arguments):
        return None
    keys = [parameter.key for parameter in parameters]
    if set(by_name) != set(keys):
        return None
    return [by_name[key] for key in keys]


def _candidate_cost(context, function: Symbol, arguments: list[CallArgument]) -> int | None:
    parameters = _parameters(context, function)
    ordered = _ordered_arguments(arguments, parameters)
    if ordered is None:
        return None
    total = 0
    for argument, parameter in zip(ordered, parameters):
        destination = parameter.attributes.get("datatype", UNKNOWN_TYPE)
        sources = context.candidates(argument.expression) or {UNKNOWN_TYPE}
        costs = [conversion_cost(source, destination) for source in sources if is_assignable(source, destination)]
        if not costs:
            return None
        variable_nodes = [node for node in walk(argument.expression) if node.get("name") == "variable_name"]
        argument_is_lvalue = any(context.lvalues.get(id(node), False) for node in walk(argument.expression))
        if len(variable_nodes) == 1:
            symbol = context.symbols.symbol_for_reference(variable_nodes[0])
            argument_is_lvalue = argument_is_lvalue or bool(
                symbol
                and symbol.kind in {SymbolKind.VARIABLE, SymbolKind.PARAMETER, SymbolKind.RETURN_VALUE}
                and not symbol.attributes.get("constant")
            )
        if parameter.storage in {StorageClass.OUTPUT, StorageClass.IN_OUT} and not argument_is_lvalue:
            return None
        total += min(costs)
    return total


def _mangled_name(context, function: Symbol) -> str:
    parameters = _parameters(context, function)
    parts = [function.name]
    for parameter in parameters:
        datatype = parameter.attributes.get("datatype", UNKNOWN_TYPE)
        parts.append(f"{parameter.storage.value}_{datatype.name}")
    return re.sub(r"[^0-9A-Za-z_]", "_", "__".join(parts))


@register_check(
    name="fill-call-candidates",
    phase=SemanticPhase.TYPES,
    after=("fill-candidate-types", "lvalues"),
)
class FillCallCandidates(SemanticCheck):
    def run(self, ast):
        signature_owner: dict[tuple[str, tuple[tuple[str, str], ...]], Symbol] = {}
        for overloads in self.context.symbols.global_scope.function_overloads.values():
            for function in overloads:
                signature = (
                    function.key,
                    tuple(
                        (parameter.storage.value, parameter.attributes.get("datatype", UNKNOWN_TYPE).name.casefold())
                        for parameter in _parameters(self.context, function)
                    ),
                )
                previous = signature_owner.get(signature)
                if previous is not None:
                    self.error(
                        "duplicate-overload",
                        f"Function '{function.name}' has the same IEC parameter signature as a previous overload.",
                        function.declaration,
                    )
                else:
                    signature_owner[signature] = function
                if len(overloads) > 1:
                    self.context.generated_names[id(function)] = _mangled_name(self.context, function)

        calls = [node for node in walk(ast) if node.get("name") == "primary_expression" and _function_name(node)]
        for call in calls:
            name = _function_name(call)
            scope = self.context.symbols.scope_for(call)
            overloads = self.context.symbols.lookup_functions(name or "", scope)
            arguments = _arguments(call)
            compatible = [function for function in overloads if _candidate_cost(self.context, function, arguments) is not None]
            self.context.candidate_functions[id(call)] = compatible
            returns = {
                function.attributes.get("datatype", UNKNOWN_TYPE)
                for function in compatible
            }
            if returns:
                self.context.candidate_types[id(call)] = returns

        # A call is wrapped in several single-child expression nodes. Propagate
        # its return candidates outward just like matiec annotates its AST.
        nodes = list(walk(ast))
        changed = True
        while changed:
            changed = False
            for node in nodes:
                children = direct_children(node)
                if len(children) != 1 or self.context.candidates(node):
                    continue
                candidates = self.context.candidates(children[0])
                if candidates:
                    self.context.candidate_types[id(node)] = set(candidates)
                    changed = True
        return self.context


@register_check(
    name="narrow-call-candidates",
    phase=SemanticPhase.TYPES,
    after=("narrow-candidate-types", "fill-call-candidates"),
)
class NarrowCallCandidates(SemanticCheck):
    def run(self, ast):
        for call in (node for node in walk(ast) if id(node) in self.context.candidate_functions):
            candidates = self.context.candidate_functions[id(call)]
            name = _function_name(call) or "<function>"
            if not candidates:
                self.error("no-matching-overload", f"No matching overload for function '{name}'.", call)
                continue
            arguments = _arguments(call)
            costs = {id(function): _candidate_cost(self.context, function, arguments) for function in candidates}
            best_cost = min(cost for cost in costs.values() if cost is not None)
            best = [function for function in candidates if costs[id(function)] == best_cost]
            expected = self.context.type_of(call)
            if expected is not None:
                by_return = [
                    function for function in best
                    if function.attributes.get("datatype", UNKNOWN_TYPE) == expected
                ]
                if by_return:
                    best = by_return
            if len(best) != 1:
                self.error("ambiguous-overload", f"Ambiguous overload for function '{name}'.", call)
                continue
            function = best[0]
            self.context.resolved_calls[id(call)] = function
            ordered = _ordered_arguments(arguments, _parameters(self.context, function))
            if ordered is not None:
                self.context.resolved_arguments[id(call)] = [argument.expression for argument in ordered]
            datatype = function.attributes.get("datatype", UNKNOWN_TYPE)
            self.context.set_type(call, datatype)
        return self.context
