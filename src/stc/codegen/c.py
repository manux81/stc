# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate portable C code from the analyzed Structured Text AST."""

import re

from .visitor import NodeVisitor
from .sfc import charts as sfc_charts, field as sfc_field, state_declarations as sfc_state_declarations
from .generator.engine import GeneratorEngine
from .generator.ir import Assignment, Call, Cast, IfBranch, Literal, RepeatLoop, UnaryExpression, WhileLoop
from .generator.loader import GeneratorBundle, bundled_generator, load_generator
from ..runtime.loader import render_primitives


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
        engine = self.g.generator_engine
        for cls in self.classes.values():
            self.g.text += engine.render(
                "class_predecl", name=cls["name"], kind="class"
            )
        for iface in self.interfaces.values():
            self.g.text += engine.render(
                "class_predecl", name=iface["name"], kind="interface"
            )
        self.g.text += "\n"

        for iface in self.interfaces.values():
            self._emit_interface(iface)
        for cls in self._class_order():
            self._emit_class(cls)

    def _emit_interface(self, iface):
        engine = self.g.generator_engine
        methods = self._all_interface_methods(iface)
        rendered = []
        for method in methods:
            ret, suffix = self._method_signature(method["node"])
            rendered.append(
                engine.render(
                    "interface_method",
                    name=method["name"],
                    return_type=ret,
                    parameters=suffix,
                )
            )
        methods_text = "".join(rendered)
        if not methods:
            methods_text = engine.render("class_empty_field", empty="1")
        self.g.text += engine.render(
            "interface", name=iface["name"], bases="", methods=methods_text
        )

    def _emit_class(self, cls):
        engine = self.g.generator_engine
        name = cls["name"]
        base = self._class(cls.get("base"))
        has_base = "1" if base is not None else ""
        no_base = "" if base is not None else "1"
        own_fields = self._own_fields(cls)

        # Prototypes must precede vtable initializers.
        prototypes = ""
        for method in cls["methods"]:
            if method["abstract"]:
                continue
            ret, suffix = self._method_signature(method["node"])
            prototypes += engine.render(
                "class_prototype",
                **{"class": name},
                name=method["name"],
                return_type=ret,
                parameters=suffix,
            )

        fields_text = engine.render(
            "class_fields",
            items=[{"type": var_type, "name": field} for var_type, field in own_fields],
        )
        base_field = engine.render(
            "class_base_field", base=base["name"] if base else "", has_base=has_base
        )
        vptr_field = engine.render("class_vptr_field", no_base=no_base)
        empty_field = engine.render(
            "class_empty_field",
            empty="1" if (base is None and not own_fields) else "",
        )

        all_methods = self._all_class_methods(cls)
        vtable_entries = []
        for method in all_methods:
            ret, suffix = self._method_signature(method["node"])
            vtable_entries.append(
                engine.render(
                    "vtable_entry",
                    return_type=ret,
                    name=method["name"],
                    parameters=suffix,
                )
            )
        vtable_text = "".join(vtable_entries)
        if not all_methods:
            vtable_text = engine.render("class_empty_field", empty="1")

        dispatch_entries = []
        for method in all_methods:
            impl = self._implementation_for(cls, method["key"])
            if impl is None or impl["abstract"]:
                dispatch_entries.append(
                    engine.render("dispatch_entry_null", name=method["name"])
                )
            else:
                dispatch_entries.append(
                    engine.render(
                        "dispatch_entry",
                        name=method["name"],
                        implementation=f"{impl['owner']}__{impl['name']}",
                        is_null="",
                    )
                )
        dispatch_text = "".join(dispatch_entries)
        if not all_methods:
            dispatch_text = engine.render("empty_dispatch")

        adapters = ""
        for iface in ([] if cls["abstract"] else self._implemented_interfaces(cls)):
            methods = self._all_interface_methods(iface)
            entries = []
            for method in methods:
                impl = self._implementation_for(cls, method["key"])
                if impl is None or impl["abstract"]:
                    entries.append(
                        engine.render("adapter_entry_null", name=method["name"])
                    )
                else:
                    entries.append(
                        engine.render(
                            "adapter_entry",
                            **{"class": name, "interface": iface["name"]},
                            name=method["name"],
                            implementation=f"{impl['owner']}__{impl['name']}",
                            parameters="",
                            arguments="",
                            return_type="",
                        )
                    )
            adapter_methods = "".join(entries)
            if not methods:
                adapter_methods = engine.render("empty_dispatch")
            adapters += engine.render(
                "interface_adapter",
                **{"class": name, "interface": iface["name"]},
                methods=adapter_methods,
            )

        init_text = self._emit_class_initializer(cls, own_fields)
        methods_text = ""
        for method in cls["methods"]:
            if not method["abstract"]:
                methods_text += self._emit_method(cls, method)

        self.g.text += engine.render(
            "class",
            name=name,
            base=base["name"] if base else "",
            has_base=has_base,
            no_base=no_base,
            has_fields="1" if own_fields else "",
            no_fields="" if own_fields else "1",
            fields=fields_text,
            base_field=base_field,
            vptr_field=vptr_field,
            empty_field=empty_field,
            prototypes=prototypes,
            vtable=vtable_text,
            dispatch=dispatch_text,
            adapters=adapters,
            init=init_text,
            methods=methods_text,
            interfaces="",
        )

    def _emit_class_initializer(self, cls, own_fields):
        engine = self.g.generator_engine
        name = cls["name"]
        base = self._class(cls.get("base"))
        base_init = (
            engine.render("class_base_init", base=base["name"]) if base else ""
        )
        statements = self.g._capture_emission(
            lambda: [
                self.emit_field_initializer(
                    var_type,
                    f"&self->{field}",
                    self.g.text_append,
                    indent="    ",
                )
                for var_type, field in own_fields
            ]
        )
        return engine.render(
            "class_init",
            name=name,
            base=base["name"] if base else "",
            has_base="1" if base else "",
            vptr=self._vptr_path(cls),
            base_init=base_init,
            statements=statements,
            defaults="",
        )

    def _emit_method(self, cls, method):
        engine = self.g.generator_engine
        name = cls["name"]
        ret, suffix = self._method_signature(method["node"])

        return_type_node = self.g._first_named(
            method["node"], "function_return_type"
        )
        locals_text = ""
        if return_type_node is not None:
            locals_text += (
                f"    {self.g._format_declarator(ret, method['name'])} = "
                f"{self.g.zero_value(ret)};\n"
            )
        locals_ = self.g.collect_sections(method["node"], "function_var_decls")
        temps = self.g.collect_sections(method["node"], "temp_var_decls")
        nested_inits = []
        for var_type, var_name in locals_ + temps:
            locals_text += (
                f"    {self.g._format_declarator(var_type, var_name)} = {{0}};\n"
            )
            nested = self._class(var_type)
            if nested is not None:
                nested_inits.append(
                    engine.render(
                        "class_init_statement",
                        address=f"&{var_name}",
                        type=var_type,
                        field=var_name,
                        nested=nested["name"],
                        indent="    ",
                        **{"class": nested["name"]},
                    )
                )
        locals_text += "".join(nested_inits)

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

        body_node = self.g._first_named(method["node"], "function_body")
        old_indent = self.g.indent
        self.g.indent = "    "
        if body_node is not None:
            body = self.g._capture_emission(lambda: self.g.visit(body_node))
        else:
            body = ""
        self.g.indent = old_indent

        self.g.current_instance = previous_instance
        self.g.current_instance_fields = previous_fields
        self.g.current_instance_field_paths = previous_paths
        self.g.current_pointer_params = previous_pointers

        return_stmt = (
            engine.render("method_return", name=method["name"], indent="    ")
            if return_type_node is not None
            else ""
        )
        return engine.render(
            "class_method",
            **{"class": name},
            name=method["name"],
            return_type=ret,
            receiver="",
            parameters=suffix,
            locals=locals_text,
            body=body,
            has_return="1" if return_type_node is not None else "",
            return_stmt=return_stmt,
        )

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
        self.g.text += self.g.generator_engine.render(
            "interface_assignment",
            target=target,
            source=source,
            indent=self.g.indent,
            **{"class": info["class"], "interface": info["interface"]},
        )
        return True

    def _invocation_arguments(self, node):
        args = [
            child for child in node.get("children", [])
            if isinstance(child, dict) and child.get("name") == "param_assignment"
        ]
        arg_text = []
        for arg in args:
            expressions = self.g._named_nodes(arg, "expression")
            if expressions:
                arg_text.append(self.g.render(expressions[-1]))
        bare = ", ".join(arg_text)
        return bare, (", " + bare if bare else "")

    def render_invocation(self, node):
        if node is None or self.g.context is None:
            return "/* unresolved method */ (void)0"
        resolution = self.g.context.resolved_methods.get(id(node))
        if resolution is None:
            return "/* unresolved method */ (void)0"

        receiver = self.g._first_named(node, "method_receiver")
        method = resolution["method"]
        bare, suffix = self._invocation_arguments(node)

        receiver_kind = resolution["receiver_kind"]
        static_type = resolution["receiver_type"]
        engine = self.g.generator_engine
        if receiver_kind == "SUPER":
            return engine.render(
                "virtual_call_super",
                receiver="self",
                method=method["name"],
                static_type=static_type,
                vptr="",
                arguments=bare,
                extra_arguments=suffix,
            )

        if receiver_kind == "THIS":
            cls = self._class(static_type)
            vptr = self._vptr_path(cls)
            return engine.render(
                "virtual_call_this",
                receiver="self",
                method=method["name"],
                static_type=static_type,
                vptr=vptr,
                arguments=bare,
                extra_arguments=suffix,
            )

        variable = self.g._first_named(receiver, "variable_name")
        expression = self.g.render(variable) if variable is not None else "0"
        if resolution["interface"]:
            return engine.render(
                "virtual_call_interface",
                receiver=expression,
                method=method["name"],
                static_type=static_type,
                vptr="",
                arguments=bare,
                extra_arguments=suffix,
            )

        cls = self._class(static_type)
        vptr_path = self._vptr_path(cls)
        return engine.render(
            "virtual_call",
            receiver=expression,
            method=method["name"],
            static_type=static_type,
            vptr=vptr_path,
            arguments=bare,
            extra_arguments=suffix,
        )

    def emit_field_initializer(self, var_type, address, append, indent="    "):
        cls = self._class(var_type)
        if cls is not None:
            engine = self.g.generator_engine
            if engine is not None:
                append(
                    engine.render(
                        "class_init_statement",
                        address=address,
                        type=var_type,
                        field="",
                        nested=cls["name"],
                        indent=indent,
                        **{"class": cls["name"]},
                    )
                )
            else:
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
        engine = self.g.generator_engine
        if engine is not None:
            joined = engine.render(
                "method_parameters", items=[{"value": item} for item in params]
            )
        else:
            joined = ", ".join(params)
        return ret, (", " + joined if joined else "")

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


