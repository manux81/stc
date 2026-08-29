# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Small, backend-neutral helpers for lowering textual SFC bodies."""

from __future__ import annotations


TIMED_QUALIFIERS = frozenset({"L", "D", "SD", "DS", "SL"})
ACTION_QUALIFIERS = frozenset({"N", "R", "S", "P", "P0", "P1", *TIMED_QUALIFIERS})


def named(node, name):
    if not isinstance(node, dict):
        return []
    result = [node] if node.get("name") == name else []
    for child in node.get("children", []):
        result.extend(named(child, name))
    return result


def first(node, name):
    items = named(node, name)
    return items[0] if items else None


def direct(node, name):
    return [
        child for child in node.get("children", [])
        if isinstance(child, dict) and child.get("name") == name
    ]


def value(node, name, default=""):
    item = first(node, name)
    return str(item.get("value", default)) if item is not None else default


def field(name, suffix):
    return f"__sfc_{str(name).casefold()}_{suffix}"


def chart_model(chart):
    """Return a convenient model while retaining original expression nodes."""
    steps = []
    transitions = []
    actions = {}
    action_nodes = []
    for network_index, network in enumerate(named(chart, "sfc_network")):
        elements = direct(network, "initial_step")
        elements += [
            item
            for wrapper in direct(network, "sfc_element")
            for item in wrapper.get("children", [])
            if isinstance(item, dict)
        ]
        for step_node in [item for item in elements if item.get("name") in {"initial_step", "step"}]:
            step_name = value(step_node, "step_name")
            associations = []
            for association in direct(step_node, "action_association"):
                qualifier = value(association, "action_qualifier", "N").upper()
                arguments = direct(association, "action_argument")
                time = arguments[0] if qualifier in TIMED_QUALIFIERS and arguments else None
                indicators = arguments[1:] if time is not None else arguments
                associations.append({
                    "node": association,
                    "name": value(association, "action_name"),
                    "qualifier": qualifier,
                    "time": time,
                    "indicators": indicators,
                })
            steps.append({
                "node": step_node,
                "name": step_name,
                "initial": step_node.get("name") == "initial_step",
                "network": network_index,
                "associations": associations,
            })
        for transition in [item for item in elements if item.get("name") == "transition"]:
            endpoints = direct(transition, "steps")
            sources = [value(item, "step_name") for item in named(endpoints[0], "step_name")] if endpoints else []
            targets = [value(item, "step_name") for item in named(endpoints[1], "step_name")] if len(endpoints) > 1 else []
            condition = first(first(transition, "transition_condition"), "expression")
            priority_node = first(transition, "integer")
            priority = int(str(priority_node.get("value", "0")).replace("_", "")) if priority_node else 0
            transitions.append({
                "node": transition,
                "name": value(transition, "transition_name"),
                "sources": sources,
                "targets": targets,
                "condition": condition,
                "priority": priority,
            })
        for action in [item for item in elements if item.get("name") == "action"]:
            action_nodes.append(action)
            actions[value(action, "action_name").casefold()] = action
    return {
        "node": chart,
        "steps": steps,
        "transitions": transitions,
        "actions": actions,
        "action_nodes": action_nodes,
    }


def charts(node):
    chart_nodes = (
        [node]
        if isinstance(node, dict) and node.get("name") == "sequential_function_chart"
        else named(node, "sequential_function_chart")
    )
    return [chart_model(chart) for chart in chart_nodes]


def state_declarations(node, bool_type, time_type):
    result = []
    for chart in charts(node):
        for step in chart["steps"]:
            result.extend([
                (bool_type, field(step["name"], "active")),
                (bool_type, field(step["name"], "previous")),
                (time_type, field(step["name"], "elapsed_ms")),
            ])
        for action_name in chart["actions"]:
            result.append((bool_type, field(f"action_{action_name}", "stored")))
    return result
