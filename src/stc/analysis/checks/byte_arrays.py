# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Check Edition 4 unary string/byte-array conversion intrinsics."""
from ..types import ArrayType, ArrayDimension, BYTE, STRING, WSTRING, USTRING, TypeCategory
from .base import SemanticCheck, SemanticPhase, direct_children, register_check, walk

STRING_TO_BYTES = {f"{name}_TO_ARRAY_OF_BYTE": t for name, t in
                   (("STRING", STRING), ("WSTRING", WSTRING), ("USTRING", USTRING))}
BYTES_TO_STRING = {f"ARRAY_OF_BYTE_TO_{name}": t for name, t in
                   (("STRING", STRING), ("WSTRING", WSTRING), ("USTRING", USTRING))}
CONVERSIONS = STRING_TO_BYTES | BYTES_TO_STRING


def conversion_call(node):
    for call in walk(node):
        if call.get("name") != "primary_expression":
            continue
        children = direct_children(call)
        if not children or children[0].get("name") != "function_name":
            continue
        name = next((str(n.get("value", "")).upper() for n in walk(children[0])
                     if n.get("name") == "standard_function_name"), "")
        if name in CONVERSIONS:
            arguments = [next((n for n in reversed(direct_children(arg))
                               if n.get("name") == "expression"), None)
                         for arg in children[1:] if arg.get("name") == "param_assignment"]
            return call, name, arguments
    return None


def byte_array(t):
    return (isinstance(t, ArrayType) and len(t.dimensions) == 1
            and t.element_type is not None and t.element_type.name == "BYTE")


def resolved_byte_array(context, expression):
    """Resolve named arrays and legacy inline declarations without ArrayType."""
    t = context.type_of(expression)
    if byte_array(t):
        return t
    found = next((t for t in context.candidates(expression) if byte_array(t)), None)
    if found is not None:
        return found
    variables = [n for n in walk(expression) if n.get("name") == "variable_name"]
    if len(variables) != 1 or any(n.get("name") == "array_variable" for n in walk(expression)):
        return None
    symbol = context.symbols.symbol_for_reference(variables[0])
    if symbol is None:
        return None
    for declaration in walk(symbol.scope.node):
        if declaration.get("name") not in {"array_var_init_decl", "array_var_declaration", "var1_init_decl"}:
            continue
        if not any(n is symbol.declaration for n in walk(declaration)):
            continue
        specification = next((n for n in walk(declaration) if n.get("name") == "array_specification"), None)
        if specification is None and symbol.type_ref is not None:
            wanted = symbol.type_ref.name.casefold()
            for definition in walk(context.symbols.global_scope.node):
                if definition.get("name") != "array_type_declaration":
                    continue
                if not any(str(n.get("value", "")).casefold() == wanted
                           for n in direct_children(definition)):
                    continue
                specification = next((n for n in walk(definition)
                                      if n.get("name") == "array_specification"), None)
                if specification is not None:
                    break
        if specification is None:
            continue
        types = [str(n.get("value", "")).upper() for n in walk(specification)
                 if n.get("name", "").endswith("_type_name") and n.get("value")]
        ranges = [n for n in walk(specification) if n.get("name") == "subrange"]
        if types != ["BYTE"] or len(ranges) != 1:
            return None
        bounds = [n for n in walk(ranges[0]) if n.get("name") == "signed_integer"]
        if len(bounds) != 2:
            return None
        values = []
        for bound in bounds:
            value = context.constant_of(bound)
            if value is not None:
                values.append(int(value.value))
            else:
                raw = str(bound.get("value", ""))
                try:
                    values.append(int(raw.replace("_", "")))
                except ValueError:
                    return None
        if values[1] < values[0]:
            return None
        return ArrayType("<byte-array>", TypeCategory.ARRAY, dimensions=(ArrayDimension(*values),), element_type=BYTE)
    return None


def string_literal_type(expression):
    current = expression
    names = {"unicode_character_string", "typed_character_string", "single_byte_character_string", "double_byte_character_string"}
    while len(direct_children(current)) == 1 and current.get("name") not in names:
        current = direct_children(current)[0]
    name = current.get("name")
    if name == "single_byte_character_string":
        return STRING
    if name == "double_byte_character_string":
        return WSTRING
    if name in {"unicode_character_string", "typed_character_string"}:
        token = next((n for n in walk(current) if n.get("name") == "token"), {})
        prefix = str(token.get("value", "")).split("#", 1)[0].upper().strip()
        return {"STRING": STRING, "WSTRING": WSTRING, "USTRING": USTRING, "U": USTRING}.get(prefix)
    return None


@register_check(name="byte-array-conversions", phase=SemanticPhase.TYPES,
                after=("narrow-call-candidates",), description="Validate string/byte-array conversions.")
class ByteArrayConversions(SemanticCheck):
    def run(self, ast):
        parents = {id(child): node for node in walk(ast) for child in direct_children(node)}
        touched = []
        for call in walk(ast):
            if call.get("name") != "primary_expression":
                continue
            match = conversion_call(call)
            if match is None or match[0] is not call:
                continue
            _, name, arguments = match
            if self.context.standard_edition < 4:
                self.error("edition4-byte-array-conversion", f"{name} requires Edition 4.", call)
            if len(arguments) != 1 or arguments[0] is None:
                self.error("byte-array-conversion-arity", f"{name} requires exactly one argument.", call)
                continue
            argument = arguments[0]
            if name in BYTES_TO_STRING:
                if resolved_byte_array(self.context, argument) is None:
                    self.error("byte-array-conversion-type", f"{name} requires a one-dimensional ARRAY OF BYTE.", argument)
                result_types = {BYTES_TO_STRING[name]}
            else:
                sources = self.context.candidates(argument)
                literal = string_literal_type(argument)
                if literal is not None:
                    sources = sources | {literal}
                if not any(t.name == STRING_TO_BYTES[name].name for t in sources):
                    self.error("byte-array-conversion-type", f"{name} requires {STRING_TO_BYTES[name].name}.", argument)
                current = call
                while id(current) in parents and parents[id(current)].get("name") != "assignment_statement":
                    parent = parents[id(current)]
                    if len(direct_children(parent)) != 1:
                        break
                    current = parent
                assignment = parents.get(id(current))
                target = direct_children(assignment)[0] if assignment and assignment.get("name") == "assignment_statement" else None
                result_types = self.context.candidates(target) if target is not None else set()
                if target is None or resolved_byte_array(self.context, target) is None:
                    self.error("byte-array-conversion-destination", f"Assign {name} directly to a one-dimensional ARRAY OF BYTE.", call)
            self.context.candidate_types[id(call)] = set(result_types)
            touched.append(call)
        for call in touched:
            current = call
            candidates = self.context.candidates(call)
            while candidates:
                self.context.candidate_types[id(current)] = set(candidates)
                if len(candidates) == 1:
                    self.context.set_type(current, next(iter(candidates)))
                parent = parents.get(id(current))
                if parent is None or len(direct_children(parent)) != 1:
                    break
                current = parent
        return self.context
