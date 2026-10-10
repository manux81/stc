"""The self-documenting API exposed to external ``.gen`` backends."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleSpec:
    name: str
    description: str
    values: tuple[str, ...]
    category: str
    required: bool = False
    required_values: tuple[str, ...] = ()
    mapping: bool = False
    phase: int = 1


def _rule(name, description, values, category, *, required=False, required_values=(), mapping=False, phase=1):
    return RuleSpec(name, description, tuple(values), category, required, tuple(required_values), mapping, phase)


# This is executable schema, not separately maintained prose: help, validation
# and scaffolding all derive from it.
_RULES = (
    _rule("type", "Map a resolved IEC type name to a target type.", ("name",), "types", required=True, mapping=True),
    _rule("integer_literal", "Render a normalized integer literal.", ("value", "type_name"), "literals", required=True, required_values=("value",)),
    _rule("real_literal", "Render a normalized real literal.", ("value", "type_name", "suffix"), "literals", required=True, required_values=("value",)),
    _rule("boolean_literal", "Map an IEC boolean literal to its target spelling.", ("value",), "literals", required=True, mapping=True),
    _rule("based_literal", "Render a normalized based integer literal.", ("value", "base", "prefix"), "literals", required=True, required_values=("value",)),
    _rule("based_prefix", "Map an IEC base to its target literal prefix.", ("value",), "literals", required=True, mapping=True),
    _rule("binary_expression", "Render an already typed binary expression.", ("left", "operator", "right"), "expressions", required=True, required_values=("left", "operator", "right")),
    _rule("power_expression", "Render a right-associative exponentiation.", ("left", "right"), "expressions", required=True, required_values=("left", "right")),
    _rule("unary_expression", "Render an already typed unary expression.", ("operator", "operand"), "expressions", required=True, required_values=("operator", "operand")),
    _rule("operator", "Map a resolved IEC operator to target syntax.", ("value",), "expressions", required=True, mapping=True),
    _rule("assignment", "Assign a lowered value to a lowered target.", ("target", "value", "indent"), "assignments", required=True, required_values=("target", "value")),
    _rule("if", "Render an IF branch.", ("condition", "body", "indent"), "control flow", required=True, required_values=("condition", "body")),
    _rule("elseif", "Render an ELSE IF branch.", ("condition", "body", "indent"), "control flow", required=True, required_values=("condition", "body")),
    _rule("else", "Render an ELSE branch.", ("body", "indent"), "control flow", required=True, required_values=("body",)),
    _rule("while", "Render a WHILE loop.", ("condition", "body", "indent"), "control flow", required=True, required_values=("condition", "body")),
    _rule("repeat", "Render a REPEAT/UNTIL loop.", ("condition", "body", "indent"), "control flow", required=True, required_values=("condition", "body")),
    _rule("exit", "Exit the nearest loop.", ("indent",), "control flow", required=True),
    _rule("continue", "Continue the nearest loop.", ("indent",), "control flow", required=True),
    _rule("return", "Return from the current POU.", ("value", "has_value", "indent"), "control flow", required=True),
    _rule("cast", "Render a semantically selected conversion.", ("source_type", "target_type", "value"), "conversions", required=True, required_values=("target_type", "value"), phase=2),
    _rule("call", "Render a resolved direct call.", ("name", "arguments"), "calls", required=True, required_values=("name", "arguments"), phase=2),
    _rule("parameter", "Render a list of resolved call parameters.", ("items", "name", "value", "mode", "type"), "calls", required=True, phase=2),
    _rule("array_type", "Render a named target array type.", ("name", "element_type", "dimensions"), "arrays", required=True, required_values=("name", "dimensions"), phase=2),
    _rule("array_dimension", "Render one array dimension around or after an element type.", ("value", "size", "lower", "upper"), "arrays", required=True, required_values=("value", "size"), phase=2),
    _rule("array_access", "Render a lowered array access.", ("array", "indices"), "arrays", required=True, required_values=("array", "indices"), phase=2),
    _rule("array_index", "Render a list of zero-based array indices.", ("items", "value"), "arrays", required=True, phase=2),
    _rule("reference_type", "Render a named target reference type.", ("name", "referenced_type"), "references", required=True, required_values=("name", "referenced_type"), phase=2),
    _rule("reference", "Create a reference to a lowered lvalue.", ("value",), "references", required=True, required_values=("value",), phase=2),
    _rule("null_reference", "Render the null reference value.", (), "references", required=True, phase=2),
    _rule("dereference", "Dereference a lowered reference.", ("value",), "references", required=True, required_values=("value",), phase=2),
    _rule("for", "Render a normalized FOR loop.", ("variable", "start", "end", "step", "direction", "comparator", "update", "body", "indent"), "control flow", required=True, required_values=("variable", "start", "end", "update", "body"), phase=2),
    _rule("case", "Render a CASE selection.", ("selector", "elements", "else_body", "indent"), "control flow", required=True, required_values=("elements",), phase=2),
    _rule("case_element_first", "Render the first CASE element.", ("labels", "body", "indent"), "control flow", required=True, required_values=("labels", "body"), phase=2),
    _rule("case_element", "Render a subsequent CASE element.", ("labels", "body", "indent"), "control flow", required=True, required_values=("labels", "body"), phase=2),
    _rule("case_value", "Render one scalar CASE label.", ("selector", "value"), "control flow", required=True, required_values=("value",), phase=2),
    _rule("case_range", "Render one CASE range label.", ("selector", "lower", "upper"), "control flow", required=True, required_values=("lower", "upper"), phase=2),
    _rule("case_labels", "Join already lowered CASE labels.", ("items", "value"), "control flow", required=True, phase=2),
    _rule("case_else", "Render a CASE default branch.", ("body", "indent", "has_elements"), "control flow", required=True, required_values=("body",), phase=2),
    _rule("case_else_first", "Render a CASE default when no elements precede it.", ("body", "indent"), "control flow", required=True, required_values=("body",), phase=2),
    _rule("function", "Generate a target-language IEC FUNCTION.", ("name", "emitted_name", "comment", "attributes", "return_type", "parameters", "locals", "body", "return_value"), "functions", required=True, required_values=("emitted_name", "return_type", "parameters", "body"), phase=2),
    _rule("function_block", "Generate an IEC FUNCTION_BLOCK representation.", ("name", "fields", "defaults", "properties", "setup", "cold_init", "warm_init", "parameters", "entrypoint", "temporaries", "body"), "function blocks", required=True, required_values=("name", "fields", "body"), phase=2),
    _rule("program", "Generate an IEC PROGRAM representation.", ("name", "fields", "defaults", "properties", "setup", "cold_init", "warm_init", "parameters", "entrypoint", "temporaries", "body"), "programs", required=True, required_values=("name", "fields", "body"), phase=2),
    _rule("property_get", "Render a resolved property getter call.", ("receiver", "method", "owner", "arguments", "extra_arguments", "base_path"), "properties", required=True, required_values=("receiver", "method"), phase=3),
    _rule("property_get_class", "Render a class property getter call.", ("receiver", "method", "owner", "arguments", "extra_arguments", "base_path"), "properties", required=True, required_values=("receiver", "method"), phase=3),
    _rule("property_get_interface", "Render an interface property getter call.", ("receiver", "method", "owner", "arguments", "extra_arguments", "base_path"), "properties", required=True, required_values=("receiver", "method"), phase=3),
    _rule("property_set", "Render a resolved property setter call.", ("receiver", "method", "owner", "value", "indent", "base_path"), "properties", required=True, required_values=("receiver", "method", "value"), phase=3),
    _rule("property_set_class", "Render a class property setter call.", ("receiver", "method", "owner", "value", "indent", "base_path"), "properties", required=True, required_values=("receiver", "method", "value"), phase=3),
    _rule("property_set_interface", "Render an interface property setter call.", ("receiver", "method", "value", "indent", "base_path"), "properties", required=True, required_values=("receiver", "method", "value"), phase=3),
    _rule("interface_assignment", "Render a resolved class-to-interface assignment.", ("target", "source", "class", "interface", "indent"), "OOP", required=True, required_values=("target", "source"), phase=3),
    _rule("class", "Render a lowered class layout.", ("name", "base", "has_base", "no_base", "has_fields", "no_fields", "fields", "base_field", "vptr_field", "empty_field", "prototypes", "vtable", "dispatch", "adapters", "init", "methods", "interfaces"), "OOP", required=True, required_values=("name", "fields", "methods"), phase=3),
    _rule("class_field", "Render one lowered class field.", ("type", "name"), "OOP", required=True, required_values=("type", "name"), phase=3),
    _rule("class_fields", "Render a list of lowered class fields.", ("items", "type", "name"), "OOP", required=True, phase=3),
    _rule("class_prototype", "Render one class method forward declaration.", ("class", "name", "return_type", "parameters"), "OOP", required=True, phase=3),
    _rule("vtable_entry", "Render one vtable slot declaration.", ("return_type", "name", "parameters"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("dispatch_entry", "Render one dispatch-table initializer entry.", ("name", "implementation", "is_null"), "OOP", required=True, required_values=("name", "implementation"), phase=3),
    _rule("dispatch_entry_null", "Render one null dispatch-table entry.", ("name",), "OOP", required=True, required_values=("name",), phase=3),
    _rule("class_method", "Render one lowered class method implementation.", ("class", "name", "return_type", "receiver", "parameters", "locals", "body", "has_return", "return_stmt"), "OOP", required=True, required_values=("name", "body"), phase=3),
    _rule("method_parameter", "Render one lowered by-value method parameter.", ("type", "name", "mode"), "OOP", required=True, required_values=("type", "name"), phase=3),
    _rule("method_parameter_out", "Render one lowered by-reference method parameter.", ("type", "name", "mode"), "OOP", required=True, required_values=("type", "name"), phase=3),
    _rule("method_receiver", "Render the target method receiver parameter.", (), "OOP", required=True, phase=3),
    _rule("method_parameters", "Join already lowered method parameters.", ("items", "value", "type", "name", "mode"), "OOP", required=True, phase=3),
    _rule("interface", "Render a lowered interface layout.", ("name", "bases", "methods", "defaults", "impls"), "OOP", required=True, required_values=("name", "methods"), phase=3),
    _rule("interface_default", "Render one interface default dispatch entry.", ("interface", "name", "parameters"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("interface_impl", "Render one interface dispatch wrapper.", ("name", "return_type", "parameters", "arguments"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("interface_method", "Render one lowered interface method slot.", ("name", "return_type", "parameters"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("interface_adapter", "Render one class-to-interface adapter.", ("class", "interface", "methods"), "OOP", required=True, required_values=("class", "interface"), phase=3),
    _rule("adapter_entry", "Render one adapter dispatch entry.", ("class", "interface", "name", "implementation", "parameters", "arguments", "return_type"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("adapter_entry_null", "Render one null adapter dispatch entry.", ("name",), "OOP", required=True, required_values=("name",), phase=3),
    _rule("class_predecl", "Render one class/interface forward declaration.", ("name", "kind"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("class_base_field", "Render the embedded base-class field.", ("base", "has_base"), "OOP", required=True, required_values=("base",), phase=3),
    _rule("class_vptr_field", "Render the root-class dispatch pointer field.", ("no_base",), "OOP", required=True, phase=3),
    _rule("class_empty_field", "Render the empty-structure placeholder field.", ("empty",), "OOP", required=True, phase=3),
    _rule("class_init", "Render one class initializer.", ("name", "base", "has_base", "vptr", "base_init", "statements", "defaults"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("class_init_statement", "Render one class initializer statement.", ("address", "type", "field", "nested", "indent", "class"), "OOP", required=True, required_values=("indent",), phase=3),
    _rule("class_base_init", "Render the base-class initializer call.", ("base",), "OOP", required=True, required_values=("base",), phase=3),
    _rule("class_default", "Render one default field initializer.", ("field", "value"), "OOP", required=True, required_values=("field", "value"), phase=3),
    _rule("empty_dispatch", "Render the empty dispatch-table placeholder.", (), "OOP", required=True, phase=3),
    _rule("property_method", "Render one property accessor implementation.", ("owner", "name", "return_type", "parameters", "locals", "body", "return_stmt"), "OOP", required=True, required_values=("name", "body"), phase=3),
    _rule("method_return", "Render one method return statement.", ("name", "indent"), "OOP", required=True, required_values=("name",), phase=3),
    _rule("virtual_call", "Render a resolved virtual call.", ("receiver", "method", "static_type", "vptr", "arguments", "extra_arguments"), "OOP", required=True, required_values=("receiver", "method"), phase=3),
    _rule("virtual_call_this", "Render a virtual call on the current instance.", ("receiver", "method", "static_type", "vptr", "arguments", "extra_arguments"), "OOP", required=True, required_values=("method",), phase=3),
    _rule("virtual_call_super", "Render a virtual call on the base instance.", ("receiver", "method", "static_type", "vptr", "arguments", "extra_arguments"), "OOP", required=True, required_values=("method",), phase=3),
    _rule("virtual_call_interface", "Render a virtual call through an interface.", ("receiver", "method", "static_type", "vptr", "arguments", "extra_arguments"), "OOP", required=True, required_values=("receiver", "method"), phase=3),
    _rule("sfc_chart", "Render one lowered deterministic SFC scan.", ("body", "indent", "steps", "transitions", "actions"), "SFC", required=True, required_values=("body",), phase=4),
    _rule("sfc_transition", "Render one resolved SFC transition.", ("fire", "sources", "targets", "condition", "priority", "decl", "body", "indent"), "SFC", required=True, required_values=("fire",), phase=4),
    _rule("sfc_fire", "Render one SFC transition fire computation.", ("fire", "sources", "condition", "gate", "indent"), "SFC", required=True, required_values=("fire", "condition"), phase=4),
    _rule("sfc_step_assign", "Assign one SFC step state flag.", ("step", "value", "indent"), "SFC", required=True, required_values=("step", "value"), phase=4),
    _rule("sfc_elapsed", "Update one SFC step elapsed timer.", ("step", "active", "previous", "elapsed", "indent"), "SFC", required=True, required_values=("active", "previous", "elapsed"), phase=4),
    _rule("sfc_action", "Guard one SFC action body by its activation condition.", ("condition", "body", "indent"), "SFC", required=True, required_values=("body",), phase=4),
    _rule("sfc_assign", "Drive one SFC variable output.", ("target", "condition", "indent"), "SFC", required=True, required_values=("target", "condition"), phase=4),
    _rule("sfc_set", "Set or reset one latched SFC output.", ("target", "condition", "value", "indent"), "SFC", required=True, required_values=("target", "condition", "value"), phase=4),
    _rule("sfc_stored", "Latch or clear one stored SFC action.", ("action", "condition", "value", "indent"), "SFC", required=True, required_values=("action", "condition", "value"), phase=4),
    _rule("sfc_previous", "Copy one SFC step flag to its previous image.", ("step", "active", "previous", "indent"), "SFC", required=True, required_values=("active", "previous"), phase=4),
    _rule("sfc_state", "Render one persistent SFC state field.", ("type", "name"), "SFC", required=True, required_values=("type", "name"), phase=4),
    _rule("sfc_action_decl", "Render one SFC action declaration.", ("name", "body"), "SFC", required=True, required_values=("name", "body"), phase=4),
    _rule("sfc_flag", "Render one SFC state flag access.", ("field",), "SFC", required=True, required_values=("field",), phase=4),
    _rule("il_dispatch", "Render a lowered IL control-flow program.", ("instructions", "labels", "indent", "acc"), "IL", required=True, required_values=("instructions",), phase=4),
    _rule("il_instruction", "Render one lowered IL instruction with its label.", ("index", "label", "has_label", "body", "indent"), "IL", required=True, required_values=("body",), phase=4),
    _rule("il_label", "Render one IL label definition.", ("name", "indent"), "IL", required=True, required_values=("name",), phase=4),
    _rule("il_assign", "Render one IL accumulator store.", ("target", "value", "indent"), "IL", required=True, required_values=("target", "value"), phase=4),
    _rule("il_jump", "Render a resolved IL jump.", ("target_label", "target_index", "condition", "has_condition", "indent"), "IL", required=True, required_values=("target_label", "target_index"), phase=4),
    _rule("il_return", "Render one IL return.", ("value", "has_value", "condition", "has_condition", "indent"), "IL", required=True, phase=4),
    _rule("il_call", "Render one IL function invocation.", ("name", "arguments"), "IL", required=True, required_values=("name",), phase=4),
    _rule("il_guarded", "Guard one IL statement by the accumulator.", ("condition", "body", "indent"), "IL", required=True, required_values=("condition", "body"), phase=4),
    _rule("il_next", "Advance to the next IL instruction.", ("index", "indent"), "IL", required=True, phase=4),
    _rule("runtime_primitive", "Render a selected runtime primitive.", ("name", "dependencies", "declaration", "implementation"), "runtime", required=True, required_values=("implementation",), phase=4),
    _rule("preamble", "Render the target file header.", ("source", "edition"), "module", required=True, required_values=("source",), phase=4),
    _rule("global_variable", "Render one configuration global variable.", ("name", "type", "value", "is_constant"), "module", required=True, required_values=("name", "type"), phase=4),
    _rule("global_constant", "Render one constant configuration global variable.", ("name", "type", "value"), "module", required=True, required_values=("name", "type"), phase=4),
    _rule("configuration", "Render one IEC configuration scheduler.", ("name", "body", "declarations"), "module", required=True, required_values=("name", "body"), phase=4),
)

GENERATOR_API = {rule.name: rule for rule in _RULES}


def generator_help(section: str | None = None, descriptions: dict[str, str] | None = None) -> str:
    rules = [GENERATOR_API[section]] if section else list(_RULES)
    lines: list[str] = []
    for rule in rules:
        lines.append(rule.name)
        lines.append("")
        lines.append((descriptions or {}).get(rule.name, rule.description))
        lines.append("")
        lines.append("Available values:")
        lines.extend(f"    {{{value}}}" for value in rule.values)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
