"""Backend-neutral IEC lowering algorithms shared by reference adapters."""

import re
from ...parsing.strings import decode_character_literal
from ...analysis.strings import target_string_spec

from ...analysis.types import ArrayType, EnumType

from .sfc import charts as sfc_charts, field as sfc_field
from .ir import Assignment, Call, Cast, IfBranch, Literal, RepeatLoop, UnaryExpression, WhileLoop


class SharedLowering:
    def _bounded_string_value(self, target, value):
        spec = target_string_spec(self.context, target)
        if spec is None:
            return value
        kind, capacity = spec
        wide = self.generator_engine.map("boolean_literal", "TRUE" if kind == "WSTRING" else "FALSE")
        return f"STC_STRING_CHECK({value}, {capacity}, {wide})"

    def _needs_string_checks(self, ast):
        return any(target_string_spec(self.context, n.get("children", [{}])[0]) is not None
                   for n in self._named_nodes(ast, "assignment_statement"))

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
        return self.generator_engine.render("unary_expression", operator=self.generator_engine.map("operator", "NOT"), operand=expression)


    def _il_true(self):
        return self.generator_engine.map("boolean_literal", "TRUE")


    def _il_false(self):
        return self.generator_engine.map("boolean_literal", "FALSE")


    def _il_assignment(self, target, expression):
        return self.generator_engine.render("assignment", target=target, value=expression, indent="").rstrip()


    def _il_emit_line(self, statement):
        self.text += f"{self.indent}{statement}\n"


    def _il_has_jumps(self, instructions):
        jump_opcodes = {"JMP", "JMPC", "JMPCN"}
        for instruction in instructions:
            for child in instruction.get("children", []):
                if isinstance(child, dict) and self._il_token(child) in jump_opcodes:
                    return True
        return False


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


    def _il_label_index(self, instructions, destination):
        wanted = str(destination or "").casefold()
        for index, instruction in enumerate(instructions):
            for label in self._il_labels(instruction):
                if str(label.get("value", "")).casefold() == wanted:
                    return index
        return len(instructions)


    def visit_configuration_declaration(self, node):
        name_node = self._first_named(node, "configuration_name")
        if name_node is None:
            return
        name = name_node["value"]
        tasks = {}
        for task in self._named_nodes(node, "task_configuration"):
            task_name = self._first_named(task, "task_name")
            initialization = self._first_named(task, "task_initialization")
            if task_name is None:
                continue
            duration = self._first_named(initialization, "duration") if initialization else None
            interval = max(int(self.render(duration)) if duration is not None else 1, 1)
            integers = self._named_nodes(initialization, "integer") if initialization else []
            priority = int(str(integers[-1].get("value", "0")).replace("_", "")) if integers else 0
            values = {str(value).upper() for value in self._raw_values(initialization)}
            tasks[task_name["value"].casefold()] = dict(
                config=name, name=task_name["value"], interval=interval,
                priority=priority, single="SINGLE" in values,
            )
        programs = []
        for program in self._named_nodes(node, "program_configuration"):
            instance = self._first_named(program, "program_name")
            type_node = self._first_named(program, "program_type_name")
            if instance is None or type_node is None:
                continue
            task = self._first_named(program, "task_name")
            values = {str(value).upper() for value in self._raw_values(program)}
            programs.append(dict(config=name, instance=instance["value"], type=type_node["value"],
                                 task=task["value"].casefold() if task else None,
                                 retain="RETAIN" in values, non_retain="NON_RETAIN" in values))
        engine = self.generator_engine
        def render(rule, records, **extra):
            return "".join(engine.render(rule, item, **extra) for item in records)
        declarations = engine.render("scheduler_declarations", name=name,
            programs=render("scheduler_program", programs), tasks=render("scheduler_task", tasks.values()))
        reset = render("scheduler_reset", tasks.values())
        cold = render("scheduler_init", programs, method="cold_init")
        warm = "".join(engine.render("scheduler_init", program,
            method="cold_init" if program["non_retain"] else "warm_init")
            for program in programs if not program["retain"])
        defaults = render("scheduler_program_default", programs) + render("scheduler_task_default", tasks.values())
        free = render("scheduler_run", [p for p in programs if p["task"] is None], indent="        ")
        scheduled = sorted(tasks.values(), key=lambda item: (item["priority"], item["name"].casefold()))
        loop = ""
        if scheduled:
            def task_render(rule, **extra):
                return "".join(engine.render(rule + ("_single" if t["single"] else ""), t, **extra) for t in tasks.values())
            singles = render("scheduler_single_decl", [t for t in scheduled if t["single"]])
            due = task_render("scheduler_due")
            remainder = task_render("scheduler_advance", indent="                ", delta="remaining_ms")
            advance = task_render("scheduler_advance", indent="            ", delta="next_due_ms")
            fire = "".join(engine.render("scheduler_fire" + ("_single" if t["single"] else ""), t,
                calls=render("scheduler_run", [p for p in programs if p["task"] == t["name"].casefold()], indent="                ")) for t in scheduled)
            loop = engine.render("scheduler_loop", singles=singles, due=due, remainder=remainder, advance=advance, fire=fire)
        body = engine.render("scheduler_body", name=name, base=min((t["interval"] for t in tasks.values()), default=1),
            cold=cold, warm=warm, reset=reset, defaults=defaults, free=free, loop=loop)
        self.text += engine.render("configuration", name=name, declarations=declarations, body=body)


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


    def _raw_values(self, node):
        if isinstance(node, str):
            yield node
        elif isinstance(node, dict):
            value = node.get("value")
            if isinstance(value, str):
                yield value
            for child in node.get("children", []):
                yield from self._raw_values(child)


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


    def _retained_declarations(self, node):
        return self.collect_sections(node, "retentive_var_declarations")


    def _iter_named_set(self, node, names):
        if not isinstance(node, dict):
            return
        if node.get("name") in names:
            yield node
            return
        for child in node.get("children", []):
            yield from self._iter_named_set(child, names)


    def _capture_emission(self, callback):
        previous = self.text
        self.text = ""
        try:
            callback()
            return self.text
        finally:
            self.text = previous


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


    def visit_integer(self, node):
        self.text += node["value"].replace("_", "")


    def visit_signed_integer(self, node):
        if node.get("value") is not None:
            self.text += str(node["value"]).replace("_", "")
        else:
            self.accept(node)


    def visit_binary_integer(self, node):
        self._visit_based_integer(node, 2)


    def visit_octal_integer(self, node):
        self._visit_based_integer(node, 8)


    def visit_hex_integer(self, node):
        self._visit_based_integer(node, 16)


    def visit_bit_string_literal(self, node):
        for child in node["children"]:
            self.visit(child)


    def _iec_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "''")) if token else "''"
        return self.string_literal(decode_character_literal(raw))

    @staticmethod
    def _unicode_content(raw):
        return decode_character_literal(raw)


    def visit_unicode_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "U#''")) if token else "U#''"
        content = self._unicode_content(raw)
        prefix = raw[:raw.find("#")].strip().upper() if "#" in raw else ""
        if prefix == "UCHAR" or (prefix == "U" and len(content) == 1):
            self.text += str(ord(content[0]) if content else 0)
            return
        self.text += self.string_literal(content)

    @staticmethod
    def _typed_character_content(raw):
        return decode_character_literal(raw)


    def visit_typed_character_string(self, node):
        token = self._first_named(node, "token")
        raw = str(token.get("value", "STRING#''")) if token else "STRING#''"
        prefix = raw[:raw.find("#")].strip().upper()
        content = self._typed_character_content(raw)
        if prefix in {"CHAR", "WCHAR"}:
            self.text += str(ord(content[0]) if content else 0)
            return
        self.text += self.string_literal(content)


    def visit_single_byte_character_string(self, node):
        self.text += self._iec_string(node)


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


    def visit_field_selector(self, node):
        self.text += str(node.get("value", ""))


    def visit_standard_function_name(self, node):
        self.text += node["value"]


    def visit_derived_function_name(self, node):
        self.text += node["value"]


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


    def visit_enumerated_type_declaration(self, node):
        name = self._first_named(node, "enumerated_type_name")
        values = [item["value"] for item in self._named_nodes(node, "enumerated_value") if item.get("value")]
        if name and values:
            rendered = "".join(self.generator_engine.render(
                "enum_value", name=value, first=self.generator_engine.render("enum_default_marker") if index == 0 else "",
                comma="," if index < len(values) - 1 else "",
            ) for index, value in enumerate(values))
            self.text += self.generator_engine.render("enum_type", name=name["value"], values=rendered)


    def visit_string_type_declaration(self, node):
        name = self._first_named(node, "string_type_name")
        size = next((self.render(item) for item in self._named_nodes(node, "integer")), "80")
        if name:
            self.text += self.generator_engine.render("string_type", name=name["value"], size=size)


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


    def _render_nested_body(self, node):
        self.indent_inc()
        try:
            return self.render(node)
        finally:
            self.indent_dec()


    def visit_token(self, node):
        self.text += str(node.get("value", ""))


    def visit_method_declaration(self, node):
        # Methods are emitted as part of their owning class.
        return


    def visit_method_prototype(self, node):
        # Interface method prototypes are emitted in the interface vtable.
        return


    def _visit_infix(self, node):
        for child in node["children"]:
            self.visit(child)


    def _format_declarator(self, var_type, name, pointer=False):
        engine = self.generator_engine
        patterns = engine.bundle.rules["layout_patterns"].mapping
        array = re.fullmatch(patterns["array"], var_type)
        if array:
            return engine.render("array_pointer_declarator" if pointer else "array_declarator",
                                 name=name, **array.groupdict())
        separator = "" if re.fullmatch(patterns["attached_name"], var_type) else " "
        return engine.render("pointer_declarator" if pointer else "declarator",
                             type=var_type, name=name, separator=separator)

    def zero_value(self, type_name):
        engine = self.generator_engine
        mapping = engine.bundle.rules["zero_value"].mapping
        if type_name in mapping:
            return mapping[type_name]
        patterns = engine.bundle.rules["layout_patterns"].mapping
        if re.fullmatch(patterns["reference"], type_name):
            return engine.render("zero_reference")
        if re.fullmatch(patterns["vector"], type_name):
            return engine.render("zero_vector")
        array = re.fullmatch(patterns["array_value"], type_name)
        if array:
            return engine.render("zero_array", value=self.zero_value(array["type"].strip()), size=array["size"].strip())
        if self.context is not None:
            datatype = self.context.declared_types.get(type_name.casefold())
            if isinstance(datatype, ArrayType):
                return engine.render("zero_named_array")
            if isinstance(datatype, EnumType) and datatype.elements:
                return engine.render("zero_enum", type=type_name, value=datatype.elements[0])
        return engine.render("zero_default")


