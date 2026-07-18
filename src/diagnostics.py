# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Render compiler diagnostics with Clang-style source locations."""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from semantic_context import Diagnostic
from source_map import SourceMap


@dataclass(frozen=True, slots=True)
class DiagnosticStyle:
    color: bool = False


class DiagnosticRenderer:
    COLORS = {
        "error": "\033[1;31m",
        "warning": "\033[1;35m",
        "note": "\033[1;36m",
        "reset": "\033[0m",
        "bold": "\033[1m",
        "green": "\033[1;32m",
    }

    def __init__(self, source_map: SourceMap | None, style: DiagnosticStyle | None = None):
        self.source_map = source_map
        self.style = style or DiagnosticStyle()

    def _paint(self, text: str, color: str) -> str:
        if not self.style.color:
            return text
        return f"{self.COLORS[color]}{text}{self.COLORS['reset']}"

    def render(self, diagnostic: Diagnostic) -> str:
        span = self.source_map.span_for(diagnostic.node) if self.source_map else None
        filename = self.source_map.filename if self.source_map else "<unknown>"
        severity = diagnostic.severity
        label = self._paint(severity, severity if severity in self.COLORS else "error")
        code = f" [{diagnostic.code}]" if diagnostic.code else ""

        if span is None:
            return f"{filename}: {label}: {diagnostic.message}{code}"

        header = (
            f"{filename}:{span.start_line}:{span.start_column}: "
            f"{label}: {diagnostic.message}{code}"
        )
        source_line = self.source_map.line_text(span.start_line)
        if not source_line:
            return header

        width = max(1, (span.end_column - span.start_column) if span.end_line == span.start_line else 1)
        caret = " " * max(0, span.start_column - 1) + "^" + "~" * max(0, width - 1)
        if self.style.color:
            caret = " " * max(0, span.start_column - 1) + self._paint("^" + "~" * max(0, width - 1), "green")
        return f"{header}\n {span.start_line:>4} | {source_line}\n      | {caret}"


def should_use_color(mode: str, stream=None) -> bool:
    stream = stream or sys.stderr
    if mode == "always":
        return True
    if mode == "never" or os.getenv("NO_COLOR") is not None:
        return False
    return bool(getattr(stream, "isatty", lambda: False)())
