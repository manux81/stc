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
    _rule("based_literal", "Render a normalized based integer literal.", ("value", "base", "prefix"), "literals"),
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
    _rule("property_get", "Render a resolved property getter call.", ("receiver", "method", "arguments"), "properties"),
    _rule("property_set", "Render a resolved property setter call.", ("receiver", "method", "value", "indent"), "properties"),
    _rule("class", "Render a lowered class layout.", ("name", "base", "fields", "methods", "interfaces"), "OOP"),
    _rule("interface", "Render a lowered interface layout.", ("name", "bases", "methods"), "OOP"),
    _rule("virtual_call", "Render a resolved virtual call.", ("receiver", "method", "static_type", "arguments"), "OOP"),
    _rule("sfc_chart", "Render one lowered deterministic SFC scan.", ("steps", "transitions", "actions"), "SFC"),
    _rule("sfc_transition", "Render one resolved SFC transition.", ("sources", "targets", "condition", "priority"), "SFC"),
    _rule("il_dispatch", "Render a lowered IL control-flow program.", ("instructions", "labels"), "IL"),
    _rule("il_jump", "Render a resolved IL jump.", ("target_label", "target_index", "condition"), "IL"),
    _rule("runtime_primitive", "Render a selected runtime primitive.", ("name", "dependencies", "declaration", "implementation"), "runtime"),
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