class CCodeGenerator(NodeVisitor):
    def _il_descendants(self, node, name):
        if not isinstance(node, dict):
            return []
        found = [node] if node.get("name") == name else []
        for child in node.get("children", []):
            found.extend(self._il_descendants(child, name))
        return found

    def _il_token(self, node):
        tokens = self._il_descendants(node, "token")
        return next((str(item.get("value", "")).upper() for item in tokens if item.get("value") != "\u2029"), "")

    def _il_operand_node(self, operation):
        operands = self._il_descendants(operation, "il_operand")
        if not operands:
            return None
        children = [item for item in operands[0].get("children", []) if isinstance(item, dict)]
        return children[0] if children else None

    def _il_render_operand(self, operation):
        operand = self._il_operand_node(operation)
        if operand is None:
            return None
        # The grammar cannot distinguish an unqualified enumeration element
        # from a symbolic variable. Prefer a declared/current-instance name;
        # qualified enum values remain represented by their dedicated node.
        if operand.get("name") == "enumerated_value":
            operand = {"name": "variable_name", "value": operand.get("value", ""), "children": []}
        return self.render(operand)

    def _il_opcode_key(self, opcode):
        """Map an IL opcode to a backend-agnostic operator key.

        IL conjunction is bitwise; the backend operator mapping supplies the
        actual spelling, so no target keyword appears here.
        """
        table = {
            "AND": "BIT_AND", "&": "BIT_AND", "AN": "BIT_AND", "ANDN": "BIT_AND",
            "OR": "BIT_OR", "ORN": "BIT_OR", "XOR": "XOR", "XORN": "XOR",
            "ADD": "ADD", "SUB": "SUB", "MUL": "MUL", "DIV": "DIV", "MOD": "MOD",
            "GT": "GT", "GE": "GE", "EQ": "EQ", "LT": "LT", "LE": "LE",
            "NE": "NE",
        }
        return table.get(opcode, opcode)

    def _il_boolean_not(self, expression):
        return f"{self.generator_engine.map('operator', 'NOT')}({expression})"

    def _il_true(self):
        return self.generator_engine.map("boolean_literal", "TRUE")

    def _il_false(self):
        return self.generator_engine.map("boolean_literal", "FALSE")

    def _il_assignment(self, target, expression):
        return f"{target} = {expression};"

    def _il_emit_line(self, statement):
        self.text += f"{self.indent}{statement}\n"

    def _il_has_jumps(self, instructions):
        jump_opcodes = {"JMP", "JMPC", "JMPCN"}
        for instruction in instructions:
            for child in instruction.get("children", []):
                if isinstance(child, dict) and self._il_token(child) in jump_opcodes:
                    return True
        return False

    def _il_operation(self, instruction):
        return next(
            (child for child in instruction.get("children", []) if isinstance(child, dict) and child.get("name") != "label" and child.get("name") != "token"),
            None,
        )

    def _il_labels(self, instruction):
        return [
            item for item in instruction.get("children", [])
            if isinstance(item, dict) and item.get("name") == "label"
        ]

    def _il_call_arguments(self, operation, accumulator):
        arguments = [accumulator] if accumulator is not None else []
        for item in self._il_descendants(operation, "il_operand"):
            child = next((c for c in item.get("children", []) if isinstance(c, dict)), None)
            if child is not None:
                if child.get("name") == "enumerated_value":
                    child = {"name": "variable_name", "value": child.get("value", ""), "children": []}
                arguments.append(self.render(child))
        return arguments

    def visit_instruction_list(self, node):
        instructions = self._il_descendants(node, "il_instruction")
        if self._il_has_jumps(instructions):
            self._visit_il_dispatch(node, instructions)
        else:
            self._visit_il_linear(node, instructions)

    def _visit_il_linear(self, node, instructions):
        engine = self.generator_engine
        accumulator = None
        terminated = False
        stored_function_result = False
        for instruction in instructions:
            for label in self._il_labels(instruction):
                self.text += engine.render(
                    "il_label", name=label.get("value", ""), indent=self.indent
                )
            operation = self._il_operation(instruction)
            if operation is None:
                continue
            opcode = self._il_token(operation)
            operand = self._il_render_operand(operation)
            if opcode in {"LD", "LDN"} and operand is not None:
                accumulator = self._il_boolean_not(operand) if opcode == "LDN" else operand
            elif opcode in {"ST", "STN"} and operand is not None and accumulator is not None:
                value = self._il_boolean_not(accumulator) if opcode == "STN" else accumulator
                self.text += engine.render(
                    "il_assign", target=operand, value=value, indent=self.indent
                )
                stored_function_result = bool(self.current_function) and operand.casefold() == self.current_function.casefold()
            elif opcode == "NOT" and accumulator is not None:
                accumulator = self._il_boolean_not(accumulator)
            elif opcode in {"ANDN", "AN", "ORN", "XORN"} and accumulator is not None and operand is not None:
                key = {"ANDN": "BIT_AND", "AN": "BIT_AND", "ORN": "BIT_OR", "XORN": "XOR"}[opcode]
                operator = engine.map("operator", key)
                accumulator = f"({accumulator} {operator} {self._il_boolean_not(operand)})"
            elif opcode in {"AND", "&", "OR", "XOR", "ADD", "SUB", "MUL", "DIV", "MOD", "GT", "GE", "EQ", "LT", "LE", "NE"} and accumulator is not None and operand is not None:
                operator = engine.map("operator", self._il_opcode_key(opcode))
                accumulator = f"({accumulator} {operator} {operand})"
            elif opcode in {"S", "S1", "R", "R1"} and accumulator is not None and operand is not None:
                value = self._il_true() if opcode in {"S", "S1"} else self._il_false()
                inner = engine.render(
                    "il_assign", target=operand, value=value, indent=self.indent + "    "
                )
                self.text += engine.render(
                    "il_guarded", condition=accumulator, body=inner, indent=self.indent
                )
            elif opcode in {"JMP", "JMPC", "JMPCN"}:
                labels = self._il_descendants(operation, "label")
                destination = labels[0].get("value", "") if labels else ""
                target_index = self._il_label_index(instructions, destination)
                if opcode == "JMP":
                    self.text += engine.render(
                        "il_jump", target_label=destination, target_index=target_index,
                        condition="", has_condition="", indent=self.indent,
                    )
                elif accumulator is not None:
                    condition = accumulator if opcode == "JMPC" else self._il_boolean_not(accumulator)
                    inner = engine.render(
                        "il_jump", target_label=destination, target_index=target_index,
                        condition="", has_condition="", indent=self.indent + "    ",
                    )
                    self.text += engine.render(
                        "il_guarded", condition=condition, body=inner, indent=self.indent
                    )
            elif opcode in {"RET", "RETC", "RETCN"}:
                condition = None
                if opcode == "RETC" and accumulator is not None:
                    condition = accumulator
                elif opcode == "RETCN" and accumulator is not None:
                    condition = self._il_boolean_not(accumulator)
                if self.current_function and accumulator is not None:
                    value = f" {accumulator}"
                else:
                    value = ""
                statement = engine.render(
                    "il_return", value=value, has_value="1" if value else "",
                    condition=condition or "", has_condition="1" if condition else "",
                    indent=self.indent + "    " if condition else self.indent,
                )
                if condition is None:
                    self.text += statement
                else:
                    self.text += engine.render(
                        "il_guarded", condition=condition, body=statement,
                        indent=self.indent,
                    )
                terminated = opcode == "RET"
            else:
                function_names = self._il_descendants(operation, "il_function_name")
                if function_names:
                    name = function_names[0].get("value", "")
                    arguments = self._il_call_arguments(operation, accumulator)
                    accumulator = engine.render(
                        "il_call", name=name, arguments=", ".join(arguments)
                    )
        if self.current_function and accumulator is not None and not terminated and not stored_function_result:
            target = self.render({"name": "variable_name", "value": self.current_function, "children": []})
            self.text += engine.render(
                "il_assign", target=target, value=accumulator, indent=self.indent
            )

    def _il_label_index(self, instructions, destination):
        wanted = str(destination or "").casefold()
        for index, instruction in enumerate(instructions):
            for label in self._il_labels(instruction):
                if str(label.get("value", "")).casefold() == wanted:
                    return index
        return len(instructions)

    def _visit_il_dispatch(self, node, instructions):
        engine = self.generator_engine
        labels = {}
        for index, instruction in enumerate(instructions):
            for label in self._il_labels(instruction):
                labels[str(label.get("value", "")).casefold()] = index
        accumulator = None
        terminated = False
        stored_function_result = False
        arms = []
        for index, instruction in enumerate(instructions):
            body_indent = self.indent + "    "
            body = ""
            for label in self._il_labels(instruction):
                body += engine.render(
                    "il_label", name=label.get("value", ""), indent=body_indent
                )
            operation = self._il_operation(instruction)
            advances = True
            if operation is not None:
                opcode = self._il_token(operation)
                operand = self._il_render_operand(operation)
                if opcode in {"LD", "LDN"} and operand is not None:
                    accumulator = self._il_boolean_not(operand) if opcode == "LDN" else operand
                elif opcode in {"ST", "STN"} and operand is not None and accumulator is not None:
                    value = self._il_boolean_not(accumulator) if opcode == "STN" else accumulator
                    body += engine.render(
                        "il_assign", target=operand, value=value, indent=body_indent
                    )
                    stored_function_result = bool(self.current_function) and operand.casefold() == self.current_function.casefold()
                elif opcode == "NOT" and accumulator is not None:
                    accumulator = self._il_boolean_not(accumulator)
                elif opcode in {"ANDN", "AN", "ORN", "XORN"} and accumulator is not None and operand is not None:
                    key = {"ANDN": "BIT_AND", "AN": "BIT_AND", "ORN": "BIT_OR", "XORN": "XOR"}[opcode]
                    operator = engine.map("operator", key)
                    accumulator = f"({accumulator} {operator} {self._il_boolean_not(operand)})"
                elif opcode in {"AND", "&", "OR", "XOR", "ADD", "SUB", "MUL", "DIV", "MOD", "GT", "GE", "EQ", "LT", "LE", "NE"} and accumulator is not None and operand is not None:
                    operator = engine.map("operator", self._il_opcode_key(opcode))
                    accumulator = f"({accumulator} {operator} {operand})"
                elif opcode in {"S", "S1", "R", "R1"} and accumulator is not None and operand is not None:
                    value = self._il_true() if opcode in {"S", "S1"} else self._il_false()
                    inner = engine.render(
                        "il_assign", target=operand, value=value, indent=body_indent + "    "
                    )
                    body += engine.render(
                        "il_guarded", condition=accumulator, body=inner, indent=body_indent
                    )
                elif opcode in {"JMP", "JMPC", "JMPCN"}:
                    targets = self._il_descendants(operation, "label")
                    destination = targets[0].get("value", "") if targets else ""
                    target_index = labels.get(str(destination).casefold(), len(instructions))
                    jump = engine.render(
                        "il_jump", target_label=destination, target_index=target_index,
                        condition="", has_condition="", indent=body_indent + "    " if opcode != "JMP" else body_indent,
                    )
                    if opcode == "JMP":
                        body += jump
                        advances = False
                    elif accumulator is not None:
                        condition = accumulator if opcode == "JMPC" else self._il_boolean_not(accumulator)
                        body += engine.render(
                            "il_guarded", condition=condition, body=jump, indent=body_indent
                        )
                elif opcode in {"RET", "RETC", "RETCN"}:
                    condition = None
                    if opcode == "RETC" and accumulator is not None:
                        condition = accumulator
                    elif opcode == "RETCN" and accumulator is not None:
                        condition = self._il_boolean_not(accumulator)
                    if self.current_function and accumulator is not None:
                        value = f" {accumulator}"
                    else:
                        value = ""
                    statement = engine.render(
                        "il_return", value=value, has_value="1" if value else "",
                        condition="", has_condition="", indent=body_indent + "    " if condition else body_indent,
                    )
                    if condition is None:
                        body += statement
                        advances = opcode != "RET"
                        if opcode == "RET":
                            terminated = True
                    else:
                        body += engine.render(
                            "il_guarded", condition=condition, body=statement, indent=body_indent
                        )
                else:
                    function_names = self._il_descendants(operation, "il_function_name")
                    if function_names:
                        name = function_names[0].get("value", "")
                        arguments = self._il_call_arguments(operation, accumulator)
                        accumulator = engine.render(
                            "il_call", name=name, arguments=", ".join(arguments)
                        )
            if advances:
                body += engine.render("il_next", index=index + 1, indent=body_indent)
            arms.append(
                engine.render(
                    "il_instruction", index=index,
                    label="", has_label="", body=body, indent=self.indent,
                )
            )
        self.text += engine.render(
            "il_dispatch", instructions="".join(arms), labels="",
            indent=self.indent, acc="",
        )
        if self.current_function and accumulator is not None and not terminated and not stored_function_result:
            target = self.render({"name": "variable_name", "value": self.current_function, "children": []})
            self.text += engine.render(
                "il_assign", target=target, value=accumulator, indent=self.indent
            )

    def __init__(
        self,
        context=None,
        source_name="<stdin>",
        native_implementations=None,
        generator_bundle: GeneratorBundle | None = None,
        use_data_generator: bool = True,
    ):
        self.context = context
        self.source_name = source_name
        self.native_implementations = native_implementations or {}
        display_source = str(source_name).replace("*/", "* /")
        standard_edition = context.standard_edition if context is not None else 3
        self.indent = ""
        self.current_function = None
        self.current_return_type = None
        self.current_instance = None
        self.current_instance_fields = set()
        self.current_instance_field_paths = {}
        self.current_pointer_params = set()
        self._types_pre_emitted = False
        self.oop = OOPCEmitter(self)
        self.generator_engine = (
            GeneratorEngine(generator_bundle or load_generator(bundled_generator("c")))
            if use_data_generator else None
        )
        if self.generator_engine is not None:
            self.text = self.generator_engine.render(
                "preamble", source=display_source, edition=str(standard_edition)
            )
        else:
            self.text = (
                "/*\n"
                " * Portable C generated by STC.\n"
                f" * Source: {display_source}\n"
                f" * IEC profile: IEC 61131-3 Edition {standard_edition}\n"
                " *\n"
                " * This file contains the translated IEC 61131-3 program and its runtime glue.\n"
                " * Regenerate it from the Structured Text source instead of editing it directly.\n"
                " */\n\n"
                "/* Standard C library headers. */\n"
                "#include <stdbool.h>\n"
                "#include <stdint.h>\n"
                "#include <math.h>\n"
                "#include <stdio.h>\n"
                "#include <stdlib.h>\n"
                "#include <string.h>\n\n"
                "/* Checked IEC reference dereference: NULL is a runtime error. */\n"
                "#define STC_DEREF(pointer) "
                "(*((pointer) != NULL ? (pointer) : (abort(), (pointer))))\n\n"
            )

    def iecType2C(self, typein):
        if self.generator_engine is not None:
            return self.generator_engine.map("type", str(typein))
        conv = {
            "SINT": "int8_t", "INT": "int16_t", "DINT": "int32_t", "LINT": "int64_t",
            "USINT": "uint8_t", "UINT": "uint16_t", "UDINT": "uint32_t", "ULINT": "uint64_t",
            "REAL": "float", "LREAL": "double",
            "BOOL": "bool", "BYTE": "uint8_t", "WORD": "uint16_t", "DWORD": "uint32_t",
            "LWORD": "uint64_t", "TIME": "int64_t", "DATE": "int64_t",
            "LTIME": "int64_t", "LDATE": "int64_t", "LTOD": "int64_t", "LDT": "int64_t",
            "TIME_OF_DAY": "int64_t", "TOD": "int64_t", "DATE_AND_TIME": "int64_t",
            "DT": "int64_t", "CHAR": "uint8_t", "WCHAR": "uint16_t", "UCHAR": "uint32_t",
            "STRING": "const char *", "WSTRING": "const char *", "USTRING": "const char *",
        }
        return conv.get(typein.upper(), typein)


    def c_type_for_node(self, node, fallback=None):
        if self.context is not None:
            datatype = self.context.type_of(node)
            if datatype is not None and datatype.name not in {"<unknown>", "<error>"}:
                return self.iecType2C(datatype.name)
        return fallback

    def source_line_directive(self, node):
        if self.context is None or self.context.source_map is None:
            return ""
        span = self.context.source_map.span_for(node)
        if span is None or self.source_name in {"-", "<stdin>"}:
            return ""
        escaped = self.source_name.replace("\\", "\\\\").replace('"', '\\"')
        return f'#line {span.start_line} "{escaped}"\n'

    def indent_inc(self):
        self.indent += "    "

    def indent_dec(self):
        self.indent = self.indent[:-4]

    def render(self, node):
        previous = self.text
        self.text = ""
        self.visit(node)
        rendered = self.text
        self.text = previous
        return rendered

    def extract_type(self, node):
        if isinstance(node, dict):
            if node.get("name", "").endswith("_type_name") and node.get("value"):
                return self.iecType2C(node["value"])
            for child in node.get("children", []):
                found = self.extract_type(child)
                if found:
                    return found
        return None

    def declaration_type(self, node, fallback="int16_t"):
        """Return a target type for an IEC declaration, including strings."""
        reference = self._first_named(node, "reference_specification")
        if reference is not None:
            return f"{self.extract_type(reference) or fallback} *"
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "const char *"
        found = self.extract_type(node)
        if found:
            return found
        raw_types = {value.upper() for value in self._raw_values(node) if isinstance(value, str)}
        for type_name in ("STRING", "WSTRING", "USTRING", "CHAR", "WCHAR", "UCHAR",
                          "TIME", "LTIME", "DATE", "LDATE", "TOD", "LTOD", "TIME_OF_DAY", "DT", "LDT", "DATE_AND_TIME"):
            if type_name in raw_types:
                return self.iecType2C(type_name)
        return fallback

    def _raw_values(self, node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            value = node.get("value")
            if isinstance(value, str):
                yield value
            for child in node.get("children", []):
                yield from self._raw_values(child)

    def _string_max_length(self, expression):
        """Return the declared maximum length of an IEC string expression."""
        if expression is None or self.context is None:
            return None
        variable = self._first_named(expression, "variable_name")
        if variable is None:
            return None
        symbol = self.context.symbols.symbol_for_reference(variable)
        if symbol is None or symbol.type_ref.name is None:
            return None
        type_name = str(symbol.type_ref.name or "").upper()
        if type_name not in {"STRING", "WSTRING", "USTRING"}:
            return None
        # For STRING[n], WSTRING[n] and USTRING[n], TypeRef.node still
        # contains the original declaration AST, including integer n.
        declaration = symbol.type_ref.node
        size = self._first_named(declaration, "integer")
        if size is not None and size.get("value") is not None:
            return int(str(size["value"]).replace("_", ""))
        # IEC default maximum length when no explicit [n] is supplied.
        return 80

    def zero_value(self, c_type):
        if c_type == "bool":
            return "false"
        if c_type == "float":
            return "0.0f"
        if c_type == "double":
            return "0.0"
        if c_type == "const char *":
            return "NULL"
        return "0"

    def _array_dimensions(self, specification):
        dimensions = ""
        for range_node in self._named_nodes(specification, "subrange"):
            bounds = self._named_nodes(range_node, "signed_integer")
            if len(bounds) == 2:
                lower, upper = self.render(bounds[0]), self.render(bounds[1])
                size = f"{upper} - ({lower}) + 1"
                dimensions = self.generator_engine.render(
                    "array_dimension", value=dimensions, size=size, lower=lower, upper=upper
                )
        return dimensions

    def _declaration_type(self, node):
        reference = self._first_named(node, "reference_specification")
        if reference is not None:
            return f"{self.extract_type(reference) or 'int16_t'} *"
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "const char *"
        array = self._first_named(node, "array_specification")
        if array is not None:
            named = self._first_named(array, "array_type_name")
            if named is not None:
                return named["value"]
            return self.declaration_type(array) + self._array_dimensions(array)
        for kind in ("structure_type_name", "function_block_type_name"):
            named = self._first_named(node, kind)
            if named is not None:
                value = named.get("value")
                if value:
                    return self.iecType2C(value)
                leaf = next((item.get("value") for item in self._named_nodes(named, "standard_function_block_name") if item.get("value")), None)
                if leaf:
                    return leaf
                leaf = next((item.get("value") for item in self._named_nodes(named, "derived_function_block_name") if item.get("value")), None)
                if leaf:
                    return leaf
        return self.declaration_type(node)

    @staticmethod
    def _format_declarator(var_type, name, pointer=False):
        bracket = var_type.find("[")
        if bracket >= 0:
            base, dimensions = var_type[:bracket], var_type[bracket:]
            return f"{base} (*{name}){dimensions}" if pointer else f"{base} {name}{dimensions}"
        if pointer:
            separator = "" if var_type.rstrip().endswith("*") else " "
            return f"{var_type}{separator}*{name}"
        separator = "" if var_type.rstrip().endswith("*") else " "
        return f"{var_type}{separator}{name}"

    def _emit_section(self, title):
        self.text += f"/* --- {title} " + "-" * max(1, 68 - len(title)) + " */\n\n"

    def collect_var_decls(self, node):
        declarations = []
        if not isinstance(node, dict):
            return declarations
        declaration_nodes = {
            "var1_init_decl", "var1_declaration", "array_var_init_decl",
            "array_var_declaration", "structured_var_init_decl", "structured_var_declaration",
            "string_var_declaration", "fb_name_decl", "located_var_decl",
        }
        if node.get("name") in declaration_nodes:
            names = []
            names_node = self._first_named(node, "var1_list")
            for child in self._named_nodes(names_node, "variable_name"):
                if child.get("value") and child["value"] not in names:
                    names.append(child["value"])
            if not names:
                for child in self._named_nodes(node, "fb_name"):
                    if child.get("value") and child["value"] not in names:
                        names.append(child["value"])
            var_type = self._declaration_type(node)
            declarations.extend((var_type, name) for name in names)
            return declarations
        for child in node.get("children", []):
            declarations.extend(self.collect_var_decls(child))
        return declarations

    def _section_declarations(self, node):
        declarations = []
        for section in ("input_declarations", "output_declarations", "input_output_declarations",
                        "var_declarations", "retentive_var_declarations", "non_retentive_var_decls",
                        "temp_var_decls", "function_var_decls"):
            declarations.extend(self.collect_sections(node, section))
        return declarations

    def _persistent_declarations(self, node):
        declarations = []
        for section in ("input_declarations", "output_declarations", "input_output_declarations",
                        "var_declarations", "retentive_var_declarations", "non_retentive_var_decls"):
            declarations.extend(self.collect_sections(node, section))
        return declarations

    def _temporary_declarations(self, node):
        return self.collect_sections(node, "temp_var_decls")

    def _retained_declarations(self, node):
        return self.collect_sections(node, "retentive_var_declarations")

    def _declaration_initializers(self, node):
        result = {}
        declaration_nodes = {
            "var1_init_decl", "string_var_declaration",
        }
        persistent_sections = {
            "input_declarations", "output_declarations", "input_output_declarations",
            "var_declarations", "retentive_var_declarations", "non_retentive_var_decls",
        }
        declarations = self._persistent_declarations(node)
        previous_instance, previous_fields = self.current_instance, self.current_instance_fields
        self.current_instance = "self"
        self.current_instance_fields = {field.casefold() for _, field in declarations}
        try:
            for section_name in persistent_sections:
                for section in self._named_nodes(node, section_name):
                    for declaration in self._iter_named_set(section, declaration_nodes):
                        initializer = (
                            self._first_named(declaration, "reference_value")
                            or self._first_named(declaration, "constant")
                        )
                        if initializer is None:
                            continue
                        value = self.render(initializer)
                        for var_type, field in self.collect_var_decls(declaration):
                            if "[" not in var_type:
                                result[field.casefold()] = value
        finally:
            self.current_instance, self.current_instance_fields = previous_instance, previous_fields
        return result

    def _iter_named_set(self, node, names):
        if not isinstance(node, dict):
            return
        if node.get("name") in names:
            yield node
            return
        for child in node.get("children", []):
            yield from self._iter_named_set(child, names)

    @staticmethod
    def _unique_declarations(declarations):
        result = []
        seen = set()
        for declaration in declarations:
            key = declaration[1].casefold()
            if key not in seen:
                seen.add(key)
                result.append(declaration)
        return result

    def _emit_instance_initializers(self, name, declarations, retained, initializers):
        retained_names = {field.casefold() for _, field in retained}
        self.text += "/* Reset all instance state for a cold start. */\n"
        self.text += f"void {name}_cold_init({name} *self)\n{{\n    memset(self, 0, sizeof(*self));\n"
        for var_type, field in declarations:
            self.oop.emit_field_initializer(var_type, f"&self->{field}", self.text_append)
        for _, field in declarations:
            if field.casefold() in initializers:
                self.text += f"    self->{field} = {initializers[field.casefold()]};\n"
        self.text += "}\n\n"
        self.text += "/* Reset non-retentive state while preserving RETAIN fields. */\n"
        self.text += f"void {name}_warm_init({name} *self)\n{{\n"
        if not declarations:
            self.text += "    (void)self;\n"
        for _, field in declarations:
            if field.casefold() not in retained_names:
                self.text += f"    memset(&self->{field}, 0, sizeof(self->{field}));\n"
                self.oop.emit_field_initializer(_, f"&self->{field}", self.text_append, indent="    ")
                if field.casefold() in initializers:
                    self.text += f"    self->{field} = {initializers[field.casefold()]};\n"
        self.text += "}\n\n"

    def _capture_emission(self, callback):
        previous = self.text
        self.text = ""
        try:
            callback()
            return self.text
        finally:
            self.text = previous

    def text_append(self, value):
        self.text += value

    def collect_sections(self, node, section_name):
        if not isinstance(node, dict):
            return []
        if node.get("name") == "property_declaration":
            return []
        if node.get("name") == section_name:
            return self.collect_var_decls(node)
        declarations = []
        for child in node.get("children", []):
            declarations.extend(self.collect_sections(child, section_name))
        return declarations

    def visit_integer_literal(self, node):
        value = node["value"].replace("_", "")
        self.text += self.generator_engine.render(
            "integer_literal", Literal(value=value, type_name=self.c_type_for_node(node))
        ) if self.generator_engine is not None else value

    def visit_real_literal(self, node):
        value = node["value"].replace("_", "")
        c_type = self.c_type_for_node(node)
        suffix = "f" if c_type == "float" and not value.lower().endswith("f") else ""
        self.text += self.generator_engine.render(
            "real_literal", Literal(value=value, type_name=c_type, suffix=suffix)
        ) if self.generator_engine is not None else value + suffix

    def visit_integer(self, node):
        self.text += node["value"].replace("_", "")

    def visit_signed_integer(self, node):
        if node.get("value") is not None:
            self.text += str(node["value"]).replace("_", "")
        else:
            self.accept(node)

    def _visit_based_integer(self, node, base):
        value = self.render(node["children"][0]).replace("_", "")
        digits = value.split("#", 1)[-1]
        # The backend declares its own per-base prefix; an empty prefix means
        # the target has no literal syntax for that base, so the lowering pass
        # normalizes the value to decimal. No target name appears here.
        prefix = (
            self.generator_engine.map("based_prefix", str(base))
            if self.generator_engine is not None else ""
        )
        normalized = str(int(digits, base)) if prefix == "" else digits
        if self.generator_engine is not None:
            self.text += self.generator_engine.render(
                "based_literal", value=normalized, base=str(base), prefix=prefix
            )
        else:
            self.text += prefix + normalized

    def visit_binary_integer(self, node):
        self._visit_based_integer(node, 2)

    def visit_octal_integer(self, node):
        self._visit_based_integer(node, 8)

    def visit_hex_integer(self, node):
        self._visit_based_integer(node, 16)

    def visit_boolean_literal(self, node):
        self.text += (
            self.generator_engine.map("boolean_literal", node["value"].upper())
            if self.generator_engine is not None else node["value"].lower()
        )

    def visit_bit_string_literal(self, node):
        for child in node["children"]:
            self.visit(child)

    def _iec_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "''")) if token else "''"
        content = raw[1:-1] if len(raw) >= 2 else raw
        content = content.replace("$N", "\n").replace("$n", "\n")
        content = content.replace("$T", "\t").replace("$t", "\t")
        content = content.replace("$$", "$").replace("$''", "'").replace("$'", "'")
        content = content.replace("''", "'")
        content = content.replace("\\", "\\\\").replace('"', '\\"')
        content = content.replace("\n", "\\n").replace("\t", "\\t")
        return f'"{content}"'

    @staticmethod
    def _unicode_content(raw):
        """Decode the Edition 4 ${HEX} escape into a Unicode scalar value."""
        sharp = raw.find("#")
        quoted = raw[sharp + 1:].strip() if sharp >= 0 else raw
        content = quoted[1:-1] if len(quoted) >= 2 else quoted
        content = re.sub(
            r"\$\{([0-9A-Fa-f]{1,6})\}",
            lambda match: (
                chr(int(match.group(1), 16))
                if int(match.group(1), 16) <= 0x10FFFF
                and not 0xD800 <= int(match.group(1), 16) <= 0xDFFF
                else "\ufffd"
            ),
            content,
        )
        return content.replace("$N", "\n").replace("$n", "\n").replace("$$", "$").replace("''", "'")

    def visit_unicode_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "U#''")) if token else "U#''"
        content = self._unicode_content(raw)
        if raw.lstrip().upper().startswith("UCHAR"):
            self.text += str(ord(content[0]) if content else 0)
            return
        escaped = content.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
        self.text += f'"{escaped}"'

    @staticmethod
    def _typed_character_content(raw):
        quoted = raw[raw.find("#") + 1:].strip()
        content = quoted[1:-1] if len(quoted) >= 2 else quoted
        content = re.sub(
            r"\$([0-9A-Fa-f]{2}|[0-9A-Fa-f]{4})",
            lambda match: chr(int(match.group(1), 16)),
            content,
        )
        return content.replace("$N", "\n").replace("$n", "\n").replace("$T", "\t").replace("$t", "\t").replace("$$", "$").replace("''", "'").replace('""', '"')

    def visit_typed_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "STRING#''")) if token else "STRING#''"
        prefix = raw[:raw.find("#")].strip().upper()
        content = self._typed_character_content(raw)
        if prefix in {"CHAR", "WCHAR"}:
            self.text += str(ord(content[0]) if content else 0)
            return
        escaped = content.replace("\\", "\\\\").replace('"', '\\"')
        escaped = escaped.replace("\n", "\\n").replace("\t", "\\t")
        self.text += f'"{escaped}"'

    def visit_single_byte_character_string(self, node):
        self.text += self._iec_string(node)

    def visit_double_byte_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", '""')) if token else '""'
        self.text += raw

    def visit_duration(self, node):
        multipliers = {"d": 86400000, "h": 3600000, "m": 60000, "s": 1000, "ms": 1}
        total = 0.0
        for component in self._named_nodes(node, "duration_component"):
            number = self._first_named(component, "integer") or self._first_named(component, "real_literal")
            tokens = self._named_nodes(component, "token")
            unit = str(tokens[-1].get("value", "ms")).casefold() if tokens else "ms"
            try:
                total += float(number.get("value", 0)) * multipliers.get(unit, 1)
            except (AttributeError, ValueError):
                pass
        self.text += str(int(total))

    def visit_date(self, node):
        values = [int(item.get("value", 0)) for item in self._named_nodes(node, "integer")]
        self.text += str(values[0] * 10000 + values[1] * 100 + values[2] if len(values) >= 3 else 0)

    def visit_time_of_day(self, node):
        values = [int(float(item.get("value", 0))) for item in self._named_nodes(node, "integer")]
        self.text += str(((values[0] * 60 + values[1]) * 60 + values[2]) * 1000 if len(values) >= 3 else 0)

    def visit_date_and_time(self, node):
        values = [int(float(item.get("value", 0))) for item in self._named_nodes(node, "integer")]
        if len(values) >= 6:
            self.text += str((((values[0] * 100 + values[1]) * 100 + values[2]) * 1000000) + values[3] * 10000 + values[4] * 100 + values[5])
        else:
            self.text += "0"

    def visit_signed_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_unsigned_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_real_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_bit_string_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_variable_name(self, node):
        name = node["value"]
        if self.current_instance is not None and name.casefold() in self.current_instance_fields:
            path = self.current_instance_field_paths.get(name.casefold(), name)
            self.text += f"{self.current_instance}->{path}"
        elif name.casefold() in self.current_pointer_params:
            self.text += f"(*{name})"
        elif self.context is not None:
            symbol = self.context.symbols.symbol_for_reference(node)
            if symbol is not None and symbol.storage in {"output", "in_out"}:
                self.text += f"(*{name})"
            else:
                self.text += name
        else:
            self.text += name

    def visit_enumerated_value(self, node):
        self.text += str(node.get("value", "0"))

    def visit_qualified_enumerated_value(self, node):
        self.accept(node)

    def visit_field_selector(self, node):
        self.text += str(node.get("value", ""))

    def visit_structured_variable(self, node):
        info = self.context.resolved_properties.get(id(node)) if self.context is not None else None
        if info is None or info.get("accessor") != "get":
            self.accept(node)
            return
        receiver = self._first_named(node, "variable_name")
        expression = self.render(receiver)
        method_name = info["method"]["name"]
        rule = (
            "property_get_interface"
            if info["interface"]
            else "property_get_class"
            if info["owner_kind"] == "class"
            else "property_get"
        )
        self.text += self.generator_engine.render(
            rule,
            receiver=expression,
            method=method_name,
            owner=info["owner"],
            arguments="",
            extra_arguments="",
            base_path="".join(f".{item}" for item in info.get("base_path", ())),
        )

    def _emit_property_assignment(self, node):
        if self.context is None:
            return False
        variable = self._first_named(node, "variable")
        structured = self._first_named(variable, "structured_variable")
        info = self.context.resolved_properties.get(id(structured)) if structured is not None else None
        if info is None or info.get("accessor") != "set":
            return False
        expression_node = self._first_named(node, "expression")
        receiver = self._first_named(structured, "variable_name")
        receiver_text = self.render(receiver)
        value = self.render(expression_node)
        method_name = info["method"]["name"]
        rule = (
            "property_set_interface"
            if info["interface"]
            else "property_set_class"
            if info["owner_kind"] == "class"
            else "property_set"
        )
        self.text += self.generator_engine.render(
            rule,
            receiver=receiver_text,
            method=method_name,
            owner=info["owner"],
            value=value,
            indent=self.indent,
            base_path="".join(f".{item}" for item in info.get("base_path", ())),
        )
        return True

    def _array_lower_bounds(self, variable_name):
        """Return the IEC lower bounds for an array variable reference."""
        if self.context is None or variable_name is None:
            return ()

        symbol = self.context.symbols.symbol_for_reference(variable_name)
        if symbol is None:
            return ()

        specification = None

        # Inline declaration:
        #     A : ARRAY[5..7] OF INT;
        declaration_nodes = {
            "var1_init_decl",
            "var1_declaration",
            "array_var_init_decl",
            "array_var_declaration",
            "structured_var_init_decl",
            "structured_var_declaration",
            "string_var_declaration",
            "fb_name_decl",
            "located_var_decl",
        }
        for declaration in self._iter_named_set(
            symbol.scope.node, declaration_nodes
        ):
            names = self._named_nodes(declaration, "variable_name")
            if any(item is symbol.declaration for item in names):
                specification = self._first_named(
                    declaration, "array_specification"
                )
                break

        # Named array type:
        #     TYPE Values : ARRAY[5..7] OF INT; END_TYPE
        #     A : Values;
        if (
            specification is None
            and symbol.type_ref is not None
            and symbol.type_ref.name
        ):
            type_name = symbol.type_ref.name.casefold()
            root = self.context.symbols.global_scope.node
            for declaration in self._named_nodes(
                root, "array_type_declaration"
            ):
                name = self._first_named(declaration, "array_type_name")
                if (
                    name is not None
                    and str(name.get("value", "")).casefold() == type_name
                ):
                    specification = self._first_named(
                        declaration, "array_specification"
                    )
                    break

        if specification is None:
            return ()

        lower_bounds = []
        for subrange in self._named_nodes(specification, "subrange"):
            bounds = self._named_nodes(subrange, "signed_integer")
            if len(bounds) == 2:
                lower_bounds.append(self.render(bounds[0]))

        return tuple(lower_bounds)

    def visit_array_variable(self, node):
        """Translate IEC array indexes to zero-based C indexes."""
        subscripted = self._first_named(node, "subscripted_variable")
        subscript_list = self._first_named(node, "subscript_list")

        if subscripted is None or subscript_list is None:
            self.accept(node)
            return

        variable_name = self._first_named(subscripted, "variable_name")
        lower_bounds = self._array_lower_bounds(variable_name)

        array = self.render(subscripted)

        subscripts = [
            child
            for child in subscript_list.get("children", [])
            if isinstance(child, dict) and child.get("name") == "subscript"
        ]

        indices = []
        for dimension, subscript in enumerate(subscripts):
            index = self.render(subscript)
            lower = (
                lower_bounds[dimension]
                if dimension < len(lower_bounds)
                else "0"
            )
            if lower == "0":
                adjusted = index
            else:
                adjusted = f"({index}) - ({lower})"
            indices.append({"value": adjusted})
        rendered_indices = self.generator_engine.render("array_index", items=indices)
        self.text += self.generator_engine.render("array_access", array=array, indices=rendered_indices)

    def visit_subscript_list(self, node):
        for subscript in self._named_nodes(node, "subscript"):
            self.text += f"[{self.render(subscript)}]"

    def visit_library(self, node):
        self._emit_section("IEC 61131-3 runtime support")
        self.oop.prepare(node)
        requested = {
            str(item.get("value", "")).upper()
            for item in self._named_nodes(node, "standard_function_name")
        }
        if self._named_nodes(node, "assert_statement"):
            requested.add("ASSERT")
        bundle = self.generator_engine.bundle if self.generator_engine is not None else None
        if self.generator_engine is not None and bundle is not None:
            self.text += render_primitives(
                bundle.extension, requested, self.generator_engine, bundle.path
            ) + "\n"
        else:
            self.text += render_primitives("c", requested) + "\n"
        type_declarations = self._named_nodes(node, "data_type_declaration")
        if type_declarations:
            self._emit_section("User-defined IEC data types")
        for declaration in type_declarations:
            self.visit_data_type_declaration(declaration)
        self._types_pre_emitted = True
        if type_declarations:
            self.text += "\n"
        global_declarations = self._named_nodes(node, "global_var_decl")
        if global_declarations:
            self._emit_section("Configuration global variables")
        for global_decl in global_declarations:
            names = [item.get("value") for item in self._named_nodes(global_decl, "global_var_name") if item.get("value")]
            var_type = self._declaration_type(global_decl)
            section = self._ancestor_section(node, global_decl, "global_var_declarations")
            is_constant = section is not None and "CONSTANT" in {value.upper() for value in self._raw_values(section)}
            initializer = self._first_named(global_decl, "constant")
            initial_value = self.render(initializer) if initializer is not None else "0"
            for name in names:
                qualifier = "const " if is_constant else ""
                self.text += qualifier + self._format_declarator(var_type, name) + f" = {initial_value};\n"
        if global_declarations:
            self.text += "\n"
        declarations = list(self._function_declarations(node))
        if declarations:
            self._emit_section("Function declarations")
            for declaration in declarations:
                return_type, emitted_name, params = self._function_signature(declaration)
                self.text += f"{return_type} {emitted_name}({', '.join(params) or 'void'});\n"
            self.text += "\n"
        if self.oop.has_oop:
            self._emit_section("IEC 61131-3 Edition 3 object-oriented types")
            self.oop.emit_declarations(node)
        self._emit_section("Program organization unit implementations")
        self.accept(
            node,
            lambda name: name not in {
                "data_type_declaration", "class_declaration", "interface_declaration"
            },
        )
        configurations = self._named_nodes(node, "configuration_declaration")
        if configurations:
            self.text += "\n/* Standalone entry point. Define STC_NO_MAIN when embedding this file. */\n"
            self.text += "\n#ifndef STC_NO_MAIN\nint main(void)\n{\n"
            for configuration in configurations:
                config_name = self._first_named(configuration, "configuration_name")["value"]
                self.text += f"    {config_name}_cold_start();\n    {config_name}_cycle({config_name}_base_interval_ms());\n"
            self.text += "    return 0;\n}\n#endif\n"

    def _ancestor_section(self, root, target, name):
        if not isinstance(root, dict):
            return None
        if root.get("name") == name and any(item is target for item in self._named_nodes(root, target.get("name"))):
            return root
        for child in root.get("children", []):
            found = self._ancestor_section(child, target, name)
            if found is not None:
                return found
        return None


    def _function_declarations(self, node):
        if not isinstance(node, dict):
            return
        if node.get("name") == "function_declaration":
            yield node
            return
        for child in node.get("children", []):
            yield from self._function_declarations(child)

    def _function_signature(self, node):
        name = node["children"][0]["value"]
        symbol = None
        if self.context is not None:
            symbol = self.context.symbols.symbol_for_declaration(node["children"][0])
        emitted_name = (
            self.context.generated_names.get(id(symbol), name)
            if self.context is not None and symbol is not None
            else name
        )
        return_type = self.declaration_type(node["children"][1], "void")
        input_decls = self.collect_sections(node["children"][2], "input_declarations")
        output_decls = self.collect_sections(node["children"][2], "output_declarations")
        inout_decls = self.collect_sections(node["children"][2], "input_output_declarations")
        params = [self._format_declarator(var_type, var_name) for var_type, var_name in input_decls]
        params += [self._format_declarator(var_type, var_name, pointer=True) for var_type, var_name in output_decls + inout_decls]
        return return_type, emitted_name, params

    def visit_standard_function_name(self, node):
        self.text += node["value"]

    def visit_derived_function_name(self, node):
        self.text += node["value"]

    def visit_primary_expression(self, node):
        children = node.get("children", [])
        if not children or children[0].get("name") != "function_name":
            self.accept(node)
            return

        standard_name = self._first_named(children[0], "standard_function_name")
        standard_name_value = (
            str(standard_name.get("value", "")).upper()
            if standard_name
            else ""
        )

        if standard_name_value == "LEN_MAX":
            argument = self._first_named(node, "expression")
            length = self._string_max_length(argument)
            if length is not None:
                self.text += str(length)
                return

        trunc_match = re.fullmatch(
            r"(?:(?:REAL|LREAL)_)?TRUNC_(SINT|INT|DINT|LINT|USINT|UINT|UDINT|ULINT)",
            standard_name_value,
        )
        if trunc_match:
            argument = self._first_named(node, "expression")
            self.text += self.generator_engine.render(
                "cast",
                Cast(self.c_type_for_node(argument) or "", self.iecType2C(trunc_match.group(1)), self.render(argument)),
            )
            return

        resolved = self.context.resolved_calls.get(id(node)) if self.context is not None else None
        name = self.context.generated_names.get(id(resolved), resolved.name) if resolved is not None else self.render(children[0])
        resolved_arguments = (
            self.context.resolved_arguments.get(id(node)) if self.context is not None else None
        )
        arguments = resolved_arguments or [
            child for child in children[1:] if child.get("name") == "param_assignment"
        ]
        rendered_arguments = []
        for argument in arguments:
            if resolved_arguments is not None:
                rendered_arguments.append({"value": self.render(argument)})
            else:
                expressions = [child for child in argument.get("children", []) if child.get("name") == "expression"]
                if expressions:
                    rendered_arguments.append({"value": self.render(expressions[-1])})
        argument_text = self.generator_engine.render("parameter", items=rendered_arguments)
        self.text += self.generator_engine.render(
            "call", Call(name, tuple(item["value"] for item in rendered_arguments)), arguments=argument_text
        )

    def visit_function_declaration(self, node):
        name = node["children"][0]["value"]
        native = self.native_implementations.get(name.casefold())
        return_type, emitted_name, params = self._function_signature(node)
        self.current_function = name
        self.current_return_type = return_type

        local_decls = self.collect_sections(node["children"][2], "function_var_decls")

        comment = (
            f"/* Automatically generated conversion for enum {node.get('enum_type')}. */\n"
            if node.get("synthetic") and node.get("generated_by") == "enum-conversions"
            else f"/* IEC function: {name}. */\n"
        )
        locals_text = ""
        if return_type != "void":
            locals_text += f"    {self._format_declarator(return_type, name)} = {{0}};\n"
        for var_type, var_name in local_decls:
            locals_text += f"    {self._format_declarator(var_type, var_name)} = {{0}};\n"
        if local_decls or return_type != "void":
            locals_text += "\n"
        old_indent = self.indent
        self.indent = "    "
        if native is not None:
            body = "".join(f"    {line.rstrip()}\n" if line.strip() else "\n" for line in (native.section("body") or "").splitlines())
        else:
            function_body = self._first_named(node, "function_body")
            body = self.render(function_body) if function_body is not None else ""
        self.indent = old_indent
        return_value = f"    return {name};\n" if return_type != "void" else ""
        self.text += self.generator_engine.render(
            "function", name=name, emitted_name=emitted_name, comment=comment, attributes="",
            return_type=return_type, parameters=", ".join(params) or "void",
            locals=locals_text, body=body, return_value=return_value,
        )
        self.current_function = None
        self.current_return_type = None

    def visit_function_block_declaration(self, node):
        name_node = self._first_named(node, "derived_function_block_name")
        if name_node is None:
            return
        name = name_node["value"]
        native = self.native_implementations.get(name.casefold())
        declarations = self._unique_declarations(
            self._persistent_declarations(node) + sfc_state_declarations(node, *self._sfc_state_types())
        )
        temporaries = self._unique_declarations(self._temporary_declarations(node))
        retained = self._unique_declarations(self._retained_declarations(node))
        initializers = self._declaration_initializers(node)
        for chart in sfc_charts(node):
            for step in chart["steps"]:
                if step["initial"]:
                    initializers[sfc_field(step["name"], "active").casefold()] = "true"

        fields = "".join(f"    {self._format_declarator(t, n)};\n" for t, n in declarations) or "    uint8_t _stc_empty;\n"
        properties = self._capture_emission(lambda: self._emit_function_block_properties(name, node, declarations))
        setup_text = "    memset(self, 0, sizeof(*self));\n"
        for chart in sfc_charts(node):
            for step in chart["steps"]:
                if step["initial"]:
                    setup_text += f"    self->{sfc_field(step['name'], 'active')} = true;\n"
        for _, field in declarations:
            if field.casefold() in initializers:
                setup_text += f"    self->{field} = {initializers[field.casefold()]};\n"
        setup = native.section("setup") if native is not None and native.kind == "function_block" else None
        if setup:
            setup_text += "".join(f"    {line.rstrip()}\n" if line.strip() else "\n" for line in setup.splitlines())
        instance_initializers = self._capture_emission(lambda: self._emit_instance_initializers(name, declarations, retained, initializers))

        inouts = self.collect_sections(node, "input_output_declarations")
        parameters = [f"{name} *self"] + [self._format_declarator(var_type, var_name, pointer=True) for var_type, var_name in inouts]
        entrypoint = "loop" if native is not None and native.kind == "function_block" else "step"
        previous_instance, previous_fields, previous_pointers = self.current_instance, self.current_instance_fields, self.current_pointer_params
        self.current_instance = "self"
        self.current_instance_fields = {field.casefold() for _, field in declarations if field.casefold() not in {item.casefold() for _, item in inouts}}
        self.current_pointer_params = {field.casefold() for _, field in inouts}
        old_indent = self.indent
        self.indent = "    "
        temporaries_text = "    (void)self;\n"
        for var_type, var_name in temporaries:
            temporaries_text += f"    {self._format_declarator(var_type, var_name)} = {{0}};\n"
        if temporaries:
            temporaries_text += "\n"
        if native is not None and native.kind == "function_block":
            body = "".join(f"    {line.rstrip()}\n" if line.strip() else "\n" for line in (native.section("loop") or "").splitlines())
        else:
            body_node = self._first_named(node, "function_block_body")
            body = self.render(body_node) if body_node is not None else ""
        self.current_instance, self.current_instance_fields, self.current_pointer_params = previous_instance, previous_fields, previous_pointers
        self.indent = old_indent
        self.text += self.generator_engine.render(
            "function_block", name=name, fields=fields, properties=properties,
            setup=setup_text, cold_init=instance_initializers, warm_init="",
            parameters=", ".join(parameters), entrypoint=entrypoint,
            temporaries=temporaries_text, body=body,
        )

    def _emit_function_block_properties(self, owner_name, node, declarations):
        field_paths = {field.casefold(): field for _, field in declarations}
        for prop in self._named_nodes(node, "property_declaration"):
            method = self._first_named(prop, "method_declaration")
            if method is None:
                continue
            method_name_node = self._first_named(method, "method_name")
            if method_name_node is None:
                continue
            method_name = method_name_node["value"]
            ret, suffix = self.oop._method_signature(method)
            return_type_node = self._first_named(method, "function_return_type")
            locals_text = ""
            if return_type_node is not None:
                locals_text += (
                    f"    {self._format_declarator(ret, method_name)} = "
                    f"{self.zero_value(ret)};\n"
                )
            for var_type, local in (
                self.collect_sections(method, "function_var_decls")
                + self.collect_sections(method, "temp_var_decls")
            ):
                locals_text += f"    {self._format_declarator(var_type, local)} = {{0}};\n"

            old_instance, old_fields = self.current_instance, self.current_instance_fields
            old_paths, old_pointers = self.current_instance_field_paths, self.current_pointer_params
            self.current_instance = "self"
            self.current_instance_fields = set(field_paths)
            self.current_instance_field_paths = field_paths
            inouts = self.collect_sections(method, "input_output_declarations")
            outputs = self.collect_sections(method, "output_declarations")
            self.current_pointer_params = {item.casefold() for _, item in inouts + outputs}
            old_indent = self.indent
            self.indent = "    "
            body = self._capture_emission(
                lambda: self.visit(self._first_named(method, "function_body"))
                if self._first_named(method, "function_body") is not None
                else None
            )
            self.indent = old_indent
            self.current_instance, self.current_instance_fields = old_instance, old_fields
            self.current_instance_field_paths, self.current_pointer_params = old_paths, old_pointers
            return_stmt = (
                self.generator_engine.render("method_return", name=method_name, indent="    ")
                if return_type_node is not None
                else ""
            )
            self.text += self.generator_engine.render(
                "property_method",
                owner=owner_name,
                name=method_name,
                return_type=ret,
                parameters=suffix,
                locals=locals_text,
                body=body,
                return_stmt=return_stmt,
            )

    def visit_program_declaration(self, node):
        name_node = self._first_named(node, "program_type_name")
        if name_node is None:
            return
        name = name_node["value"]
        declarations = self._unique_declarations(
            self._persistent_declarations(node) + sfc_state_declarations(node, *self._sfc_state_types())
        )
        temporaries = self._unique_declarations(self._temporary_declarations(node))
        retained = self._unique_declarations(self._retained_declarations(node))
        initializers = self._declaration_initializers(node)
        for chart in sfc_charts(node):
            for step in chart["steps"]:
                if step["initial"]:
                    initializers[sfc_field(step["name"], "active").casefold()] = "true"
        fields = "".join(f"    {self._format_declarator(var_type, var_name)};\n" for var_type, var_name in declarations)
        if not fields:
            fields = "    uint8_t _stc_empty;\n"
        initializers_text = self._capture_emission(
            lambda: self._emit_instance_initializers(name, declarations, retained, initializers)
        )
        previous_instance, previous_fields, previous_pointers = self.current_instance, self.current_instance_fields, self.current_pointer_params
        self.current_instance, self.current_instance_fields = "self", {field.casefold() for _, field in declarations}
        old_indent = self.indent
        self.indent = "    "
        temporaries_text = "    (void)self;\n"
        for var_type, var_name in temporaries:
            temporaries_text += f"    {self._format_declarator(var_type, var_name)} = {{0}};\n"
        if temporaries:
            temporaries_text += "\n"
        body_node = self._first_named(node, "function_block_body")
        body = self.render(body_node) if body_node is not None else ""
        self.current_instance, self.current_instance_fields, self.current_pointer_params = previous_instance, previous_fields, previous_pointers
        self.indent = old_indent
        self.text += self.generator_engine.render(
            "program", name=name, fields=fields, cold_init=initializers_text, warm_init="",
            temporaries=temporaries_text, body=body,
        )

    def visit_action(self, node):
        name_node = self._first_named(node, "action_name")
        if name_node is None:
            return
        self.indent_inc()
        body = self._capture_emission(
            lambda: self.accept(node, lambda child_name: child_name == "function_block_body")
        )
        self.indent_dec()
        self.text += self.generator_engine.render(
            "sfc_action_decl", name=name_node["value"], body=body
        )

    def _sfc_flag(self, field):
        return self.generator_engine.render("sfc_flag", field=field)

    def _sfc_step_condition(self, step, association):
        engine = self.generator_engine
        active = self._sfc_flag(sfc_field(step["name"], "active"))
        previous = self._sfc_flag(sfc_field(step["name"], "previous"))
        elapsed = self._sfc_flag(sfc_field(step["name"], "elapsed_ms"))
        and_op = engine.map("operator", "AND")
        not_op = engine.map("operator", "NOT")
        qualifier = association["qualifier"]
        time = self.render(association["time"]) if association["time"] is not None else "0"
        if qualifier in {"P", "P1"}:
            return f"({active} {and_op} {not_op}{previous})"
        if qualifier == "P0":
            return f"({not_op}{active} {and_op} {previous})"
        if qualifier == "L":
            return f"({active} {and_op} {elapsed} {engine.map('operator', 'LT')} ({time}))"
        if qualifier in {"D", "SD", "DS"}:
            return f"({active} {and_op} {elapsed} {engine.map('operator', 'GE')} ({time}))"
        if qualifier == "SL":
            return f"({active} {and_op} {elapsed} {engine.map('operator', 'LT')} ({time}))"
        return active

    def _sfc_state_types(self):
        """Return backend-spelled (bool, time) types for SFC state fields."""
        if self.generator_engine is not None:
            return (
                self.generator_engine.map("type", "BOOL"),
                self.generator_engine.map("type", "TIME"),
            )
        return ("bool", "int64_t")

    def _sfc_variable(self, name):
        return self.render({"name": "variable_name", "value": name, "children": []})

    def visit_sequential_function_chart(self, node):
        """Execute one deterministic SFC scan using persistent POU state."""
        engine = self.generator_engine
        and_op = engine.map("operator", "AND")
        or_op = engine.map("operator", "OR")
        not_op = engine.map("operator", "NOT")
        false_value = engine.map("boolean_literal", "FALSE")
        true_value = engine.map("boolean_literal", "TRUE")
        for chart_index, chart in enumerate(sfc_charts(node)):
            ordered = sorted(enumerate(chart["transitions"]), key=lambda item: (item[1]["priority"], item[0]))
            earlier_sources = []
            fire_names = {}
            decls = {}
            for ordinal, transition in ordered:
                fire = f"__sfc_{chart_index}_fire_{ordinal}"
                fire_names[ordinal] = fire
                sources = f" {and_op} ".join(
                    self._sfc_flag(sfc_field(name, "active")) for name in transition["sources"]
                ) or false_value
                condition = self.render(transition["condition"]) if transition["condition"] is not None else false_value
                current_sources = {item.casefold() for item in transition["sources"]}
                blocked = [
                    name for name, used in earlier_sources
                    if {item.casefold() for item in used} & current_sources
                ]
                gate = "" if not blocked else f" {and_op} " + f" {and_op} ".join(f"{not_op}{name}" for name in blocked)
                decls[ordinal] = engine.render(
                    "sfc_fire",
                    fire=fire,
                    sources=sources,
                    condition=condition,
                    gate=gate,
                    indent=self.indent,
                )
                earlier_sources.append((fire, transition["sources"]))

            chunks = []
            for ordinal, transition in enumerate(chart["transitions"]):
                fire = fire_names.get(ordinal)
                if fire is None:
                    continue
                self.indent_inc()
                body = ""
                for name in transition["sources"]:
                    body += engine.render(
                        "sfc_step_assign",
                        step=sfc_field(name, "active"),
                        value=false_value,
                        indent=self.indent,
                    )
                for name in transition["targets"]:
                    body += engine.render(
                        "sfc_step_assign",
                        step=sfc_field(name, "active"),
                        value=true_value,
                        indent=self.indent,
                    )
                self.indent_dec()
                chunks.append(
                    engine.render(
                        "sfc_transition",
                        fire=fire,
                        sources="",
                        targets="",
                        condition=(
                            self.render(transition["condition"])
                            if transition["condition"] is not None
                            else false_value
                        ),
                        priority=transition["priority"],
                        decl=decls[ordinal],
                        body=body,
                        indent=self.indent,
                    )
                )

            for step in chart["steps"]:
                chunks.append(
                    engine.render(
                        "sfc_elapsed",
                        step=step["name"],
                        active=sfc_field(step["name"], "active"),
                        previous=sfc_field(step["name"], "previous"),
                        elapsed=sfc_field(step["name"], "elapsed_ms"),
                        indent=self.indent,
                    )
                )

            variable_conditions = {}
            indicator_conditions = {}
            variable_sets = {}
            variable_resets = {}
            action_sets = {}
            action_resets = {}
            stored_actions = set()
            for step in chart["steps"]:
                for association in step["associations"]:
                    condition = self._sfc_step_condition(step, association)
                    qualifier = association["qualifier"]
                    key = association["name"].casefold()
                    action = chart["actions"].get(key)
                    if action is not None:
                        if qualifier == "R":
                            action_resets.setdefault(key, []).append(condition)
                        elif qualifier in {"S", "SD", "DS"}:
                            action_sets.setdefault(key, []).append(condition)
                            stored_actions.add(key)
                        else:
                            self.indent_inc()
                            action_body = self._capture_emission(
                                lambda: self.accept(action, lambda child_name: child_name == "function_block_body")
                            )
                            self.indent_dec()
                            chunks.append(
                                engine.render(
                                    "sfc_action",
                                    condition=condition,
                                    body=action_body,
                                    indent=self.indent,
                                )
                            )
                    elif qualifier == "R":
                        variable_resets.setdefault(association["name"], []).append(condition)
                    elif qualifier in {"S", "SD", "DS"}:
                        variable_sets.setdefault(association["name"], []).append(condition)
                    else:
                        variable_conditions.setdefault(association["name"], []).append(condition)
                    for indicator in association["indicators"]:
                        indicator_name = self._first_named(indicator, "variable_name")
                        if indicator_name is not None:
                            indicator_conditions.setdefault(indicator_name["value"], []).append(condition)

            combined_conditions = dict(variable_conditions)
            for name, conditions in indicator_conditions.items():
                combined_conditions.setdefault(name, []).extend(conditions)
            for name, conditions in combined_conditions.items():
                enabled = conditions[0] if len(conditions) == 1 else f" {or_op} ".join(f"({item})" for item in conditions)
                if name in variable_sets or name in variable_resets:
                    chunks.append(
                        engine.render(
                            "sfc_set",
                            target=self._sfc_variable(name),
                            condition=enabled,
                            value=true_value,
                            indent=self.indent,
                        )
                    )
                else:
                    chunks.append(
                        engine.render(
                            "sfc_assign",
                            target=self._sfc_variable(name),
                            condition=enabled,
                            indent=self.indent,
                        )
                    )
            for name, conditions in variable_sets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_set",
                        target=self._sfc_variable(name),
                        condition=enabled,
                        value=true_value,
                        indent=self.indent,
                    )
                )
            for name, conditions in variable_resets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_set",
                        target=self._sfc_variable(name),
                        condition=enabled,
                        value=false_value,
                        indent=self.indent,
                    )
                )
            for key, conditions in action_sets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_stored",
                        action=sfc_field("action_" + key, "stored"),
                        condition=enabled,
                        value=true_value,
                        indent=self.indent,
                    )
                )
            for key, conditions in action_resets.items():
                enabled = f" {or_op} ".join(f"({item})" for item in conditions)
                chunks.append(
                    engine.render(
                        "sfc_stored",
                        action=sfc_field("action_" + key, "stored"),
                        condition=enabled,
                        value=false_value,
                        indent=self.indent,
                    )
                )
            for key in sorted(stored_actions):
                action = chart["actions"][key]
                state = self._sfc_flag(sfc_field("action_" + key, "stored"))
                self.indent_inc()
                stored_body = self._capture_emission(
                    lambda: self.accept(action, lambda child_name: child_name == "function_block_body")
                )
                self.indent_dec()
                chunks.append(
                    engine.render(
                        "sfc_action", condition=state, body=stored_body, indent=self.indent
                    )
                )
            for step in chart["steps"]:
                chunks.append(
                    engine.render(
                        "sfc_previous",
                        step=step["name"],
                        active=sfc_field(step["name"], "active"),
                        previous=sfc_field(step["name"], "previous"),
                        indent=self.indent,
                    )
                )
            self.text += engine.render(
                "sfc_chart", body="".join(chunks), indent=self.indent,
                steps="", transitions="", actions="",
            )

    def visit_simple_type_declaration(self, node):
        name = self._first_named(node, "simple_type_name")
        array = self._first_named(node, "array_specification")
        structure = self._first_named(node, "structure_declaration")
        if name and array:
            self._emit_array_type(name["value"], array)
        elif name and structure:
            self._emit_structure_type(name["value"], structure)
        elif name:
            underlying = next(
                (self.iecType2C(item.get("value")) for item in self._named_nodes(node, "signed_integer_type_name") + self._named_nodes(node, "unsigned_integer_type_name") + self._named_nodes(node, "real_type_name") + self._named_nodes(node, "bit_string_type_name") if item.get("value")),
                "int16_t",
            )
            self.text += f"typedef {underlying} {name['value']};\n"

    def visit_data_type_declaration(self, node):
        if self._types_pre_emitted:
            return
        for declaration in self._named_nodes(node, "simple_type_declaration"):
            self.visit_simple_type_declaration(declaration)
        for declaration in self._named_nodes(node, "subrange_type_declaration"):
            self.visit_subrange_type_declaration(declaration)
        for declaration in self._named_nodes(node, "enumerated_type_declaration"):
            self.visit_enumerated_type_declaration(declaration)
        for declaration in self._named_nodes(node, "array_type_declaration"):
            self.visit_array_type_declaration(declaration)
        for declaration in self._named_nodes(node, "structure_type_declaration"):
            self.visit_structure_type_declaration(declaration)
        for declaration in self._named_nodes(node, "string_type_declaration"):
            self.visit_string_type_declaration(declaration)
        for declaration in self._named_nodes(node, "reference_type_declaration"):
            self.visit_reference_type_declaration(declaration)

    def visit_reference_type_declaration(self, node):
        name = self._first_named(node, "reference_type_name")
        specification = self._first_named(node, "reference_specification")
        if name is not None and specification is not None:
            target = self.extract_type(specification) or "int16_t"
            self.text += self.generator_engine.render("reference_type", name=name["value"], referenced_type=target)

    def visit_subrange_type_declaration(self, node):
        name = self._first_named(node, "subrange_type_name")
        if name:
            underlying = next(
                (self.iecType2C(item.get("value")) for item in self._named_nodes(node, "signed_integer_type_name") + self._named_nodes(node, "unsigned_integer_type_name") if item.get("value")),
                "int16_t",
            )
            self.text += f"typedef {underlying} {name['value']};\n"

    def visit_enumerated_type_declaration(self, node):
        name = self._first_named(node, "enumerated_type_name")
        values = [item["value"] for item in self._named_nodes(node, "enumerated_value") if item.get("value")]
        if name and values:
            self.text += f"typedef enum {name['value']} {{\n"
            for index, value in enumerate(values):
                comma = "," if index < len(values) - 1 else ""
                self.text += f"    {value}{comma}\n"
            self.text += f"}} {name['value']};\n"

    def visit_array_type_declaration(self, node):
        name = self._first_named(node, "array_type_name")
        spec = self._first_named(node, "array_specification")
        if name and spec:
            self._emit_array_type(name["value"], spec)

    def _emit_array_type(self, name, spec):
        sizes = self._array_dimensions(spec)
        element = self.declaration_type(spec)
        self.text += self.generator_engine.render("array_type", name=name, element_type=element, dimensions=sizes)

    def visit_string_type_declaration(self, node):
        name = self._first_named(node, "string_type_name")
        size = next((self.render(item) for item in self._named_nodes(node, "integer")), "80")
        if name:
            self.text += f"typedef char {name['value']}[{size} + 1];\n"

    def visit_structure_type_declaration(self, node):
        name = self._first_named(node, "structure_type_name")
        if not name:
            return
        self._emit_structure_type(name["value"], node)

    def _emit_structure_type(self, name, node):
        self.text += f"typedef struct {name} {{\n"
        self.indent_inc()
        for element in self._named_nodes(node, "structure_element_declaration"):
            field = self._first_named(element, "structure_element_name")
            if field:
                self.text += f"{self.indent}{self._format_declarator(self._declaration_type(element), field['value'])};\n"
        self.indent_dec()
        self.text += f"}} {name};\n"

    def _named_nodes(self, node, name):
        result = []
        if not isinstance(node, dict):
            return result
        if node.get("name") == name:
            result.append(node)
        for child in node.get("children", []):
            result.extend(self._named_nodes(child, name))
        return result

    def _emit_native_code(self, source):
        for line in source.splitlines():
            self.text += f"{self.indent}{line.rstrip()}\n" if line.strip() else "\n"

    def _first_named(self, node, name):
        if not isinstance(node, dict):
            return None
        if node.get("name") == name:
            return node
        for child in node.get("children", []):
            found = self._first_named(child, name)
            if found is not None:
                return found
        return None

    def visit_var1_init_decl(self, node):
        var_type = self.extract_type(node) or "int16_t"
        names = [child["value"] for child in node["children"][0]["children"]]
        self.text += f"{var_type} {', '.join(names)}"

    def visit_expression(self, node):
        key = "BIT_OR" if self._is_bitwise_expression(node) else "OR"
        operator = self.generator_engine.map("operator", key) if self.generator_engine is not None else ("|" if key == "BIT_OR" else "||")
        self._render_binary_chain(node["children"], operator)

    def visit_xor_expression(self, node):
        operator = self.generator_engine.map("operator", "XOR") if self.generator_engine is not None else "^"
        self._render_binary_chain(node["children"], operator)

    def visit_and_expression(self, node):
        key = "BIT_AND" if self._is_bitwise_expression(node) else "AND"
        operator = self.generator_engine.map("operator", key) if self.generator_engine is not None else ("&" if key == "BIT_AND" else "&&")
        self._render_binary_chain(node["children"], operator)

    def _render_binary_chain(self, children, operator):
        if not children:
            return
        expression = self.render(children[0])
        for child in children[1:]:
            right = self.render(child)
            expression = self.generator_engine.render(
                "binary_expression", left=expression, operator=operator, right=right
            ) if self.generator_engine is not None else f"({expression} {operator} {right})"
        self.text += expression

    def _is_bitwise_expression(self, node):
        bit_types = {"uint8_t", "uint16_t", "uint32_t", "uint64_t"}
        own_type = self.c_type_for_node(node)
        if own_type in bit_types:
            return True
        descendant_types = {
            self.c_type_for_node(item)
            for item in self._named_nodes(node, "variable_name")
        }
        return bool(descendant_types & bit_types) and "bool" not in descendant_types

    def visit_comparison(self, node):
        children = node.get("children", [])
        if len(children) == 3 and children[1].get("name") == "comparison_equality_operator":
            left, operator, right = children
            left_text, right_text = self.render(left), self.render(right)
            string_comparison = (
                self.c_type_for_node(left) == "const char *"
                or self.c_type_for_node(right) == "const char *"
                or left_text.startswith('"')
                or right_text.startswith('"')
            )
            if string_comparison:
                relation = "!=" if operator.get("value") in {"NEQ", "<>"} else "=="
                self.text += f"strcmp({left_text}, {right_text}) {relation} 0"
                return
        self._visit_infix(node)

    def visit_comparison_equality_operator(self, node):
        op = self.generator_engine.map("operator", node["value"]) if self.generator_engine is not None else {"=": "==", "NEQ": "!=", "<>": "!="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_equ_expression(self, node):
        self._render_alternating_infix(node)

    def visit_add_expression(self, node):
        self._render_alternating_infix(node)

    def _render_alternating_infix(self, node):
        children = node.get("children", [])
        if not children:
            return
        expression = self.render(children[0])
        index = 1
        while index + 1 < len(children):
            operator = self.render(children[index]).strip()
            right = self.render(children[index + 1])
            expression = self.generator_engine.render(
                "binary_expression", left=expression, operator=operator, right=right
            ) if self.generator_engine is not None else f"({expression} {operator} {right})"
            index += 2
        if index < len(children):
            expression += self.render(children[index])
        self.text += expression

    def visit_term(self, node):
        self._visit_infix_from_child_value(node)

    def visit_power_expression(self, node):
        children = [child for child in node.get("children", []) if isinstance(child, dict)]
        if len(children) == 1:
            self.visit(children[0])
        elif len(children) >= 2:
            # IEC exponentiation is right-associative: a ** b ** c is
            # equivalent to a ** (b ** c).
            expression = self.render(children[-1])
            for child in reversed(children[:-1]):
                expression = self.generator_engine.render(
                    "power_expression", left=self.render(child), right=expression
                ) if self.generator_engine is not None else f"pow({self.render(child)}, {expression})"
            self.text += expression

    def visit_unary_expression(self, node):
        op = node.get("value")
        if not op:
            self.accept(node)
            return
        child = next((item for item in node.get("children", []) if isinstance(item, dict)), None)
        operator_key = "BIT_NOT" if op == "NOT" and child is not None and self._is_bitwise_expression(child) else op
        symbol = self.generator_engine.map("operator", operator_key) if self.generator_engine is not None else (("~" if operator_key == "BIT_NOT" else "!") if op == "NOT" else op)
        operand = self.render(child) if child is not None else ""
        self.text += self.generator_engine.render(
            "unary_expression", UnaryExpression(symbol, operand)
        ) if self.generator_engine is not None else f"({symbol}({operand}))"

    def visit_add_operator(self, node):
        value = node["value"]
        mapped = self.generator_engine.map("operator", value) if self.generator_engine is not None else value
        self.text += f" {mapped} "

    def visit_comparison_operator(self, node):
        op = self.generator_engine.map("operator", node["value"]) if self.generator_engine is not None else {"LE_EQ": "<=", "GE_EQ": ">="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_assignment_statement(self, node):
        if self._emit_property_assignment(node):
            return
        if self.oop.emit_assignment(node):
            return
        variable = next(child for child in node["children"] if child.get("name") == "variable")
        expression = next(child for child in node["children"] if child.get("name") == "expression")
        lowered = Assignment(self.render(variable), self.render(expression), self.indent)
        self.text += self.generator_engine.render("assignment", lowered) if self.generator_engine is not None else f"{lowered.indent}{lowered.target} = {lowered.value};\n"

    def visit_reference_constructor(self, node):
        variable = self._first_named(node, "variable")
        self.text += self.generator_engine.render("reference", value=self.render(variable))

    def visit_reference_value(self, node):
        if node.get("value") == "NULL":
            self.text += self.generator_engine.render("null_reference")
        else:
            self.accept(node)

    def visit_dereferenced_variable(self, node):
        referenced = next(
            (child for child in node.get("children", []) if isinstance(child, dict)),
            None,
        )
        self.text += self.generator_engine.render("dereference", value=self.render(referenced))

    def visit_assert_statement(self, node):
        expression = next(child for child in node.get("children", []) if isinstance(child, dict))
        self.text += f"{self.indent}ASSERT({self.render(expression)});\n"

    def visit_exit_statement(self, node):
        self.text += self.generator_engine.render("exit", indent=self.indent) if self.generator_engine is not None else f"{self.indent}break;\n"

    def visit_continue_statement(self, node):
        self.text += self.generator_engine.render("continue", indent=self.indent) if self.generator_engine is not None else f"{self.indent}continue;\n"

    def visit_return_statement(self, node):
        expression = self._first_named(node, "expression")
        value = " " + self.render(expression) if expression is not None else ""
        self.text += self.generator_engine.render("return", indent=self.indent, value=value, has_value=bool(value)) if self.generator_engine is not None else f"{self.indent}return{value};\n"

    def _render_nested_body(self, node):
        self.indent_inc()
        try:
            return self.render(node)
        finally:
            self.indent_dec()

    def visit_if_statement(self, node):
        lowered = IfBranch(self.render(node["children"][0]), self._render_nested_body(node["children"][1]), self.indent)
        self.text += self.generator_engine.render("if", lowered) if self.generator_engine is not None else f"{self.indent}if ({lowered.condition}) {{\n{lowered.body}{self.indent}}}\n"
        self.accept(node, lambda name: name == "elseif_statement_list")
        self.accept(node, lambda name: name == "else_statement")

    def visit_elseif_statement(self, node):
        lowered = IfBranch(self.render(node["children"][0]), self._render_nested_body(node["children"][1]), self.indent)
        self.text += self.generator_engine.render("elseif", lowered) if self.generator_engine is not None else f"{self.indent}else if ({lowered.condition}) {{\n{lowered.body}{self.indent}}}\n"

    def visit_else_statement(self, node):
        self.indent_inc()
        previous = self.text
        self.text = ""
        try:
            self.accept(node)
            body = self.text
        finally:
            self.text = previous
            self.indent_dec()
        self.text += self.generator_engine.render("else", body=body, indent=self.indent) if self.generator_engine is not None else f"{self.indent}else {{\n{body}{self.indent}}}\n"

    def visit_while_statement(self, node):
        lowered = WhileLoop(self.render(node["children"][0]), self._render_nested_body(node["children"][1]), self.indent)
        self.text += self.generator_engine.render("while", lowered) if self.generator_engine is not None else f"{self.indent}while ({lowered.condition}) {{\n{lowered.body}{self.indent}}}\n"

    def visit_repeat_statement(self, node):
        lowered = RepeatLoop(self.render(node["children"][1]), self._render_nested_body(node["children"][0]), self.indent)
        self.text += self.generator_engine.render("repeat", lowered) if self.generator_engine is not None else f"{self.indent}do {{\n{lowered.body}{self.indent}}} while (!({lowered.condition}));\n"

    def visit_token(self, node):
        self.text += str(node.get("value", ""))

    def visit_control_variable(self, node):
        value = next((child.get("value") for child in node.get("children", []) if isinstance(child, dict)), "")
        if self.current_instance is not None and isinstance(value, str) and value.casefold() in self.current_instance_fields:
            self.text += f"{self.current_instance}->{value}"
        elif isinstance(value, str) and value.casefold() in self.current_pointer_params:
            self.text += f"(*{value})"
        else:
            self.accept(node)

    def visit_for_statement(self, node):
        control, for_list, body = node["children"][:3]
        parts = [child for child in for_list.get("children", []) if isinstance(child, dict)]
        start = parts[0]
        direction = str(parts[1].get("value", "TO")).upper() if len(parts) > 1 else "TO"
        end = parts[2] if len(parts) > 2 else parts[-1]
        by = parts[4] if len(parts) > 4 and parts[3].get("value") == "BY" else None
        variable = self.render(control)
        start_text = self.render(start)
        end_text = self.render(end)
        comparator = ">=" if direction == "DOWNTO" else "<="
        if by is None:
            step = f"{variable}--" if direction == "DOWNTO" else f"{variable}++"
        else:
            operator = "-=" if direction == "DOWNTO" else "+="
            step = f"{variable} {operator} {self.render(by)}"
        lowered_body = self._render_nested_body(body)
        self.text += self.source_line_directive(node)
        self.text += self.generator_engine.render(
            "for", variable=variable, start=start_text, end=end_text,
            step=self.render(by) if by is not None else "1",
            direction="descending" if direction == "DOWNTO" else "ascending",
            comparator=comparator, update=step, body=lowered_body, indent=self.indent,
        )

    def visit_case_statement(self, node):
        children = node.get("children", [])
        expression = next(child for child in children if child.get("name") == "expression")
        expression_text = self.render(expression)
        elements = []
        default_statements = None
        for child in children:
            if child.get("name") == "case_element":
                case_list = next(item for item in child["children"] if item.get("name") == "case_list")
                statements = next(item for item in child["children"] if item.get("name") == "statement_list")
                labels = []
                for label in (item for item in case_list.get("children", []) if item.get("name") == "case_list_element"):
                    subrange = self._first_named(label, "subrange")
                    if subrange is not None:
                        bounds = self._named_nodes(subrange, "signed_integer")
                        if len(bounds) == 2:
                            labels.append({"value": self.generator_engine.render(
                                "case_range", selector=expression_text,
                                lower=self.render(bounds[0]), upper=self.render(bounds[1]),
                            )})
                    else:
                        labels.append({"value": self.generator_engine.render(
                            "case_value", selector=expression_text, value=self.render(label)
                        )})
                label_text = self.generator_engine.render("case_labels", items=labels) or "false"
                body = self._render_nested_body(statements)
                rule = "case_element_first" if not elements else "case_element"
                elements.append(self.generator_engine.render(rule, labels=label_text, body=body, indent=self.indent))
            elif child.get("name") == "statement_list":
                default_statements = child
        else_body = ""
        if default_statements is not None:
            body = self._render_nested_body(default_statements)
            rule = "case_else" if elements else "case_else_first"
            else_body = self.generator_engine.render(rule, body=body, indent=self.indent, has_elements=bool(elements))
        self.text += self.source_line_directive(node)
        self.text += self.generator_engine.render(
            "case", selector=expression_text, elements="".join(elements), else_body=else_body, indent=self.indent
        )

    def visit_case_element(self, node):
        case_list = next(child for child in node["children"] if child.get("name") == "case_list")
        statements = next(child for child in node["children"] if child.get("name") == "statement_list")
        labels = [child for child in case_list.get("children", []) if child.get("name") == "case_list_element"]
        for label in labels:
            self.text += f"{self.indent}case {self.render(label)}:\n"
        self.indent_inc()
        self.visit(statements)
        self.text += f"{self.indent}break;\n"
        self.indent_dec()

    def visit_fb_invocation(self, node):
        self.text += f"{self.indent}(void)0;\n"

    def visit_method_invocation(self, node):
        self.text += self.oop.render_invocation(node)

    def visit_method_call_statement(self, node):
        invocation = self._first_named(node, "method_invocation")
        self.text += f"{self.indent}{self.oop.render_invocation(invocation)};\n"

    def visit_class_declaration(self, node):
        # Edition 3 classes are emitted by OOPCEmitter in visit_library().
        return

    def visit_interface_declaration(self, node):
        # Edition 3 interfaces are emitted by OOPCEmitter in visit_library().
        return

    def visit_method_declaration(self, node):
        # Methods are emitted as part of their owning class.
        return

    def visit_method_prototype(self, node):
        # Interface method prototypes are emitted in the interface vtable.
        return

    def visit_configuration_declaration(self, node):
        name_node = self._first_named(node, "configuration_name")
        if name_node is None:
            return
        name = name_node["value"]
        tasks = {}
        for task in self._named_nodes(node, "task_configuration"):
            task_name_node = self._first_named(task, "task_name")
            if task_name_node is None:
                continue
            initialization = self._first_named(task, "task_initialization")
            values = [str(value).upper() for value in self._raw_values(initialization)] if initialization else []
            duration = self._first_named(initialization, "duration") if initialization else None
            interval = int(self.render(duration)) if duration is not None else 1
            integers = self._named_nodes(initialization, "integer") if initialization else []
            priority = int(str(integers[-1].get("value", "0")).replace("_", "")) if integers else 0
            tasks[task_name_node["value"].casefold()] = {
                "name": task_name_node["value"], "interval": max(interval, 1), "priority": priority,
                "single": "SINGLE" in values,
            }

        programs = []
        for program in self._named_nodes(node, "program_configuration"):
            instance_node = self._first_named(program, "program_name")
            type_node = self._first_named(program, "program_type_name")
            if instance_node is None or type_node is None:
                continue
            task_node = self._first_named(program, "task_name")
            tokens = {value.upper() for value in self._raw_values(program)}
            programs.append({
                "instance": instance_node["value"], "type": type_node["value"],
                "task": task_node["value"].casefold() if task_node else None,
                "retain": "RETAIN" in tokens, "non_retain": "NON_RETAIN" in tokens,
            })

        self.text += f"/* IEC configuration {name}. */\n"
        self.text += "/* Persistent program instances. Each instance owns independent scan state. */\n"
        for program in programs:
            self.text += f"{program['type']} {name}_{program['instance']};\n"
        if tasks:
            self.text += "\n/* Elapsed-time accumulators used by cyclic tasks. */\n"
        for task in tasks.values():
            self.text += f"static uint64_t {name}_{task['name']}_elapsed_ms;\n"
            self.text += f"/* Task {task['name']}: interval {task['interval']} ms, priority {task['priority']}. */\n"
        self.text += "\n"

        self.text += "/* Initialize every program instance and scheduler for a cold start. */\n"
        self.text += f"void {name}_cold_start(void)\n{{\n"
        for program in programs:
            self.text += f"    {program['type']}_cold_init(&{name}_{program['instance']});\n"
        for task in tasks.values():
            self.text += f"    {name}_{task['name']}_elapsed_ms = 0;\n"
        self.text += "}\n\n"

        self.text += "/* Restart execution while preserving retentive program state. */\n"
        self.text += f"void {name}_warm_start(void)\n{{\n"
        for program in programs:
            target = f"{name}_{program['instance']}"
            if program["retain"]:
                continue
            if program["non_retain"]:
                self.text += f"    {program['type']}_cold_init(&{target});\n"
            else:
                self.text += f"    {program['type']}_warm_init(&{target});\n"
        for task in tasks.values():
            self.text += f"    {name}_{task['name']}_elapsed_ms = 0;\n"
        self.text += "}\n\n"

        self.text += "/* Return the shortest configured cyclic-task interval. */\n"
        self.text += f"uint64_t {name}_base_interval_ms(void)\n{{\n"
        base_interval = min((task["interval"] for task in tasks.values()), default=1)
        self.text += f"    return UINT64_C({base_interval});\n}}\n\n"

        self.text += "/* Advance the scheduler while preserving chronological task order. */\n"
        self.text += f"void {name}_cycle(uint64_t elapsed_ms)\n{{\n"
        for program in programs:
            if program["task"] is None:
                self.text += f"    {program['type']}_run(&{name}_{program['instance']});\n"

        scheduled_tasks = sorted(
            tasks.values(),
            key=lambda item: (item["priority"], item["name"].casefold()),
        )

        if scheduled_tasks:
            self.text += "    uint64_t remaining_ms = elapsed_ms;\n"

            for task in scheduled_tasks:
                if task["single"]:
                    self.text += f"    bool {name}_{task['name']}_fired = false;\n"

            self.text += "    while (remaining_ms > 0) {\n"
            self.text += "        uint64_t next_due_ms = UINT64_MAX;\n"

            for task in tasks.values():
                elapsed_name = f"{name}_{task['name']}_elapsed_ms"
                interval = task["interval"]
                if task["single"]:
                    self.text += f"        if (!{name}_{task['name']}_fired) {{\n"
                    indent = "            "
                else:
                    indent = "        "
                self.text += (
                    f"{indent}uint64_t until_due_ms = "
                    f"UINT64_C({interval}) - {elapsed_name};\n"
                )
                self.text += (
                    f"{indent}if (until_due_ms < next_due_ms) "
                    "next_due_ms = until_due_ms;\n"
                )
                if task["single"]:
                    self.text += "        }\n"

            self.text += "        if (next_due_ms > remaining_ms) {\n"
            for task in tasks.values():
                elapsed_name = f"{name}_{task['name']}_elapsed_ms"
                if task["single"]:
                    self.text += (
                        f"            if (!{name}_{task['name']}_fired) "
                        f"{elapsed_name} += remaining_ms;\n"
                    )
                else:
                    self.text += f"            {elapsed_name} += remaining_ms;\n"
            self.text += "            break;\n"
            self.text += "        }\n"

            for task in tasks.values():
                elapsed_name = f"{name}_{task['name']}_elapsed_ms"
                if task["single"]:
                    self.text += (
                        f"        if (!{name}_{task['name']}_fired) "
                        f"{elapsed_name} += next_due_ms;\n"
                    )
                else:
                    self.text += f"        {elapsed_name} += next_due_ms;\n"
            self.text += "        remaining_ms -= next_due_ms;\n"

            for task in scheduled_tasks:
                assigned = [
                    program for program in programs
                    if program["task"] == task["name"].casefold()
                ]
                elapsed_name = f"{name}_{task['name']}_elapsed_ms"
                interval = task["interval"]
                condition = f"{elapsed_name} >= UINT64_C({interval})"
                if task["single"]:
                    condition = f"!{name}_{task['name']}_fired && ({condition})"
                self.text += f"        if ({condition}) {{\n"
                self.text += f"            {elapsed_name} -= UINT64_C({interval});\n"
                for program in assigned:
                    self.text += (
                        f"            {program['type']}_run("
                        f"&{name}_{program['instance']});\n"
                    )
                if task["single"]:
                    self.text += f"            {elapsed_name} = 0;\n"
                    self.text += f"            {name}_{task['name']}_fired = true;\n"
                self.text += "        }\n"

            self.text += "    }\n"

        self.text += "}\n\n"

    def _join_children(self, node, separator, parenthesize_operands=False):
        children = node["children"]
        wrap = parenthesize_operands and len(children) > 1
        for index, child in enumerate(children):
            if index:
                self.text += separator
            if wrap:
                self.text += "("
            self.visit(child)
            if wrap:
                self.text += ")"

    def _visit_infix(self, node):
        for child in node["children"]:
            self.visit(child)

    def _visit_infix_from_child_value(self, node):
        children = node["children"]
        if not children:
            return
        self.visit(children[0])
        for child in children[1:]:
            raw_op = child.get("value")
            op = self.generator_engine.map("operator", raw_op) if self.generator_engine is not None else {"MOD": "%"}.get(raw_op, raw_op)
            self.text += f" {op} "
            if op == "%":
                self.text += "((int64_t)("
                self.visit(child)
                self.text += "))"
            else:
                self.visit(child)
