# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Validate source constructs whose status changed between IEC editions."""

import re

from .base import SemanticCheck, SemanticPhase, register_check


@register_check(
    name="edition-compatibility",
    phase=SemanticPhase.VALIDATION,
    description="Enforce IEC 61131-3 edition-specific removals and deprecations.",
)
class EditionCompatibilityCheck(SemanticCheck):
    """Report Edition 4 removals while preserving the Edition 3 default."""

    def _belongs_to_compilation_unit(self, node):
        """Exclude bundled library declarations from the caller's source profile."""
        return not node.get("library_import", False)

    def visit_octal_integer(self, node):
        if not self._belongs_to_compilation_unit(node):
            self.generic_visit(node)
            return
        if self.context.standard_edition >= 4:
            self.error(
                "edition4-octal-literal",
                "Octal integer literals were removed in IEC 61131-3 Edition 4.",
                node,
            )
        else:
            self.warning(
                "edition3-deprecated-octal-literal",
                "Octal integer literals are deprecated in IEC 61131-3 Edition 3.",
                node,
            )
        self.generic_visit(node)

    def visit_unicode_character_string(self, node):
        if self.context.standard_edition < 4 and self._belongs_to_compilation_unit(node):
            self.error(
                "edition4-unicode-literal",
                "Unicode character strings require IEC 61131-3 Edition 4.",
                node,
            )
        token = next(
            (child for child in node.get("children", []) if isinstance(child, dict) and child.get("name") == "token"),
            None,
        )
        raw = str(token.get("value", "")) if token else ""
        invalid_scalar = False
        for encoded in re.findall(r"\$\{([0-9A-Fa-f]{1,6})\}", raw):
            value = int(encoded, 16)
            if value > 0x10FFFF or 0xD800 <= value <= 0xDFFF:
                invalid_scalar = True
                self.error(
                    "invalid-unicode-scalar",
                    f"${{{encoded}}} is not a valid Unicode scalar value.",
                    node,
                )
        if raw.lstrip().upper().startswith("UCHAR") and not invalid_scalar and self._belongs_to_compilation_unit(node):
            quoted = raw[raw.find("#") + 1:].strip()
            content = quoted[1:-1]
            content = re.sub(r"\$\{([0-9A-Fa-f]{1,6})\}", lambda match: chr(int(match.group(1), 16)), content)
            content = content.replace("$$", "$").replace("''", "'")
            if len(content) != 1:
                self.error(
                    "invalid-uchar-literal",
                    "A UCHAR literal must contain exactly one Unicode character.",
                    node,
                )
        self.generic_visit(node)

    def visit_typed_character_string(self, node):
        token = next(
            (child for child in node.get("children", []) if isinstance(child, dict) and child.get("name") == "token"),
            None,
        )
        raw = str(token.get("value", "")) if token else ""
        prefix = raw[:raw.find("#")].strip().upper()
        if prefix in {"CHAR", "WCHAR"}:
            quoted = raw[raw.find("#") + 1:].strip()
            content = quoted[1:-1]
            content = re.sub(
                r"\$([0-9A-Fa-f]{2}|[0-9A-Fa-f]{4})",
                lambda match: chr(int(match.group(1), 16)),
                content,
            )
            content = content.replace("$$", "$").replace("''", "'").replace('""', '"')
            if len(content) != 1:
                self.error(
                    "invalid-character-literal",
                    f"A {prefix} literal must contain exactly one character.",
                    node,
                )
        self.generic_visit(node)

    def visit_assert_statement(self, node):
        if self.context.standard_edition < 4 and self._belongs_to_compilation_unit(node):
            self.error(
                "edition4-assert",
                "ASSERT requires IEC 61131-3 Edition 4.",
                node,
            )
        self.generic_visit(node)

    def visit_token(self, node):
        value = str(node.get("value", "")).upper()
        if self.context.standard_edition < 4 and value in {"USTRING", "UCHAR"} and self._belongs_to_compilation_unit(node):
            self.error(
                "edition4-unicode-type",
                f"{value} requires IEC 61131-3 Edition 4.",
                node,
            )

    def visit_elementary_type_name(self, node):
        values = {str(child).upper() for child in node.get("children", []) if isinstance(child, str)}
        edition4_types = values & {"USTRING", "UCHAR"}
        if self.context.standard_edition < 4 and edition4_types and self._belongs_to_compilation_unit(node):
            type_name = sorted(edition4_types)[0]
            self.error(
                "edition4-unicode-type",
                f"{type_name} requires IEC 61131-3 Edition 4.",
                node,
            )
        self.generic_visit(node)

    def visit_standard_function_name(self, node):
        if not self._belongs_to_compilation_unit(node):
            return
        name = str(node.get("value", "")).upper()
        edition4_only = {
            "LEN_CODE_UNIT",
            "USINT_TO_CHAR",
            "UINT_TO_WCHAR",
            "WCHAR_TO_UINT",
            "UDINT_TO_UCHAR",
        }
        if self.context.standard_edition < 4:
            if name in edition4_only:
                self.error(
                    "edition4-standard-function",
                    f"{name} requires IEC 61131-3 Edition 4.",
                    node,
                )
            elif name == "TRUNC":
                self.warning(
                    "edition3-deprecated-trunc",
                    "TRUNC is deprecated in Edition 3; use a typed form such as TRUNC_DINT.",
                    node,
                )
            return
        if name == "TRUNC":
            self.error(
                "edition4-untyped-trunc",
                "TRUNC is not available in Edition 4; use a result-typed conversion such as TRUNC_DINT.",
                node,
            )
        elif "BCD" in name:
            self.warning(
                "edition4-deprecated-bcd",
                f"{name} is deprecated in IEC 61131-3 Edition 4.",
                node,
            )
