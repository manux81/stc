from nodevisitor import NodeVisitor
from iec_runtime_c import C_RUNTIME_FUNCTIONS


class CCodeGenerator(NodeVisitor):
    def __init__(self, context=None, source_name="<stdin>", native_implementations=None):
        self.context = context
        self.source_name = source_name
        self.native_implementations = native_implementations or {}
        self.text = "#include <stdbool.h>\n#include <stdint.h>\n#include <math.h>\n\n"
        self.indent = ""
        self.current_function = None
        self.current_return_type = None

    def iecType2C(self, typein):
        conv = {
            "SINT": "int8_t", "INT": "int16_t", "DINT": "int32_t", "LINT": "int64_t",
            "USINT": "uint8_t", "UINT": "uint16_t", "UDINT": "uint32_t", "ULINT": "uint64_t",
            "REAL": "float", "LREAL": "double",
            "BOOL": "bool", "BYTE": "uint8_t", "WORD": "uint16_t", "DWORD": "uint32_t",
            "LWORD": "uint64_t",
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

    def zero_value(self, c_type):
        if c_type == "bool":
            return "false"
        if c_type in ("float", "double"):
            return "0.0"
        return "0"

    def collect_var_decls(self, node):
        declarations = []
        if not isinstance(node, dict):
            return declarations
        if node.get("name") == "var1_init_decl":
            names = []
            var_list = node["children"][0]
            for child in var_list.get("children", []):
                if child.get("name") == "variable_name":
                    names.append(child["value"])
            var_type = self.extract_type(node["children"][1]) or "int16_t"
            declarations.extend((var_type, name) for name in names)
            return declarations
        for child in node.get("children", []):
            declarations.extend(self.collect_var_decls(child))
        return declarations

    def collect_sections(self, node, section_name):
        if not isinstance(node, dict):
            return []
        if node.get("name") == section_name:
            return self.collect_var_decls(node)
        declarations = []
        for child in node.get("children", []):
            declarations.extend(self.collect_sections(child, section_name))
        return declarations

    def visit_integer_literal(self, node):
        self.text += node["value"].replace("_", "")

    def visit_real_literal(self, node):
        self.text += node["value"].replace("_", "")

    def visit_integer(self, node):
        self.text += node["value"].replace("_", "")

    def visit_signed_integer(self, node):
        if node.get("value") is not None:
            self.text += str(node["value"]).replace("_", "")
        else:
            self.accept(node)

    def _visit_based_integer(self, node, base, prefix=""):
        value = self.render(node["children"][0]).replace("_", "")
        digits = value.split("#", 1)[-1]
        # C11 has no binary literal syntax, so binary values are emitted as
        # decimal. Octal and hexadecimal literals retain their readable form.
        self.text += str(int(digits, base)) if base == 2 else prefix + digits

    def visit_binary_integer(self, node):
        self._visit_based_integer(node, 2)

    def visit_octal_integer(self, node):
        self._visit_based_integer(node, 8, "0")

    def visit_hex_integer(self, node):
        self._visit_based_integer(node, 16, "0x")

    def visit_boolean_literal(self, node):
        self.text += node["value"].lower()

    def visit_bit_string_literal(self, node):
        for child in node["children"]:
            self.visit(child)

    def visit_signed_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_unsigned_integer_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_real_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_bit_string_type_name(self, node):
        self.text += self.iecType2C(node["value"])

    def visit_variable_name(self, node):
        self.text += node["value"]

    def visit_library(self, node):
        for name, runtime_source in C_RUNTIME_FUNCTIONS.items():
            if self._contains_function(node, {name}):
                self.text += runtime_source + "\n"
        self.accept(node)

    def _contains_function(self, node, names):
        if not isinstance(node, dict):
            return False
        if node.get("name") == "standard_function_name" and node.get("value") in names:
            return True
        return any(self._contains_function(child, names) for child in node.get("children", []))

    def visit_standard_function_name(self, node):
        self.text += node["value"]

    def visit_derived_function_name(self, node):
        self.text += node["value"]

    def visit_primary_expression(self, node):
        children = node.get("children", [])
        if not children or children[0].get("name") != "function_name":
            self.accept(node)
            return

        self.visit(children[0])
        self.text += "("
        arguments = [child for child in children[1:] if child.get("name") == "param_assignment"]
        for index, argument in enumerate(arguments):
            if index:
                self.text += ", "
            expressions = [child for child in argument.get("children", []) if child.get("name") == "expression"]
            if expressions:
                self.visit(expressions[-1])
        self.text += ")"

    def visit_function_declaration(self, node):
        name = node["children"][0]["value"]
        native = self.native_implementations.get(name.casefold())
        return_type = self.extract_type(node["children"][1]) or "void"
        self.current_function = name
        self.current_return_type = return_type

        input_decls = self.collect_sections(node["children"][2], "input_declarations")
        local_decls = self.collect_sections(node["children"][2], "function_var_decls")
        params = [f"{var_type} {var_name}" for var_type, var_name in input_decls]

        self.text += f"{return_type} {name}({', '.join(params)})\n{{\n"
        self.indent_inc()
        if return_type != "void":
            self.text += f"{self.indent}{return_type} {name} = {self.zero_value(return_type)};\n"
        for var_type, var_name in local_decls:
            self.text += f"{self.indent}{var_type} {var_name} = {self.zero_value(var_type)};\n"
        if local_decls or return_type != "void":
            self.text += "\n"
        if native is not None:
            self._emit_native_code(native.section("body") or "")
        else:
            self.accept(node, lambda child_name: child_name == "function_body")
        if return_type != "void":
            self.text += f"{self.indent}return {name};\n"
        self.indent_dec()
        self.text += "}\n"
        self.current_function = None
        self.current_return_type = None

    def visit_function_block_declaration(self, node):
        name_node = self._first_named(node, "derived_function_block_name")
        if name_node is None:
            return
        name = name_node["value"]
        native = self.native_implementations.get(name.casefold())
        if native is None or native.kind != "function_block":
            return

        declarations = []
        for section in ("input_declarations", "output_declarations", "var_declarations", "temp_var_decls"):
            declarations.extend(self.collect_sections(node, section))

        self.text += f"typedef struct {name} {{\n"
        self.indent_inc()
        for var_type, var_name in declarations:
            self.text += f"{self.indent}{var_type} {var_name};\n"
        self.indent_dec()
        self.text += f"}} {name};\n\n"

        self.text += f"void {name}_setup({name} *self)\n{{\n"
        self.indent_inc()
        for var_type, var_name in declarations:
            self.text += f"{self.indent}self->{var_name} = {self.zero_value(var_type)};\n"
        setup = native.section("setup")
        if setup:
            self._emit_native_code(setup)
        self.indent_dec()
        self.text += "}\n\n"

        self.text += f"void {name}_loop({name} *self)\n{{\n"
        self.indent_inc()
        self._emit_native_code(native.section("loop") or "")
        self.indent_dec()
        self.text += "}\n"

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
        self._join_children(node, " || ")

    def visit_xor_expression(self, node):
        self._join_children(node, " ^ ")

    def visit_and_expression(self, node):
        self._join_children(node, " && ")

    def visit_comparison(self, node):
        self._visit_infix(node)

    def visit_comparison_equality_operator(self, node):
        op = {"=": "==", "NEQ": "!=", "<>": "!="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_equ_expression(self, node):
        self._visit_infix(node)

    def visit_add_expression(self, node):
        self._visit_infix(node)

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
                expression = f"pow({self.render(child)}, {expression})"
            self.text += expression

    def visit_unary_expression(self, node):
        op = node.get("value")
        if op == "NOT":
            self.text += "!"
        elif op:
            self.text += op
        self.accept(node)

    def visit_add_operator(self, node):
        self.text += f" {node['value']} "

    def visit_comparison_operator(self, node):
        op = {"LE_EQ": "<=", "GE_EQ": ">="}.get(node["value"], node["value"])
        self.text += f" {op} "

    def visit_assignment_statement(self, node):
        self.text += self.indent
        self.accept(node, lambda name: name == "variable")
        self.text += " = "
        self.accept(node, lambda name: name == "expression")
        self.text += ";\n"

    def visit_if_statement(self, node):
        self.text += self.indent + "if ("
        self.visit(node["children"][0])
        self.text += ") {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"
        self.accept(node, lambda name: name == "elseif_statement_list")
        self.accept(node, lambda name: name == "else_statement")

    def visit_elseif_statement(self, node):
        self.text += self.indent + "else if ("
        self.visit(node["children"][0])
        self.text += ") {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_else_statement(self, node):
        self.text += self.indent + "else {\n"
        self.indent_inc()
        self.accept(node)
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_while_statement(self, node):
        self.text += self.indent + "while ("
        self.visit(node["children"][0])
        self.text += ") {\n"
        self.indent_inc()
        self.visit(node["children"][1])
        self.indent_dec()
        self.text += self.indent + "}\n"

    def visit_repeat_statement(self, node):
        self.text += self.indent + "do {\n"
        self.indent_inc()
        self.visit(node["children"][0])
        self.indent_dec()
        self.text += self.indent + "} while (!("
        self.visit(node["children"][1])
        self.text += "));\n"

    def visit_token(self, node):
        self.text += str(node.get("value", ""))

    def visit_control_variable(self, node):
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
        self.text += self.source_line_directive(node)
        self.text += f"{self.indent}for ({variable} = {start_text}; {variable} {comparator} {end_text}; {step}) {{\n"
        self.indent_inc()
        self.visit(body)
        self.indent_dec()
        self.text += f"{self.indent}}}\n"

    def visit_case_statement(self, node):
        children = node.get("children", [])
        expression = next(child for child in children if child.get("name") == "expression")
        expression_text = self.render(expression)
        self.text += self.source_line_directive(node)
        self.text += f"{self.indent}switch ({expression_text}) {{\n"
        self.indent_inc()
        for child in children:
            if child.get("name") == "case_element":
                self.visit(child)
            elif child.get("name") == "statement_list":
                self.text += f"{self.indent}default:\n"
                self.indent_inc()
                self.visit(child)
                self.text += f"{self.indent}break;\n"
                self.indent_dec()
        self.indent_dec()
        self.text += f"{self.indent}}}\n"

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

    def _join_children(self, node, separator):
        for index, child in enumerate(node["children"]):
            if index:
                self.text += separator
            self.visit(child)

    def _visit_infix(self, node):
        for child in node["children"]:
            self.visit(child)

    def _visit_infix_from_child_value(self, node):
        children = node["children"]
        if not children:
            return
        self.visit(children[0])
        for child in children[1:]:
            op = {"MOD": "%"}.get(child.get("value"), child.get("value"))
            self.text += f" {op} "
            self.visit(child)
