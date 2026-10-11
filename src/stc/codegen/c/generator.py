# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate portable C code from the analyzed Structured Text AST."""

import re

from ..common.byte_arrays import emit_store as emit_byte_array_store, emit_call as emit_byte_array_call
from ..common.visitor import NodeVisitor
from ..common.lowering import OopModel, SharedLowering
from ..common.sfc import charts as sfc_charts, field as sfc_field, state_declarations as sfc_state_declarations
from ..common.templates.engine import GeneratorEngine
from ..common.ir import Assignment, Call, Cast, IfBranch, Literal, RepeatLoop, UnaryExpression, WhileLoop
from ..common.templates.loader import GeneratorBundle, bundled_generator, load_generator
from ...library.loader import render_primitives
from ..common.string_literals import c_string_literal


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
            items=[self._field_item(var_type, field) for var_type, field in own_fields],
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
                self.g.generator_engine.render("local_variable", indent="    ", declaration=self.g._format_declarator(var_type, var_name), name="", type="", value="{0}")
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
        return OopModel(self.g).own_fields(cls)

    def _field_item(self, var_type, field):
        """Split array dimensions off the type so C keeps them on the name."""
        engine = self.g.generator_engine
        patterns = engine.bundle.rules["layout_patterns"].mapping
        match = re.fullmatch(patterns["array"], var_type)
        if match:
            return {"type": match.group("type"), "name": field + match.group("dimensions")}
        return {"type": var_type, "name": field}

    def _field_paths(self, cls):
        return OopModel(self.g).field_paths(cls)

    def _vptr_path(self, cls):
        base = self._class(cls.get("base")) if cls else None
        return "__vptr" if base is None else "__base." + self._vptr_path(base)

    def _class(self, value):
        return OopModel(self.g).class_for(value)

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
        return OopModel(self.g).implemented_interfaces(cls)

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


