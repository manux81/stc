"""Compile-time constant evaluation."""
from __future__ import annotations

from semantic_types import (
    BOOL,
    BUILTIN_TYPES,
    INTEGER_TYPES,
    LINT,
    LREAL,
    REAL,
    ConstantValue,
    value_fits,
)
from symbol_table import normalize_identifier
from .base import SemanticCheck, SemanticPhase, direct_children, register_check, walk


@register_check(name="constant-folding", phase=SemanticPhase.CONSTANTS)
class ConstantFolder(SemanticCheck):
    def generic_visit(self, node):
        super().generic_visit(node)
        node_children = direct_children(node)
        if len(node_children) == 1:
            value = self.context.constant_of(node_children[0])
            if value is not None:
                self.context.constants[id(node)] = value
        self._fold_binary_expression(node, node_children)

    def visit_integer(self, node):
        self._integer_literal(node, 10)

    def visit_signed_integer(self, node):
        self._integer_literal(node, 10)

    def visit_binary_integer(self, node):
        self._integer_literal(node, 2)

    def visit_octal_integer(self, node):
        self._integer_literal(node, 8)

    def visit_hex_integer(self, node):
        self._integer_literal(node, 16)

    def visit_integer_literal(self, node):
        self._integer_literal(node, 10)
        declared = next(
            (
                child.get("value")
                for child in walk(node)
                if child.get("name")
                in {"signed_integer_type_name", "unsigned_integer_type_name"}
                and isinstance(child.get("value"), str)
            ),
            None,
        )
        type_key = normalize_identifier(declared or "")
        if type_key not in BUILTIN_TYPES:
            return
        datatype = BUILTIN_TYPES[type_key]
        current = self.context.constant_of(node)
        if current is not None:
            self.context.constants[id(node)] = ConstantValue(datatype, current.value)
            self.context.candidate_types[id(node)] = {datatype}

    def visit_real_literal(self, node):
        try:
            value = float(self._normalized_literal(node))
        except (TypeError, ValueError):
            return
        self.context.constants[id(node)] = ConstantValue(REAL, value)
        self.context.candidate_types[id(node)] = {REAL, LREAL}

    def visit_boolean_literal(self, node):
        raw = str(node.get("value")).casefold()
        if raw not in {"true", "false", "0", "1"}:
            return
        value = raw in {"true", "1"}
        self.context.constants[id(node)] = ConstantValue(BOOL, value)
        self.context.candidate_types[id(node)] = {BOOL}

    def _integer_literal(self, node, base: int) -> None:
        try:
            value = int(self._normalized_literal(node), base)
        except (TypeError, ValueError):
            return
        candidates = {datatype for datatype in INTEGER_TYPES if value_fits(value, datatype)}
        datatype = min(candidates, key=lambda item: item.bits or 999) if candidates else LINT
        self.context.constants[id(node)] = ConstantValue(datatype, value)
        self.context.candidate_types[id(node)] = candidates or {LINT}

    @staticmethod
    def _normalized_literal(node) -> str:
        raw = str(node.get("value")).replace("_", "")
        return raw.split("#", 1)[1] if "#" in raw else raw

    def _fold_binary_expression(self, node, node_children) -> None:
        operators = [
            child.get("value")
            for child in node_children
            if child.get("name", "").endswith("_operator")
            or child.get("name") == "comparison_operator"
        ]
        values = [
            self.context.constant_of(child)
            for child in node_children
            if self.context.constant_of(child) is not None
        ]
        if len(values) != 2 or not operators:
            return

        left, right = values
        operator = str(operators[0]).upper()
        operations = {
            "+": lambda: left.value + right.value,
            "-": lambda: left.value - right.value,
            "*": lambda: left.value * right.value,
            "/": lambda: left.value / right.value,
            "MOD": lambda: left.value % right.value,
            "=": lambda: left.value == right.value,
            "<>": lambda: left.value != right.value,
            "<": lambda: left.value < right.value,
            ">": lambda: left.value > right.value,
            "<=": lambda: left.value <= right.value,
            ">=": lambda: left.value >= right.value,
        }
        operation = operations.get(operator)
        if operation is None:
            return
        try:
            result = operation()
        except (ArithmeticError, ValueError):
            self.error("invalid-constant-expression", "Invalid constant expression.", node)
            return
        datatype = BOOL if isinstance(result, bool) else left.datatype
        self.context.constants[id(node)] = ConstantValue(datatype, result)
