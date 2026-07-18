# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Order registered semantic checks and execute their dependency pipeline."""
from __future__ import annotations

from semantic_context import SemanticContext
from .base import SemanticCheck, registered_checks


class SemanticPipeline:
    def __init__(self, checks: tuple[type[SemanticCheck], ...] | None = None):
        self.checks = checks or self._ordered_registered_checks()

    @staticmethod
    def _ordered_registered_checks() -> tuple[type[SemanticCheck], ...]:
        remaining = {check.metadata.name: check for check in registered_checks()}
        ordered: list[type[SemanticCheck]] = []
        completed: set[str] = set()

        while remaining:
            ready = [
                check
                for check in remaining.values()
                if all(dep in completed for dep in check.metadata.after)
            ]
            if not ready:
                unresolved = ", ".join(sorted(remaining))
                raise ValueError(f"Cyclic or unknown semantic-check dependencies: {unresolved}")

            ready.sort(key=lambda check: (check.metadata.phase, check.metadata.name))
            for check in ready:
                ordered.append(check)
                completed.add(check.metadata.name)
                remaining.pop(check.metadata.name)

        return tuple(ordered)

    def run(self, ast, context: SemanticContext) -> SemanticContext:
        for check_type in self.checks:
            check_type(context).run(ast)
        return context
