# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Diagnose string-capacity errors that are known at compilation time."""
from ...frontend.strings import decode_character_literal
from ..strings import string_spec, target_string_spec
from .base import SemanticCheck, SemanticPhase, direct_children, register_check, walk


@register_check(name="string-capacity", phase=SemanticPhase.VALIDATION, after=("collect-types",))
class StringCapacityCheck(SemanticCheck):
    def _check_literal(self, node, spec):
        if spec is None:
            return
        kind, capacity = spec
        # Only a literal (with transparent expression wrappers) is constant here.
        literal = node
        literal_names = {
            "single_byte_character_string", "double_byte_character_string",
            "typed_character_string", "unicode_character_string",
        }
        while literal.get("name") not in literal_names:
            children = direct_children(literal)
            if len(children) != 1:
                return
            literal = children[0]
        token = next((n for n in walk(literal) if n.get("name") == "token"), None)
        if token is None:
            return
        try:
            content = decode_character_literal(str(token["value"]))
            length = len(content.encode("utf-16-le")) // 2 if kind == "WSTRING" else len(content)
        except (ValueError, UnicodeError):
            return  # Edition/literal validation reports malformed character values.
        if length > capacity:
            self.error("string-capacity-exceeded",
                       f"String value has length {length}, exceeding {kind}[{capacity}].", node)

    def run(self, ast):
        for symbol in self.context.symbols.iter_symbols():
            spec = string_spec(symbol)
            if spec is None:
                continue
            if spec[1] < 0:
                self.error("invalid-string-capacity", "String capacity cannot be negative.", symbol.declaration)
            declaration = symbol.type_ref.node
            if declaration is not None:
                for name in ("single_byte_character_string", "double_byte_character_string",
                             "typed_character_string", "unicode_character_string"):
                    for literal in (n for n in walk(declaration) if n.get("name") == name):
                        self._check_literal(literal, spec)
        for assignment in (n for n in walk(ast) if n.get("name") == "assignment_statement"):
            children = direct_children(assignment)
            if len(children) >= 2:
                self._check_literal(children[-1], target_string_spec(self.context, children[0]))
        return self.context
