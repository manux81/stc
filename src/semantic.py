# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Build semantic context and execute the registered analysis pipeline."""
from semantic_checks import SemanticPipeline
from semantic_context import SemanticContext
from symbol_table import SymbolTableBuilder


class SemanticError(Exception):
    def __init__(self, diagnostics, source_map=None, context=None):
        self.diagnostics = diagnostics
        self.source_map = source_map
        self.context = context
        super().__init__("\n".join(diagnostic.message for diagnostic in diagnostics))


class SemanticAnalyzer:
    """Build the symbol table and execute the registered semantic checks."""

    def __init__(self, pipeline: SemanticPipeline | None = None):
        self.pipeline = pipeline or SemanticPipeline()

    def analyze(self, ast, source_map=None) -> SemanticContext:
        context = SemanticContext(
            symbols=SymbolTableBuilder().build(ast),
            source_map=source_map,
        )
        self.pipeline.run(ast, context)
        errors = [item for item in context.diagnostics if item.severity == "error"]
        if errors:
            raise SemanticError(
                context.diagnostics,
                source_map=context.source_map,
                context=context,
            )
        return context
