# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""IEC 61131-3 Edition 3 object-oriented semantic analysis.

The pass keeps the language model independent from the C ABI.  It validates
CLASS/INTERFACE hierarchies and records enough information for backends to
perform static or dynamic method dispatch.
"""
from __future__ import annotations

from ..symbol_table import ScopeKind, normalize_identifier
from ..types import UNKNOWN_TYPE
from .base import SemanticCheck, SemanticPhase, direct_children, register_check, walk


def _first(node, name):
    return next((item for item in walk(node) if item.get("name") == name), None)


def _all(node, name):
    return [item for item in walk(node) if item.get("name") == name]


def _direct_value(node, name):
    for child in direct_children(node):
        if child.get("name") == name:
            return child.get("value")
    return None


def _tokens(node):
    return {
        str(item.get("value", "")).upper()
        for item in walk(node)
        if item.get("name") == "token"
    }


def _type_name(node):
    if node is None:
        return None
    for item in walk(node):
        if item is node:
            continue
        name = item.get("name", "")
        value = item.get("value")
        if isinstance(value, str) and (
            name.endswith("_type_name")
            or value.upper() in {
                "BOOL", "SINT", "INT", "DINT", "LINT", "USINT", "UINT",
                "UDINT", "ULINT", "REAL", "LREAL", "BYTE", "WORD", "DWORD",
                "LWORD", "STRING", "WSTRING", "USTRING", "CHAR", "WCHAR",
                "UCHAR", "TIME", "LTIME", "DATE", "LDATE", "TOD", "LTOD",
                "DT", "LDT",
            }
        ):
            return value
    return None


def _method_signature(node):
    result = _type_name(_first(node, "function_return_type"))
    params = []
    section_kinds = (
        ("input_declarations", "in"),
        ("output_declarations", "out"),
        ("input_output_declarations", "inout"),
    )
    for section_name, direction in section_kinds:
        for section in _all(node, section_name):
            for declaration in walk(section):
                if declaration.get("name") not in {
                    "var1_init_decl", "var1_declaration", "array_var_init_decl",
                    "array_var_declaration", "structured_var_init_decl",
                    "structured_var_declaration", "string_var_declaration",
                }:
                    continue
                datatype = _type_name(declaration)
                names = [
                    item.get("value")
                    for item in walk(declaration)
                    if item.get("name") == "variable_name"
                    and isinstance(item.get("value"), str)
                ]
                params.extend((direction, name.casefold(), datatype) for name in names)
    return (result, tuple(params))


def _method_info(node):
    name_node = _first(node, "method_name")
    name = name_node.get("value") if name_node else "<method>"
    tokens = _tokens(node)
    modifier = _direct_value(node, "method_modifier")
    return {
        "name": name,
        "key": normalize_identifier(name),
        "node": node,
        "signature": _method_signature(node),
        "final": modifier == "FINAL" or "FINAL" in tokens,
        "abstract": modifier == "ABSTRACT" or "ABSTRACT" in tokens,
        "override": "OVERRIDE" in tokens,
    }


def _class_info(node):
    names = _all(node, "class_type_name")
    name = names[0].get("value") if names else "<class>"
    base = names[1].get("value") if len(names) > 1 else None
    iface_list = _first(node, "interface_name_list")
    interfaces = (
        [item.get("value") for item in _all(iface_list, "interface_type_name")]
        if iface_list is not None else []
    )
    modifier = _direct_value(node, "class_modifier")
    return {
        "kind": "class",
        "name": name,
        "key": normalize_identifier(name),
        "node": node,
        "base": base,
        "interfaces": interfaces,
        "final": modifier == "FINAL",
        "abstract": modifier == "ABSTRACT",
        "methods": [_method_info(item) for item in _all(node, "method_declaration")],
    }


def _interface_info(node):
    names = _all(node, "interface_type_name")
    name = names[0].get("value") if names else "<interface>"
    extends_list = _first(node, "interface_name_list")
    extends = (
        [item.get("value") for item in _all(extends_list, "interface_type_name")]
        if extends_list is not None else []
    )
    methods = []
    for item in _all(node, "method_prototype"):
        info = _method_info(item)
        info["abstract"] = True
        methods.append(info)
    return {
        "kind": "interface",
        "name": name,
        "key": normalize_identifier(name),
        "node": node,
        "extends": extends,
        "methods": methods,
    }


@register_check(
    name="edition3-oop",
    phase=SemanticPhase.DECLARATIONS,
    after=("collect-types",),
)
class Edition3ObjectOrientedCheck(SemanticCheck):
    """Validate Ed.3 OOP declarations and resolve interface/method operations."""

    def run(self, ast):
        classes = {
            info["key"]: info
            for info in (
                _class_info(node)
                for node in walk(ast)
                if node.get("name") == "class_declaration"
            )
        }
        interfaces = {
            info["key"]: info
            for info in (
                _interface_info(node)
                for node in walk(ast)
                if node.get("name") == "interface_declaration"
            )
        }
        self.context.oop_types = {"classes": classes, "interfaces": interfaces}

        self._validate_interfaces(interfaces)
        self._validate_classes(classes, interfaces)
        self._resolve_invocations(ast, classes, interfaces)
        self._resolve_interface_assignments(ast, classes, interfaces)
        return self.context

    def _validate_interfaces(self, interfaces):
        for interface in interfaces.values():
            for parent_name in interface["extends"]:
                if normalize_identifier(parent_name) not in interfaces:
                    self.error(
                        "unknown-interface",
                        f"Unknown parent interface '{parent_name}'.",
                        interface["node"],
                    )

    def _validate_classes(self, classes, interfaces):
        for cls in classes.values():
            base = self._class(classes, cls["base"])
            if cls["base"] and base is None:
                self.error(
                    "unknown-base-class",
                    f"Unknown base class '{cls['base']}'.",
                    cls["node"],
                )
            elif base is not None and base["final"]:
                self.error(
                    "extends-final-class",
                    f"Class '{cls['name']}' cannot extend FINAL class '{base['name']}'.",
                    cls["node"],
                )

            for iface_name in cls["interfaces"]:
                if normalize_identifier(iface_name) not in interfaces:
                    self.error(
                        "unknown-interface",
                        f"Class '{cls['name']}' implements unknown interface '{iface_name}'.",
                        cls["node"],
                    )

            for method in cls["methods"]:
                inherited = self._lookup_base_method(classes, cls, method["key"])
                if method["override"]:
                    if inherited is None:
                        self.error(
                            "invalid-override",
                            f"Method '{cls['name']}.{method['name']}' is marked OVERRIDE "
                            "but no inherited method exists.",
                            method["node"],
                        )
                    elif inherited["final"]:
                        self.error(
                            "override-final-method",
                            f"Method '{method['name']}' overrides a FINAL method.",
                            method["node"],
                        )
                    elif inherited["signature"] != method["signature"]:
                        self.error(
                            "override-signature-mismatch",
                            f"Override '{cls['name']}.{method['name']}' does not preserve "
                            "the inherited signature.",
                            method["node"],
                        )
                elif inherited is not None:
                    self.error(
                        "missing-override",
                        f"Method '{cls['name']}.{method['name']}' replaces an inherited "
                        "method and must be declared OVERRIDE.",
                        method["node"],
                    )

            if not cls["abstract"]:
                for method in self._all_class_methods(classes, cls).values():
                    if method["abstract"]:
                        self.error(
                            "unimplemented-abstract-method",
                            f"Concrete class '{cls['name']}' does not implement abstract "
                            f"method '{method['name']}'.",
                            cls["node"],
                        )
                for iface in self._implemented_interfaces(classes, interfaces, cls):
                    available = self._all_class_methods(classes, cls)
                    for method in self._all_interface_methods(interfaces, iface).values():
                        candidate = available.get(method["key"])
                        if candidate is None or candidate["signature"] != method["signature"]:
                            self.error(
                                "unimplemented-interface-method",
                                f"Class '{cls['name']}' does not implement "
                                f"'{iface['name']}.{method['name']}' with a compatible signature.",
                                cls["node"],
                            )

        # Detect inheritance cycles independently of declaration order.
        for cls in classes.values():
            seen = set()
            current = cls
            while current is not None:
                if current["key"] in seen:
                    self.error(
                        "cyclic-class-inheritance",
                        f"Cyclic inheritance involving class '{cls['name']}'.",
                        cls["node"],
                    )
                    break
                seen.add(current["key"])
                current = self._class(classes, current["base"])

    def _resolve_invocations(self, ast, classes, interfaces):
        for invocation in (
            node for node in walk(ast) if node.get("name") == "method_invocation"
        ):
            receiver = _first(invocation, "method_receiver")
            method_node = _first(invocation, "method_name")
            if receiver is None or method_node is None:
                continue
            method_name = method_node.get("value")
            method_key = normalize_identifier(method_name)

            receiver_kind = str(receiver.get("value", "variable")).upper()
            receiver_type = None
            if receiver_kind in {"THIS", "SUPER"}:
                scope = self.context.symbols.scope_for(invocation)
                while scope is not None and scope.kind != ScopeKind.CLASS:
                    scope = scope.parent
                if scope is not None:
                    receiver_type = scope.name
                    if receiver_kind == "SUPER":
                        current = classes.get(normalize_identifier(receiver_type))
                        receiver_type = current["base"] if current is not None else None
            else:
                variable = _first(receiver, "variable_name")
                symbol = (
                    self.context.symbols.symbol_for_reference(variable)
                    if variable is not None else None
                )
                if symbol is not None and symbol.type_ref is not None:
                    receiver_type = symbol.type_ref.name

            key = normalize_identifier(receiver_type or "")
            resolution = None
            if key in classes:
                cls = classes[key]
                method = self._all_class_methods(classes, cls).get(method_key)
                if method is not None:
                    resolution = {
                        "receiver_kind": receiver_kind,
                        "receiver_type": cls["name"],
                        "method": method,
                        "interface": False,
                    }
            elif key in interfaces:
                iface = interfaces[key]
                method = self._all_interface_methods(interfaces, iface).get(method_key)
                if method is not None:
                    resolution = {
                        "receiver_kind": receiver_kind,
                        "receiver_type": iface["name"],
                        "method": method,
                        "interface": True,
                    }

            if resolution is None:
                self.error(
                    "unknown-method",
                    f"Cannot resolve method '{method_name}' for receiver "
                    f"type '{receiver_type or '<unknown>'}'.",
                    invocation,
                )
                continue

            self.context.resolved_methods[id(invocation)] = resolution
            result_name = resolution["method"]["signature"][0]
            if result_name:
                datatype = self.context.declared_types.get(
                    normalize_identifier(result_name),
                    UNKNOWN_TYPE,
                )
                self.context.candidate_types[id(invocation)] = {datatype}

    def _resolve_interface_assignments(self, ast, classes, interfaces):
        for assignment in (
            node for node in walk(ast) if node.get("name") == "assignment_statement"
        ):
            children = direct_children(assignment)
            if len(children) < 2:
                continue
            target_var = _first(children[0], "variable_name")
            source_var = _first(children[-1], "variable_name")
            if target_var is None or source_var is None:
                continue
            target_symbol = self.context.symbols.symbol_for_reference(target_var)
            source_symbol = self.context.symbols.symbol_for_reference(source_var)
            if (
                target_symbol is None or source_symbol is None
                or target_symbol.type_ref is None or source_symbol.type_ref is None
            ):
                continue
            target_key = normalize_identifier(target_symbol.type_ref.name or "")
            source_key = normalize_identifier(source_symbol.type_ref.name or "")
            if target_key not in interfaces or source_key not in classes:
                continue
            cls = classes[source_key]
            iface = interfaces[target_key]
            implemented = {
                item["key"]
                for item in self._implemented_interfaces(classes, interfaces, cls)
            }
            if iface["key"] not in implemented:
                self.error(
                    "interface-assignment",
                    f"Class '{cls['name']}' does not implement interface '{iface['name']}'.",
                    assignment,
                )
                continue
            self.context.oop_assignments[id(assignment)] = {
                "class": cls["name"],
                "interface": iface["name"],
            }

    @staticmethod
    def _class(classes, name):
        return classes.get(normalize_identifier(name)) if name else None

    def _lookup_base_method(self, classes, cls, key):
        current = self._class(classes, cls["base"])
        while current is not None:
            own = {item["key"]: item for item in current["methods"]}
            if key in own:
                return own[key]
            current = self._class(classes, current["base"])
        return None

    def _all_class_methods(self, classes, cls):
        result = {}
        base = self._class(classes, cls["base"])
        if base is not None:
            result.update(self._all_class_methods(classes, base))
        for method in cls["methods"]:
            result[method["key"]] = method
        return result

    def _all_interface_methods(self, interfaces, iface):
        result = {}
        for parent_name in iface["extends"]:
            parent = interfaces.get(normalize_identifier(parent_name))
            if parent is not None:
                result.update(self._all_interface_methods(interfaces, parent))
        for method in iface["methods"]:
            result[method["key"]] = method
        return result

    def _implemented_interfaces(self, classes, interfaces, cls):
        result = {}
        base = self._class(classes, cls["base"])
        if base is not None:
            for iface in self._implemented_interfaces(classes, interfaces, base):
                result[iface["key"]] = iface
        for name in cls["interfaces"]:
            iface = interfaces.get(normalize_identifier(name))
            if iface is None:
                continue
            result[iface["key"]] = iface
            for parent in iface["extends"]:
                inherited = interfaces.get(normalize_identifier(parent))
                if inherited is not None:
                    result[inherited["key"]] = inherited
        return list(result.values())
