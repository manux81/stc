# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify semantic-check registration and dependency ordering."""

from semantic_checks import SemanticCheck, SemanticPhase, SemanticPipeline, register_check
from semantic_context import SemanticContext
from symbol_table import SymbolTableBuilder


def test_registered_pipeline_has_stable_dependency_order():
    names = [check.metadata.name for check in SemanticPipeline().checks]
    assert names.index("collect-types") < names.index("fill-candidate-types")
    assert names.index("fill-candidate-types") < names.index("narrow-candidate-types")
    assert names.index("narrow-candidate-types") < names.index("type-errors")
    assert names.index("type-errors") < names.index("force-types")


def test_custom_pipeline_accepts_an_independent_check():
    class DemoCheck(SemanticCheck):
        def run(self, ast):
            self.error("demo", "Demo diagnostic.", ast)
            return self.context

    DemoCheck.metadata = type("Metadata", (), {
        "name": "demo",
        "phase": SemanticPhase.VALIDATION,
        "after": (),
    })()

    ast = {"name": "library", "children": []}
    context = SemanticContext(SymbolTableBuilder().build(ast))
    SemanticPipeline(checks=(DemoCheck,)).run(ast, context)
    assert [item.code for item in context.diagnostics] == ["demo"]
