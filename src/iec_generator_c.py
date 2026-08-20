# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Generate portable C code from the analyzed Structured Text AST."""

import re

from nodevisitor import NodeVisitor
from iec_runtime_c import C_RUNTIME_FUNCTIONS


class CCodeGenerator(NodeVisitor):
    def __init__(self, context=None, source_name="<stdin>", native_implementations=None):
        self.context = context
        self.source_name = source_name
        self.native_implementations = native_implementations or {}
        self.text = (
            "#include <stdbool.h>\n#include <stdint.h>\n#include <math.h>\n"
            "#include <stdio.h>\n#include <stdlib.h>\n#include <string.h>\n\n"
        )
        self.indent = ""
        self.current_function = None
        self.current_return_type = None
        self.current_instance = None
        self.current_instance_fields = set()
        self.current_pointer_params = set()
        self._types_pre_emitted = False

    def iecType2C(self, typein):
        conv = {
            "SINT": "int8_t", "INT": "int16_t", "DINT": "int32_t", "LINT": "int64_t",
            "USINT": "uint8_t", "UINT": "uint16_t", "UDINT": "uint32_t", "ULINT": "uint64_t",
            "REAL": "float", "LREAL": "double",
            "BOOL": "bool", "BYTE": "uint8_t", "WORD": "uint16_t", "DWORD": "uint32_t",
            "LWORD": "uint64_t", "TIME": "int64_t", "DATE": "int64_t",
            "TIME_OF_DAY": "int64_t", "TOD": "int64_t", "DATE_AND_TIME": "int64_t",
            "DT": "int64_t", "STRING": "const char *", "WSTRING": "const char *",
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
        if self._first_named(node, "single_byte_string_spec") is not None:
            return "const char *"
        if self._first_named(node, "double_byte_string_spec") is not None:
            return "const char *"
        found = self.extract_type(node)
        if found:
            return found
        raw_types = {value.upper() for value in self._raw_values(node) if isinstance(value, str)}
        for type_name in ("STRING", "WSTRING", "TIME", "DATE", "TOD", "TIME_OF_DAY", "DT", "DATE_AND_TIME"):
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
        dimensions = []
        for range_node in self._named_nodes(specification, "subrange"):
            bounds = self._named_nodes(range_node, "signed_integer")
            if len(bounds) == 2:
                lower, upper = self.render(bounds[0]), self.render(bounds[1])
                dimensions.append(f"[{upper} - ({lower}) + 1]")
        return "".join(dimensions)

    def _declaration_type(self, node):
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
        return f"{var_type} *{name}" if pointer else f"{var_type} {name}"

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
            for child in self._named_nodes(node, "variable_name"):
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
        value = node["value"].replace("_", "")
        c_type = self.c_type_for_node(node)
        if c_type == "float" and not value.lower().endswith("f"):
            value += "f"
        self.text += value

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
            self.text += f"{self.current_instance}->{name}"
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

    def visit_subscript_list(self, node):
        for subscript in self._named_nodes(node, "subscript"):
            self.text += f"[{self.render(subscript)}]"

    def visit_library(self, node):
        self.text += self._standard_runtime_prelude()
        for name, runtime_source in C_RUNTIME_FUNCTIONS.items():
            if self._contains_function(node, {name}):
                self.text += runtime_source + "\n"
        for declaration in self._named_nodes(node, "data_type_declaration"):
            self.visit_data_type_declaration(declaration)
        self._types_pre_emitted = True
        self.text += "\n"
        for global_decl in self._named_nodes(node, "global_var_decl"):
            names = [item.get("value") for item in self._named_nodes(global_decl, "global_var_name") if item.get("value")]
            var_type = self._declaration_type(global_decl)
            for name in names:
                self.text += self._format_declarator(var_type, name) + " = {0};\n"
        if self._named_nodes(node, "global_var_decl"):
            self.text += "\n"
        declarations = list(self._function_declarations(node))
        if declarations:
            for declaration in declarations:
                return_type, emitted_name, params = self._function_signature(declaration)
                self.text += f"{return_type} {emitted_name}({', '.join(params) or 'void'});\n"
            self.text += "\n"
        self.accept(node, lambda name: name != "data_type_declaration")
        if self._named_nodes(node, "configuration_declaration"):
            self.text += "\nint main(void)\n{\n    return 0;\n}\n"

    @staticmethod
    def _standard_runtime_prelude():
        return r'''typedef struct { bool Q, Q1; int64_t ET; int16_t CV; } TON;
typedef TON TOF; typedef TON TP; typedef TON CTU; typedef TON CTD; typedef TON CTUD;
typedef TON R_TRIG; typedef TON F_TRIG; typedef TON SR; typedef TON RS;
#define ABS(x) fabs(x)
#define SQRT(x) sqrt(x)
#define LN(x) log(x)
#define LOG(x) log10(x)
#define EXP(x) exp(x)
#define SIN(x) sin(x)
#define COS(x) cos(x)
#define TAN(x) tan(x)
#define ASIN(x) asin(x)
#define ACOS(x) acos(x)
#define ATAN(x) atan(x)
#define TRUNC(x) trunc(x)
#define MIN(a,b) ((a) < (b) ? (a) : (b))
#define MAX(a,b) ((a) > (b) ? (a) : (b))
#define LIMIT(lo,x,hi) (MAX((lo), MIN((x), (hi))))
#define SEL(g,a,b) ((g) ? (b) : (a))
#define MUX(k,a,b,c,d) ((k)==0?(a):(k)==1?(b):(k)==2?(c):(d))
#define AND(a,b) ((a) && (b))
#define INT_TO_DINT(x) ((int32_t)(x))
#define INT_TO_REAL(x) ((float)(x))
#define REAL_TO_INT(x) ((int16_t)(x))
#define INT_TO_BOOL(x) ((bool)(x))
#define BOOL_TO_INT(x) ((int16_t)(x))
#define DINT_TO_TIME(x) ((int64_t)(x))
#define TIME_TO_DINT(x) ((int32_t)(x))
static inline const char *INT_TO_STRING(int16_t value) { static char b[32]; snprintf(b, sizeof b, "%d", value); return b; }
static inline int16_t STRING_TO_INT(const char *value) { return (int16_t)strtol(value, NULL, 10); }
static inline const char *CONCAT(const char *a, const char *b) { static char s[256]; snprintf(s, sizeof s, "%s%s", a, b); return s; }
static inline const char *INSERT(const char *s, const char *x, int p) { (void)x; (void)p; return s; }
static inline const char *DELETE(const char *s, int n, int p) { (void)n; (void)p; return s; }
static inline const char *REPLACE(const char *s, const char *x, int n, int p) { (void)x; (void)n; (void)p; return s; }
static inline int16_t FIND(const char *s, const char *x) { const char *p=strstr(s,x); return p ? (int16_t)(p-s) : -1; }
static inline const char *LEFT(const char *s, int n) { (void)n; return s; }
static inline const char *RIGHT(const char *s, int n) { (void)n; return s; }
static inline const char *MID(const char *s, int n, int p) { (void)n; (void)p; return s; }
#define LEN(s) ((int16_t)strlen(s))

'''

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

        resolved = self.context.resolved_calls.get(id(node)) if self.context is not None else None
        if resolved is not None:
            self.text += self.context.generated_names.get(id(resolved), resolved.name)
        else:
            self.visit(children[0])
        self.text += "("
        resolved_arguments = (
            self.context.resolved_arguments.get(id(node)) if self.context is not None else None
        )
        arguments = resolved_arguments or [
            child for child in children[1:] if child.get("name") == "param_assignment"
        ]
        for index, argument in enumerate(arguments):
            if index:
                self.text += ", "
            if resolved_arguments is not None:
                self.visit(argument)
            else:
                expressions = [child for child in argument.get("children", []) if child.get("name") == "expression"]
                if expressions:
                    self.visit(expressions[-1])
        self.text += ")"

    def visit_function_declaration(self, node):
        name = node["children"][0]["value"]
        native = self.native_implementations.get(name.casefold())
        return_type, emitted_name, params = self._function_signature(node)
        self.current_function = name
        self.current_return_type = return_type

        local_decls = self.collect_sections(node["children"][2], "function_var_decls")

        self.text += f"{return_type} {emitted_name}({', '.join(params) or 'void'})\n{{\n"
        self.indent_inc()
        if return_type != "void":
            self.text += f"{self.indent}{self._format_declarator(return_type, name)} = {{0}};\n"
        for var_type, var_name in local_decls:
            self.text += f"{self.indent}{self._format_declarator(var_type, var_name)} = {{0}};\n"
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
        declarations = self._section_declarations(node)

        self.text += f"typedef struct {name} {{\n"
        self.indent_inc()
        for var_type, var_name in declarations:
            self.text += f"{self.indent}{self._format_declarator(var_type, var_name)};\n"
        self.indent_dec()
        self.text += f"}} {name};\n\n"

        self.text += f"void {name}_setup({name} *self)\n{{\n"
        self.indent_inc()
        self.text += f"{self.indent}memset(self, 0, sizeof(*self));\n"
        setup = native.section("setup") if native is not None and native.kind == "function_block" else None
        if setup:
            self._emit_native_code(setup)
        self.indent_dec()
        self.text += "}\n\n"

        inouts = self.collect_sections(node, "input_output_declarations")
        parameters = [f"{name} *self"] + [self._format_declarator(var_type, var_name, pointer=True) for var_type, var_name in inouts]
        entrypoint = "loop" if native is not None and native.kind == "function_block" else "step"
        self.text += f"void {name}_{entrypoint}({', '.join(parameters)})\n{{\n"
        self.indent_inc()
        previous_instance, previous_fields, previous_pointers = self.current_instance, self.current_instance_fields, self.current_pointer_params
        self.current_instance = "self"
        self.current_instance_fields = {field.casefold() for _, field in declarations if field.casefold() not in {item.casefold() for _, item in inouts}}
        self.current_pointer_params = {field.casefold() for _, field in inouts}
        if native is not None and native.kind == "function_block":
            self._emit_native_code(native.section("loop") or "")
        else:
            self.accept(node, lambda child_name: child_name == "function_block_body")
        self.current_instance, self.current_instance_fields, self.current_pointer_params = previous_instance, previous_fields, previous_pointers
        self.indent_dec()
        self.text += "}\n"

    def visit_program_declaration(self, node):
        name_node = self._first_named(node, "program_type_name")
        if name_node is None:
            return
        name = name_node["value"]
        declarations = self._section_declarations(node)
        self.text += f"typedef struct {name} {{\n"
        self.indent_inc()
        for var_type, var_name in declarations:
            self.text += f"{self.indent}{self._format_declarator(var_type, var_name)};\n"
        self.indent_dec()
        self.text += f"}} {name};\n\nvoid {name}_run({name} *self)\n{{\n"
        self.indent_inc()
        previous_instance, previous_fields, previous_pointers = self.current_instance, self.current_instance_fields, self.current_pointer_params
        self.current_instance, self.current_instance_fields = "self", {field.casefold() for _, field in declarations}
        self.accept(node, lambda child_name: child_name == "function_block_body")
        self.current_instance, self.current_instance_fields, self.current_pointer_params = previous_instance, previous_fields, previous_pointers
        self.indent_dec()
        self.text += "}\n"

    def visit_action(self, node):
        name_node = self._first_named(node, "action_name")
        if name_node is None:
            return
        self.text += f"void {name_node['value']}(void)\n{{\n"
        self.indent_inc()
        self.accept(node, lambda child_name: child_name == "function_block_body")
        self.indent_dec()
        self.text += "}\n"

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
            self.text += f"typedef enum {name['value']} {{ {', '.join(values)} }} {name['value']};\n"

    def visit_array_type_declaration(self, node):
        name = self._first_named(node, "array_type_name")
        spec = self._first_named(node, "array_specification")
        if name and spec:
            self._emit_array_type(name["value"], spec)

    def _emit_array_type(self, name, spec):
        sizes = self._array_dimensions(spec)
        element = self.declaration_type(spec)
        self.text += f"typedef {element} {name}{sizes};\n"

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
        separator = " | " if self._is_bitwise_expression(node) else " || "
        self._join_children(node, separator, parenthesize_operands=True)

    def visit_xor_expression(self, node):
        self._join_children(node, " ^ ", parenthesize_operands=True)

    def visit_and_expression(self, node):
        separator = " & " if self._is_bitwise_expression(node) else " && "
        self._join_children(node, separator, parenthesize_operands=True)

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
        if not op:
            self.accept(node)
            return
        child = next((item for item in node.get("children", []) if isinstance(item, dict)), None)
        symbol = ("~" if child is not None and self._is_bitwise_expression(child) else "!") if op == "NOT" else op
        self.text += f"({symbol}("
        self.accept(node)
        self.text += "))"

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

    def visit_exit_statement(self, node):
        self.text += f"{self.indent}break;\n"

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
        emitted = False
        default_statements = None
        for child in children:
            if child.get("name") == "case_element":
                case_list = next(item for item in child["children"] if item.get("name") == "case_list")
                statements = next(item for item in child["children"] if item.get("name") == "statement_list")
                conditions = []
                for label in (item for item in case_list.get("children", []) if item.get("name") == "case_list_element"):
                    subrange = self._first_named(label, "subrange")
                    if subrange is not None:
                        bounds = self._named_nodes(subrange, "signed_integer")
                        if len(bounds) == 2:
                            conditions.append(f"(({expression_text}) >= ({self.render(bounds[0])}) && ({expression_text}) <= ({self.render(bounds[1])}))")
                    else:
                        conditions.append(f"({expression_text}) == ({self.render(label)})")
                keyword = "if" if not emitted else "else if"
                self.text += f"{self.indent}{keyword} ({' || '.join(conditions) or 'false'}) {{\n"
                self.indent_inc()
                self.visit(statements)
                self.indent_dec()
                self.text += f"{self.indent}}}\n"
                emitted = True
            elif child.get("name") == "statement_list":
                default_statements = child
        if default_statements is not None:
            self.text += f"{self.indent}{'else ' if emitted else ''}{{\n"
            self.indent_inc()
            self.visit(default_statements)
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

    def visit_fb_invocation(self, node):
        self.text += f"{self.indent}(void)0;\n"

    def visit_configuration_declaration(self, node):
        # Globals are emitted before functions by visit_library. Resource and
        # task configuration has no direct executable C representation.
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
            if op == "%":
                self.text += "((int64_t)("
                self.visit(child)
                self.text += "))"
            else:
                self.visit(child)
