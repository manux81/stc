# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Render checked string/byte-array intrinsics through backend templates."""
from ...semantic.checks.byte_arrays import conversion_call, STRING_TO_BYTES, BYTES_TO_STRING, resolved_byte_array


def array_size(generator, expression):
    t = resolved_byte_array(generator.context, expression)
    if t is None:
        raise ValueError("Byte-array conversion requires checked array bounds")
    return t.dimensions[0].upper - t.dimensions[0].lower + 1


def emit_store(generator, node):
    children = node.get("children", [])
    if len(children) < 2:
        return False
    target, expression = children[0], children[-1]
    match = conversion_call(expression)
    if match is None or match[1] not in STRING_TO_BYTES:
        return False
    _, name, arguments = match
    generator.text += generator.generator_engine.render("byte_array_store", name=name,
        source=generator.render(arguments[0]), target=generator.render(target),
        size=str(array_size(generator, target)), indent=generator.indent)
    return True


def emit_call(generator, node):
    match = conversion_call(node)
    if match is None or match[0] is not node or match[1] not in BYTES_TO_STRING:
        return False
    _, name, arguments = match
    generator.text += generator.generator_engine.render("byte_array_load", name=name,
        source=generator.render(arguments[0]), size=str(array_size(generator, arguments[0])))
    return True
