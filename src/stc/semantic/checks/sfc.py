# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Structural and profile-independent validation for textual SFC."""

from ...codegen.sfc import ACTION_QUALIFIERS, TIMED_QUALIFIERS, charts
from ..symbol_table import normalize_identifier
from .base import SemanticCheck, SemanticPhase, register_check


@register_check(
    name="sfc-validation",
    phase=SemanticPhase.VALIDATION,
    after=("edition-compatibility",),
    description="Validate SFC steps, transitions, actions, and qualifiers.",
)
class SequentialFunctionChartCheck(SemanticCheck):
    """Reject malformed charts before either target attempts to lower them."""

    def visit_sequential_function_chart(self, node):
        for chart in charts(node):
            step_names = {}
            action_definitions = set(chart["actions"])
            seen_actions = set()
            for action in chart["action_nodes"]:
                name_node = next(
                    (item for item in action.get("children", []) if item.get("name") == "action_name"),
                    None,
                )
                action_name = str(name_node.get("value", "")) if name_node else ""
                action_key = normalize_identifier(action_name)
                if action_key in seen_actions:
                    self.error(
                        "duplicate-sfc-action",
                        f"SFC ACTION {action_name!r} is declared more than once.",
                        action,
                    )
                seen_actions.add(action_key)
            for step in chart["steps"]:
                key = normalize_identifier(step["name"])
                if key in step_names:
                    self.error(
                        "duplicate-sfc-step",
                        f"SFC step {step['name']!r} is declared more than once in this POU.",
                        step["node"],
                    )
                else:
                    step_names[key] = step

                for association in step["associations"]:
                    qualifier = association["qualifier"]
                    if qualifier not in ACTION_QUALIFIERS:
                        self.error(
                            "invalid-sfc-action-qualifier",
                            f"Unknown SFC action qualifier {qualifier!r}.",
                            association["node"],
                        )
                    elif qualifier in TIMED_QUALIFIERS and association["time"] is None:
                        self.error(
                            "missing-sfc-action-time",
                            f"SFC action qualifier {qualifier} requires a time argument.",
                            association["node"],
                        )
                    action_key = normalize_identifier(association["name"])
                    scope = self.context.symbols.scope_for(association["node"])
                    if action_key not in action_definitions and (
                        scope is None or scope.lookup(association["name"]) is None
                    ):
                        self.error(
                            "unknown-sfc-action",
                            f"SFC action {association['name']!r} is neither an ACTION nor a declared variable.",
                            association["node"],
                        )
                    for indicator in association["indicators"]:
                        indicator_node = next(
                            (item for item in indicator.get("children", []) if item.get("name") == "variable_name"),
                            None,
                        )
                        if indicator_node is not None and (
                            scope is None or scope.lookup(str(indicator_node.get("value", ""))) is None
                        ):
                            self.error(
                                "unknown-sfc-indicator",
                                f"Unknown SFC indicator variable {indicator_node.get('value')!r}.",
                                indicator_node,
                            )

            transition_names = set()
            for transition in chart["transitions"]:
                if transition["name"]:
                    key = normalize_identifier(transition["name"])
                    if key in transition_names:
                        self.error(
                            "duplicate-sfc-transition",
                            f"SFC transition {transition['name']!r} is declared more than once.",
                            transition["node"],
                        )
                    transition_names.add(key)
                for endpoint in transition["sources"] + transition["targets"]:
                    if normalize_identifier(endpoint) not in step_names:
                        self.error(
                            "unknown-sfc-step",
                            f"Transition refers to unknown SFC step {endpoint!r}.",
                            transition["node"],
                        )
                if transition["condition"] is None:
                    self.error(
                        "unsupported-sfc-transition-condition",
                        "Only Structured Text expressions are currently executable as SFC transition conditions.",
                        transition["node"],
                    )

        self.generic_visit(node)
