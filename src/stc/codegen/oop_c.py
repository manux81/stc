# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Portable C ABI for IEC 61131-3 Edition 3 classes and interfaces."""
from __future__ import annotations


def _key(value):
    return str(value or "").casefold()


class OOPCEmitter:
    """Lower IEC Ed.3 OOP to C structs, vtables and interface fat pointers."""

    def __init__(self, generator):
        self.g = generator
        self.classes = {}
        self.interfaces = {}

    @property
    def has_oop(self):
        return bool(self.classes or self.interfaces)

    def prepare(self, library):
        if self.g.context is not None and self.g.context.oop_types:
            self.classes = self.g.context.oop_types.get("classes", {})
            self.interfaces = self.g.context.oop_types.get("interfaces", {})
        else:
            # Code generation normally runs after semantic analysis. Keep an
            # empty model rather than guessing a hierarchy when --no-check is
            # used.
            self.classes = {}
            self.interfaces = {}

    def emit_declarations(self, library):
        if not self.has_oop:
            return

        # Forward declarations break the class/interface naming cycle while
        # keeping by-value class instances strongly typed.
        for cls in self.classes.values():
            self.g.text += f"typedef struct {cls['name']} {cls['name']};\n"
        for iface in self.interfaces.values():
            self.g.text += f"typedef struct {iface['name']} {iface['name']};\n"
            self.g.text += (
                f"typedef struct {iface['name']}__vtable "
                f"{iface['name']}__vtable;\n"
            )
        self.g.text += "\n"

        for iface in self.interfaces.values():
            self._emit_interface(iface)
        for cls in self._class_order():
            self._emit_class(cls)

    def _emit_interface(self, iface):
        methods = self._all_interface_methods(iface)
        self.g.text += f"struct {iface['name']}__vtable {{\n"
        for method in methods:
            ret, params = self._method_signature(method["node"])
            suffix = ", " + ", ".join(params) if params else ""
            self.g.text += (
                f"    {ret} (*{method['name']})(void *instance{suffix});\n"
            )
        if not methods:
            self.g.text += "    uint8_t _stc_empty;\n"
        self.g.text += "};\n"
        self.g.text += f"struct {iface['name']} {{\n"
        self.g.text += "    void *instance;\n"
        self.g.text += f"    const {iface['name']}__vtable *vtable;\n"
        self.g.text += "};\n\n"

    def _emit_class(self, cls):
        name = cls["name"]
        base = self._class(cls.get("base"))
        own_fields = self._own_fields(cls)

        # Prototypes must precede vtable initializers.
        for method in cls["methods"]:
            if method["abstract"]:
                continue
            ret, params = self._method_signature(method["node"])
            suffix = ", " + ", ".join(params) if params else ""
            self.g.text += (
                f"static {ret} {name}__{method['name']}"
                f"(void *instance{suffix});\n"
            )
        if cls["methods"]:
            self.g.text += "\n"

        self.g.text += f"struct {name} {{\n"
        if base is None:
            self.g.text += "    const void *__vptr;\n"
        else:
            self.g.text += f"    {base['name']} __base;\n"
        for var_type, field in own_fields:
            self.g.text += f"    {self.g._format_declarator(var_type, field)};\n"
        if base is None and not own_fields:
            self.g.text += "    uint8_t _stc_empty;\n"
        self.g.text += "};\n\n"

        all_methods = self._all_class_methods(cls)
        self.g.text += f"typedef struct {name}__vtable {{\n"
        for method in all_methods:
            ret, params = self._method_signature(method["node"])
            suffix = ", " + ", ".join(params) if params else ""
            self.g.text += (
                f"    {ret} (*{method['name']})(void *instance{suffix});\n"
            )
        if not all_methods:
            self.g.text += "    uint8_t _stc_empty;\n"
        self.g.text += f"}} {name}__vtable;\n"

        self.g.text += f"static const {name}__vtable {name}__dispatch = {{\n"
        for method in all_methods:
            impl = self._implementation_for(cls, method["key"])
            value = (
                "NULL"
                if impl is None or impl["abstract"]
                else f"{impl['owner']}__{impl['name']}"
            )
            self.g.text += f"    .{method['name']} = {value},\n"
        if not all_methods:
            self.g.text += "    ._stc_empty = 0,\n"
        self.g.text += "};\n\n"

        for iface in self._implemented_interfaces(cls):
            methods = self._all_interface_methods(iface)
            self.g.text += (
                f"static const {iface['name']}__vtable "
                f"{name}__{iface['name']}__dispatch = {{\n"
            )
            for method in methods:
                impl = self._implementation_for(cls, method["key"])
                value = (
                    "NULL"
                    if impl is None or impl["abstract"]
                    else f"{impl['owner']}__{impl['name']}"
                )
                self.g.text += f"    .{method['name']} = {value},\n"
            if not methods:
                self.g.text += "    ._stc_empty = 0,\n"
            self.g.text += "};\n"
            self.g.text += (
                f"static inline {iface['name']} "
                f"{name}__as_{iface['name']}({name} *self)\n{{\n"
                f"    return ({iface['name']}){{ self, "
                f"&{name}__{iface['name']}__dispatch }};\n"
                "}\n\n"
            )

        self._emit_class_initializer(cls, own_fields)
        for method in cls["methods"]:
            if not method["abstract"]:
                self._emit_method(cls, method)

    def _emit_class_initializer(self, cls, own_fields):
        name = cls["name"]
        base = self._class(cls.get("base"))
        self.g.text += f"void {name}__init({name} *self)\n{{\n"
        if base is None:
            self.g.text += "    memset(self, 0, sizeof(*self));\n"
        else:
            self.g.text += "    memset(self, 0, sizeof(*self));\n"
            self.g.text += f"    {base['name']}__init(&self->__base);\n"
        self.g.text += (
            f"    self->{self._vptr_path(cls)} = &{name}__dispatch;\n"
        )
        for var_type, field in own_fields:
            self.emit_field_initializer(
                var_type,
                f"&self->{field}",
                self.g.text_append,
                indent="    ",
            )
        self.g.text += "}\n\n"

    def _emit_method(self, cls, method):
        name = cls["name"]
        ret, params = self._method_signature(method["node"])
        suffix = ", " + ", ".join(params) if params else ""
        self.g.text += (
            f"static {ret} {name}__{method['name']}"
            f"(void *instance{suffix})\n{{\n"
        )
        self.g.text += f"    {name} *self = ({name} *)instance;\n"
        self.g.text += "    (void)self;\n"

        return_type_node = self.g._first_named(
            method["node"], "function_return_type"
        )
        if return_type_node is not None:
            self.g.text += (
                f"    {self.g._format_declarator(ret, method['name'])} = "
                f"{self.g.zero_value(ret)};\n"
            )
        locals_ = self.g.collect_sections(method["node"], "function_var_decls")
        temps = self.g.collect_sections(method["node"], "temp_var_decls")
        for var_type, var_name in locals_ + temps:
            self.g.text += (
                f"    {self.g._format_declarator(var_type, var_name)} = {{0}};\n"
            )
            self.emit_field_initializer(
                var_type,
                f"&{var_name}",
                self.g.text_append,
                indent="    ",
            )

        previous_instance = self.g.current_instance
        previous_fields = self.g.current_instance_fields
        previous_paths = self.g.current_instance_field_paths
        previous_pointers = self.g.current_pointer_params
        self.g.current_instance = "self"
        field_paths = self._field_paths(cls)
        self.g.current_instance_fields = set(field_paths)
        self.g.current_instance_field_paths = field_paths
        inouts = self.g.collect_sections(
            method["node"], "input_output_declarations"
        )
        outputs = self.g.collect_sections(method["node"], "output_declarations")
        self.g.current_pointer_params = {
            item.casefold() for _, item in inouts + outputs
        }

        body = self.g._first_named(method["node"], "function_body")
        if body is not None:
            old_indent = self.g.indent
            self.g.indent = "    "
            self.g.visit(body)
            self.g.indent = old_indent

        self.g.current_instance = previous_instance
        self.g.current_instance_fields = previous_fields
        self.g.current_instance_field_paths = previous_paths
        self.g.current_pointer_params = previous_pointers

        if return_type_node is not None:
            self.g.text += f"    return {method['name']};\n"
        self.g.text += "}\n\n"

    def emit_assignment(self, node):
        if self.g.context is None:
            return False
        info = self.g.context.oop_assignments.get(id(node))
        if info is None:
            return False
        children = [
            child for child in node.get("children", [])
            if isinstance(child, dict)
        ]
        if len(children) < 2:
            return False
        target = self.g.render(children[0])
        source = self.g.render(children[-1])
        self.g.text += (
            f"{self.g.indent}{target} = "
            f"{info['class']}__as_{info['interface']}(&({source}));\n"
        )
        return True

    def render_invocation(self, node):
        if node is None or self.g.context is None:
            return "/* unresolved method */ (void)0"
        resolution = self.g.context.resolved_methods.get(id(node))
        if resolution is None:
            return "/* unresolved method */ (void)0"

        receiver = self.g._first_named(node, "method_receiver")
        method = resolution["method"]
        args = [
            child for child in node.get("children", [])
            if isinstance(child, dict) and child.get("name") == "param_assignment"
        ]
        arg_text = []
        for arg in args:
            expressions = self.g._named_nodes(arg, "expression")
            if expressions:
                arg_text.append(self.g.render(expressions[-1]))
        suffix = ", " + ", ".join(arg_text) if arg_text else ""

        receiver_kind = resolution["receiver_kind"]
        static_type = resolution["receiver_type"]
        if receiver_kind == "SUPER":
            return (
                f"{static_type}__{method['name']}((void *)self{suffix})"
            )

        if receiver_kind == "THIS":
            cls = self._class(static_type)
            vptr = f"self->{self._vptr_path(cls)}"
            return (
                f"((const {static_type}__vtable *)({vptr}))"
                f"->{method['name']}((void *)self{suffix})"
            )

        variable = self.g._first_named(receiver, "variable_name")
        expression = self.g.render(variable) if variable is not None else "0"
        if resolution["interface"]:
            return (
                f"({expression}).vtable->{method['name']}"
                f"(({expression}).instance{suffix})"
            )

        cls = self._class(static_type)
        vptr_path = self._vptr_path(cls)
        return (
            f"((const {static_type}__vtable *)"
            f"(({expression}).{vptr_path}))->{method['name']}"
            f"((void *)&({expression}){suffix})"
        )

    def emit_field_initializer(self, var_type, address, append, indent="    "):
        cls = self._class(var_type)
        if cls is not None:
            append(f"{indent}{cls['name']}__init({address});\n")

    def _method_signature(self, node):
        return_node = self.g._first_named(node, "function_return_type")
        ret = self.g.declaration_type(return_node, "void") if return_node else "void"
        inputs = self.g.collect_sections(node, "input_declarations")
        outputs = self.g.collect_sections(node, "output_declarations")
        inouts = self.g.collect_sections(node, "input_output_declarations")
        params = [
            self.g._format_declarator(var_type, var_name)
            for var_type, var_name in inputs
        ]
        params += [
            self.g._format_declarator(var_type, var_name, pointer=True)
            for var_type, var_name in outputs + inouts
        ]
        return ret, params

    def _own_fields(self, cls):
        result = []

        def collect(node):
            if not isinstance(node, dict):
                return
            if node.get("name") in {"method_declaration", "method_prototype"}:
                return
            if node.get("name") in {
                "input_declarations", "output_declarations",
                "input_output_declarations", "var_declarations",
                "retentive_var_declarations", "non_retentive_var_decls",
            }:
                result.extend(self.g.collect_var_decls(node))
                return
            for child in node.get("children", []):
                collect(child)

        collect(cls["node"])
        return self.g._unique_declarations(result)

    def _field_paths(self, cls):
        result = {}
        base = self._class(cls.get("base"))
        if base is not None:
            for key, path in self._field_paths(base).items():
                result[key] = "__base." + path
        for _, field in self._own_fields(cls):
            result[field.casefold()] = field
        return result

    def _vptr_path(self, cls):
        base = self._class(cls.get("base")) if cls else None
        return "__vptr" if base is None else "__base." + self._vptr_path(base)

    def _class(self, value):
        if isinstance(value, dict):
            return value
        return self.classes.get(_key(value))

    def _all_class_methods(self, cls):
        result = []
        positions = {}
        base = self._class(cls.get("base"))
        if base is not None:
            for method in self._all_class_methods(base):
                positions[method["key"]] = len(result)
                result.append(method)
        for method in cls["methods"]:
            item = dict(method)
            item["owner"] = cls["name"]
            if item["key"] in positions:
                result[positions[item["key"]]] = item
            else:
                positions[item["key"]] = len(result)
                result.append(item)
        return result

    def _implementation_for(self, cls, key):
        current = cls
        while current is not None:
            for method in current["methods"]:
                if method["key"] == key:
                    item = dict(method)
                    item["owner"] = current["name"]
                    return item
            current = self._class(current.get("base"))
        return None

    def _all_interface_methods(self, iface):
        result = []
        positions = {}
        for parent_name in iface.get("extends", []):
            parent = self.interfaces.get(_key(parent_name))
            if parent is not None:
                for method in self._all_interface_methods(parent):
                    if method["key"] not in positions:
                        positions[method["key"]] = len(result)
                        result.append(method)
        for method in iface["methods"]:
            if method["key"] in positions:
                result[positions[method["key"]]] = method
            else:
                positions[method["key"]] = len(result)
                result.append(method)
        return result

    def _implemented_interfaces(self, cls):
        result = {}
        base = self._class(cls.get("base"))
        if base is not None:
            for iface in self._implemented_interfaces(base):
                result[iface["key"]] = iface
        for name in cls.get("interfaces", []):
            iface = self.interfaces.get(_key(name))
            if iface is not None:
                result[iface["key"]] = iface
                for parent_name in iface.get("extends", []):
                    parent = self.interfaces.get(_key(parent_name))
                    if parent is not None:
                        result[parent["key"]] = parent
        return list(result.values())

    def _class_order(self):
        result = []
        emitted = set()

        def emit(cls):
            if cls["key"] in emitted:
                return
            base = self._class(cls.get("base"))
            if base is not None:
                emit(base)
            emitted.add(cls["key"])
            result.append(cls)

        for cls in self.classes.values():
            emit(cls)
        return result
