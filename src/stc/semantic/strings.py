# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared capacity metadata for IEC string variables."""


def _walk(node):
    if isinstance(node, dict):
        yield node
        for child in node.get("children", []):
            yield from _walk(child)


def string_spec(symbol):
    if symbol is None or symbol.type_ref is None:
        return None
    kind = str(symbol.type_ref.name or "").upper()
    if kind not in {"STRING", "WSTRING", "USTRING"}:
        return None
    size = next((n for n in _walk(symbol.type_ref.node) if n.get("name") == "integer"), None)
    capacity = int(str(size["value"]).replace("_", "")) if size else 80
    return kind, capacity


def target_string_spec(context, node):
    if context is None:
        return None
    variable = next((n for n in _walk(node) if n.get("name") == "variable_name"), None)
    if variable is None:
        return None
    symbol = context.symbols.symbol_for_reference(variable)
    # Field selections must use the field's declaration, never the receiver's capacity.
    for field in (n for n in _walk(node) if n.get("name") == "field_selector"):
        if symbol is None or symbol.type_ref is None:
            return None
        owner = next((s for s in context.symbols.iter_scopes()
                      if s.name.casefold() == str(symbol.type_ref.name).casefold()), None)
        symbol = owner.lookup_local(str(field.get("value", ""))) if owner else None
    return string_spec(symbol)