class OopModel:
    """Resolved hierarchy queries shared by both target adapters."""

    def __init__(self, generator):
        self.generator = generator

    @property
    def classes(self):
        context = self.generator.context
        return context.oop_types.get("classes", {}) if context is not None else {}

    @property
    def interfaces(self):
        context = self.generator.context
        return context.oop_types.get("interfaces", {}) if context is not None else {}

    def class_for(self, value):
        return value if isinstance(value, dict) else self.classes.get(str(value or "").casefold())

    def own_fields(self, cls):
        result = []
        def collect(node):
            if not isinstance(node, dict) or node.get("name") in {"method_declaration", "method_prototype"}:
                return
            if node.get("name") in {"input_declarations", "output_declarations", "input_output_declarations",
                                    "var_declarations", "retentive_var_declarations", "non_retentive_var_decls"}:
                result.extend(self.generator.collect_var_decls(node))
                return
            for child in node.get("children", []):
                collect(child)
        collect(cls["node"])
        return self.generator._unique_declarations(result)

    def field_paths(self, cls):
        result = {}
        base = self.class_for(cls.get("base"))
        if base is not None:
            result.update({key: "__base." + value for key, value in self.field_paths(base).items()})
        for _, field in self.own_fields(cls):
            result[field.casefold()] = field
        return result

    def implemented_interfaces(self, cls):
        result = {}
        base = self.class_for(cls.get("base"))
        if base is not None:
            for interface in self.implemented_interfaces(base):
                result[interface["key"]] = interface
        def include(interface):
            if interface["key"] in result:
                return
            result[interface["key"]] = interface
            for parent in interface.get("extends", []):
                resolved = self.interfaces.get(parent.casefold())
                if resolved is not None:
                    include(resolved)
        for name in cls.get("interfaces", []):
            interface = self.interfaces.get(name.casefold())
            if interface is not None:
                include(interface)
        return list(result.values())