class CCodeGenerator(SharedLowering, NodeVisitor):
    string_literal = staticmethod(c_string_literal)



    def _il_operation(self, instruction):
        return next(
            (child for child in instruction.get("children", []) if isinstance(child, dict) and child.get("name") != "label" and child.get("name") != "token"),
            None,
        )


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
            return self.generator_engine.render("reference_inline", type=self.extract_type(reference) or fallback)
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "unicode_string_spec") is not None:
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


    def _string_max_length(self, expression):
        """Return the declared maximum length of an IEC string expression."""
        if expression is None or self.context is None:
            return None
        variable = self._first_named(expression, "variable_name")
        if variable is None:
            return None
        symbol = self.context.symbols.symbol_for_reference(variable)
        if symbol is None or symbol.type_ref is None:
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
            return self.generator_engine.render("reference_inline", type=self.extract_type(reference) or self.iecType2C("INT"))
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "unicode_string_spec") is not None:
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


    def _emit_section(self, title):
        self.text += self.generator_engine.render("section_header", title=title, padding="-" * max(1, 68 - len(title)))

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


    def _temporary_declarations(self, node):
        return self.collect_sections(node, "temp_var_decls")


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


    def text_append(self, value):
        self.text += value


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


    def visit_boolean_literal(self, node):
        self.text += (
            self.generator_engine.map("boolean_literal", node["value"].upper())
            if self.generator_engine is not None else node["value"].lower()
        )


    def visit_double_byte_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", '""')) if token else '""'
        self.text += self._iec_string(node)


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

    def _is_wstring_expression(self, expression):
        """Return True when an expression statically refers to WSTRING."""
        if expression is None or self.context is None:
            return False
        datatype = self.context.type_of(expression)
        if datatype is not None and getattr(datatype, "name", "").upper() == "WSTRING":
            return True
        variable = self._first_named(expression, "variable_name")
        if variable is not None:
            symbol = self.context.symbols.symbol_for_reference(variable)
            if symbol is not None and symbol.type_ref is not None:
                return str(symbol.type_ref.name or "").upper() == "WSTRING"
        return False

    def visit_library(self, node):
        self._emit_section("IEC 61131-3 runtime support")
        self.oop.prepare(node)
        requested = {
            str(item.get("value", "")).upper()
            for item in self._named_nodes(node, "standard_function_name")
        }
        if self._named_nodes(node, "assert_statement"):
            requested.add("ASSERT")
        if self._needs_string_checks(node):
            requested.add("STC_STRING_CHECK")
        if "LEN_CODE_UNIT" in requested:
            requested.add("WSTRING_LEN_CODE_UNIT")
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
                self.text += self.generator_engine.render("global_constant" if is_constant else "global_variable", name=name, type=var_type, value=initial_value, declaration=self._format_declarator(var_type, name), is_constant="1" if is_constant else "")
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


    def visit_primary_expression(self, node):
        if emit_byte_array_call(self, node):
            return
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

        if standard_name_value == "LEN_CODE_UNIT":
            argument = self._first_named(node, "expression")
            if self._is_wstring_expression(argument):
                self.text += f"WSTRING_LEN_CODE_UNIT({self.render(argument)})"
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
            locals_text += self.generator_engine.render("local_variable", indent="    ", declaration=self._format_declarator(return_type, name), name="", type="", value="{0}")
        for var_type, var_name in local_decls:
            locals_text += self.generator_engine.render("local_variable", indent="    ", declaration=self._format_declarator(var_type, var_name), name="", type="", value="{0}")
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

        fields = "".join(self.generator_engine.render("state_field", indent="    ", declaration=self._format_declarator(t, n), name="", type="") for t, n in declarations) or "    uint8_t _stc_empty;\n"
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
            temporaries_text += self.generator_engine.render("local_variable", indent="    ", declaration=self._format_declarator(var_type, var_name), name="", type="", value="{0}")
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
                locals_text += self.generator_engine.render("local_variable", indent="    ", declaration=self._format_declarator(var_type, local), name="", type="", value="{0}")

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
        fields = "".join(self.generator_engine.render("state_field", indent="    ", declaration=self._format_declarator(var_type, var_name), name="", type="") for var_type, var_name in declarations)
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
            temporaries_text += self.generator_engine.render("local_variable", indent="    ", declaration=self._format_declarator(var_type, var_name), name="", type="", value="{0}")
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


    def _sfc_state_types(self):
        """Return backend-spelled (bool, time) types for SFC state fields."""
        if self.generator_engine is not None:
            return (
                self.generator_engine.map("type", "BOOL"),
                self.generator_engine.map("type", "TIME"),
            )
        return ("bool", "int64_t")


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
            self.text += self.generator_engine.render("type_alias", type=underlying, name=name["value"], kind="derived")

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
            self.text += self.generator_engine.render("type_alias", type=underlying, name=name["value"], kind="derived")


    def visit_array_type_declaration(self, node):
        name = self._first_named(node, "array_type_name")
        spec = self._first_named(node, "array_specification")
        if name and spec:
            self._emit_array_type(name["value"], spec)

    def _emit_array_type(self, name, spec):
        sizes = self._array_dimensions(spec)
        element = self.declaration_type(spec)
        self.text += self.generator_engine.render("array_type", name=name, element_type=element, dimensions=sizes)


    def visit_structure_type_declaration(self, node):
        name = self._first_named(node, "structure_type_name")
        if not name:
            return
        self._emit_structure_type(name["value"], node)

    def _emit_structure_type(self, name, node):
        fields = []
        self.indent_inc()
        for element in self._named_nodes(node, "structure_element_declaration"):
            field = self._first_named(element, "structure_element_name")
            if field:
                var_type = self._declaration_type(element)
                fields.append(self.generator_engine.render(
                    "structure_field", indent=self.indent, type=var_type,
                    name=field["value"], declaration=self._format_declarator(var_type, field["value"]),
                ))
        self.indent_dec()
        self.text += self.generator_engine.render("structure_type", name=name, fields="".join(fields))

    def _named_nodes(self, node, name):
        result = []
        if not isinstance(node, dict):
            return result
        if node.get("name") == name:
            result.append(node)
        for child in node.get("children", []):
            result.extend(self._named_nodes(child, name))
        return result


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
        if emit_byte_array_store(self, node):
            return
        if self._emit_property_assignment(node):
            return
        if self.oop.emit_assignment(node):
            return
        variable = next(child for child in node["children"] if child.get("name") == "variable")
        expression = next(child for child in node["children"] if child.get("name") == "expression")
        lowered = Assignment(self.render(variable), self._bounded_string_value(variable, self.render(expression)), self.indent)
        self.text += self.generator_engine.render("assignment", lowered) if self.generator_engine is not None else f"{lowered.indent}{lowered.target} = {lowered.value};\n"


    def visit_exit_statement(self, node):
        self.text += self.generator_engine.render("exit", indent=self.indent) if self.generator_engine is not None else f"{self.indent}break;\n"

    def visit_continue_statement(self, node):
        self.text += self.generator_engine.render("continue", indent=self.indent) if self.generator_engine is not None else f"{self.indent}continue;\n"

    def visit_return_statement(self, node):
        expression = self._first_named(node, "expression")
        value = " " + self.render(expression) if expression is not None else ""
        self.text += self.generator_engine.render("return", indent=self.indent, value=value, has_value=bool(value)) if self.generator_engine is not None else f"{self.indent}return{value};\n"


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
        if not self._emit_fb_invocation(node):
            self.text += f"{self.indent}(void)0;\n"

    def _emit_fb_invocation(self, node):
        """Lower an FB invocation to input assignments plus the step call."""
        if self.context is None:
            return False
        target = self._first_named(node, "fb_name") or self._first_named(node, "array_variable")
        if target is None:
            return False
        scope = self.context.symbols.scope_for(node)
        type_name = None
        instance = None
        if target.get("name") == "fb_name":
            key = str(target.get("value", "")).casefold()
            symbol = scope.lookup(key) if scope is not None else None
            if symbol is None or symbol.type_ref is None or not symbol.type_ref.name:
                return False
            type_name = symbol.type_ref.name
            if self.current_instance is not None and key in self.current_instance_fields:
                path = self.current_instance_field_paths.get(key, target.get("value", ""))
                instance = f"{self.current_instance}->{path}"
            else:
                instance = target.get("value", "")
        else:
            instance = self.render(target)
            type_name = self.c_type_for_node(target)
            if type_name is None:
                return False
        native = self.native_implementations.get(type_name.casefold())
        entry = "loop" if native is not None and native.kind == "function_block" else "step"
        formals = []
        positionals = []
        for child in node.get("children", []):
            if not isinstance(child, dict) or child.get("name") != "param_assignment":
                continue
            raw = child.get("children", [])
            if len(raw) > 1 and isinstance(raw[1], dict) and raw[1].get("value") in {":=", "=>"}:
                formals.append((raw[0].get("value", ""), raw[1].get("value", ""), child))
            else:
                expression = self._first_named(child, "expression")
                positionals.append(expression if expression is not None else child)
        if positionals:
            fb_symbol = self.context.symbols.lookup(type_name)
            declaration = fb_symbol.declaration if fb_symbol is not None else None
            ordered = [name for _, name in self.collect_sections(declaration, "input_declarations")] if declaration is not None else []
            if len(ordered) < len(positionals):
                return False
            for name, expression in zip(ordered, positionals):
                formals.append((name, ":=", expression))
        rendered = []
        for name, operator, source in formals:
            expression = self._first_named(source, "expression") if isinstance(source, dict) and source.get("name") == "param_assignment" else source
            if expression is None:
                return False
            rendered.append((name, operator, self.render(expression)))
        for name, operator, value in rendered:
            if operator == "=>":
                self.text += f"{self.indent}{value} = {instance}.{name};\n"
            else:
                self.text += f"{self.indent}{instance}.{name} = {value};\n"
        self.text += f"{self.indent}{type_name}_{entry}(&({instance}));\n"
        return True

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
