# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Extract target-native code embedded in IEC pragma blocks."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


_PRAGMA = re.compile(
    r"\{#native\s+(?P<target>[A-Za-z0-9_+-]+)\s+"
    r"(?P<section>body|setup|loop)\s*\}"
    r"(?P<code>.*?)"
    r"\{#end_native\}",
    re.IGNORECASE | re.DOTALL,
)
_POU = re.compile(
    r"\b(?P<kind>FUNCTION_BLOCK|FUNCTION)\s+(?P<name>[A-Za-z_][A-Za-z0-9_]*)",
    re.IGNORECASE,
)


class NativePragmaError(ValueError):
    pass


@dataclass(slots=True)
class NativeImplementation:
    kind: str
    name: str
    target: str
    sections: dict[str, str] = field(default_factory=dict)

    def section(self, name: str) -> str | None:
        return self.sections.get(name)


def extract_native_pragmas(source: str) -> tuple[str, dict[tuple[str, str], NativeImplementation]]:
    """Return parser-safe source and native implementations keyed by target/name.

    Replacing pragma contents with whitespace preserves line and column offsets
    for the existing source-map implementation.
    """
    implementations: dict[tuple[str, str], NativeImplementation] = {}
    output = []
    cursor = 0
    for match in _PRAGMA.finditer(source):
        declarations = list(_POU.finditer(source, 0, match.start()))
        if not declarations:
            raise NativePragmaError("Native pragma is not inside a FUNCTION or FUNCTION_BLOCK")
        declaration = declarations[-1]
        kind = declaration.group("kind").casefold()
        name = declaration.group("name")
        target = match.group("target").casefold()
        section = match.group("section").casefold()
        if kind == "function" and section != "body":
            raise NativePragmaError(f"Function {name!r} only accepts a native body section")
        if kind == "function_block" and section == "body":
            raise NativePragmaError(
                f"Function block {name!r} uses setup/loop sections instead of body"
            )
        key = (target, name.casefold())
        implementation = implementations.setdefault(
            key,
            NativeImplementation(kind, name, target),
        )
        if section in implementation.sections:
            raise NativePragmaError(f"Duplicate native {section} section for {name!r}")
        implementation.sections[section] = match.group("code").strip()

        output.append(source[cursor:match.start()])
        pragma = match.group(0)
        output.append("".join("\n" if char == "\n" else " " for char in pragma))
        cursor = match.end()
    output.append(source[cursor:])
    return "".join(output), implementations
