# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Inject conversion functions for user-defined enumerated types.

The IEC standard library cannot declare conversions whose signatures contain a
type that is only introduced by the user program.  As in matiec, this lowering
pass generates Structured Text functions and appends their parsed nodes to the
AST.  The normal symbol table, overload resolver, type checker, and backends can
therefore process them without enum-specific call handling.
"""
from __future__ import annotations

from ast_builder import AstBuilder
from iec_lexer import IECLexer
from iec_parser import IECParser


INTEGER_TYPES = ("SINT", "INT", "DINT", "LINT", "USINT", "UINT", "UDINT", "ULINT")


def _walk(node):
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []):
        yield from _walk(child)


def _enum_declarations(ast):
    seen = set()
    for declaration in _walk(ast):
        if declaration.get("name") != "enumerated_type_declaration":
            continue
        name_node = next(
            (node for node in _walk(declaration) if node.get("name") == "enumerated_type_name"),
            None,
        )
        if name_node is None or not isinstance(name_node.get("value"), str):
            continue
        name = name_node["value"]
        if name.casefold() in seen:
            continue
        values = [
            node["value"]
            for node in _walk(declaration)
            if node.get("name") == "enumerated_value" and isinstance(node.get("value"), str)
        ]
        if values:
            seen.add(name.casefold())
            yield name, values


def _string_to_enum(enum_name, values):
    function_name = f"STRING_TO_{enum_name}"
    lines = [
        f"FUNCTION {function_name} : {enum_name}",
        "VAR_INPUT Value : STRING; END_VAR",
    ]
    for index, value in enumerate(values):
        keyword = "IF" if index == 0 else "ELSIF"
        lines.extend((
            f"{keyword} Value = '{value}' THEN",
            f"    {function_name} := {enum_name}#{value};",
        ))
    lines.extend((
        "ELSE",
        f"    {function_name} := {enum_name}#{values[0]};",
        "END_IF;",
        "END_FUNCTION",
    ))
    return "\n".join(lines)


def _enum_to_string(enum_name, values):
    function_name = f"{enum_name}_TO_STRING"
    lines = [
        f"FUNCTION {function_name} : STRING",
        f"VAR_INPUT Value : {enum_name}; END_VAR",
        "CASE Value OF",
    ]
    for value in values:
        lines.append(f"    {value}: {function_name} := '{enum_name}#{value}';")
    lines.extend((
        f"    ELSE {function_name} := '{enum_name}#{values[0]}';",
        "END_CASE;",
        "END_FUNCTION",
    ))
    return "\n".join(lines)


def _integer_to_enum(integer_type, enum_name, values):
    function_name = f"{integer_type}_TO_{enum_name}"
    lines = [
        f"FUNCTION {function_name} : {enum_name}",
        f"VAR_INPUT Value : {integer_type}; END_VAR",
        "CASE Value OF",
    ]
    for ordinal, value in enumerate(values):
        lines.append(f"    {ordinal}: {function_name} := {enum_name}#{value};")
    lines.extend((
        f"    ELSE {function_name} := {enum_name}#{values[0]};",
        "END_CASE;",
        "END_FUNCTION",
    ))
    return "\n".join(lines)


def _enum_to_integer(enum_name, integer_type, values):
    function_name = f"{enum_name}_TO_{integer_type}"
    lines = [
        f"FUNCTION {function_name} : {integer_type}",
        f"VAR_INPUT Value : {enum_name}; END_VAR",
        "CASE Value OF",
    ]
    for ordinal, value in enumerate(values):
        lines.append(f"    {value}: {function_name} := {ordinal};")
    lines.extend((
        f"    ELSE {function_name} := 0;",
        "END_CASE;",
        "END_FUNCTION",
    ))
    return "\n".join(lines)


def _conversion_source(enum_name, values):
    functions = [_string_to_enum(enum_name, values), _enum_to_string(enum_name, values)]
    for integer_type in INTEGER_TYPES:
        functions.append(_integer_to_enum(integer_type, enum_name, values))
        functions.append(_enum_to_integer(enum_name, integer_type, values))
    return "\n\n".join(functions) + "\n"


def inject_enum_conversion_functions(ast):
    """Append synthetic conversion declarations and return the added nodes."""
    added = []
    builder = AstBuilder()
    for enum_name, values in _enum_declarations(ast):
        source = _conversion_source(enum_name, values)
        tree = IECParser().set_source(source).parse(IECLexer().tokenize(source))
        if tree is None:
            raise RuntimeError(f"Unable to generate conversion functions for enum '{enum_name}'.")
        generated_ast = builder.build(tree)
        for node in generated_ast.get("children", []):
            node["synthetic"] = True
            node["generated_by"] = "enum-conversions"
            node["enum_type"] = enum_name
            for descendant in _walk(node):
                if descendant.get("name") == "function_declaration":
                    descendant["synthetic"] = True
                    descendant["generated_by"] = "enum-conversions"
                    descendant["enum_type"] = enum_name
            added.append(node)
    ast.setdefault("children", []).extend(added)
    return added
