# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Select textual IEC languages and preserve IL instruction boundaries."""

from __future__ import annotations

import re


SUPPORTED_SOURCE_LANGUAGES = frozenset({"auto", "st", "il"})

_POU_START = re.compile(r"^\s*(?:FUNCTION(?:_BLOCK)?|PROGRAM|METHOD|ACTION|TRANSITION)\b", re.I)
_POU_END = re.compile(r"^\s*END_(?:FUNCTION(?:_BLOCK)?|PROGRAM|METHOD|ACTION|TRANSITION)\b", re.I)
_VAR_START = re.compile(r"^\s*VAR(?:_(?:INPUT|OUTPUT|IN_OUT|TEMP|EXTERNAL|ACCESS))?\b", re.I)
_VAR_END = re.compile(r"^\s*END_VAR\b", re.I)
_IL_START = re.compile(
    r"^\s*(?:[A-Za-z_]\w*\s*:\s*)?"
    r"(?:LDN?|STN?|NOT|S|R|S1|R1|CLK|CU|CD|PV|IN|PT|ANDN?|&N?|ORN?|XORN?|"
    r"ADD|SUB|MUL|DIV|MOD|GT|GE|EQ|LT|LE|NE|CALC?N?|RETC?N?|JMPC?N?)"
    r"(?:\s|\(|$)",
    re.I,
)


def normalize_source_language(language: str) -> str:
    normalized = str(language).strip().casefold()
    if normalized not in SUPPORTED_SOURCE_LANGUAGES:
        choices = ", ".join(sorted(SUPPORTED_SOURCE_LANGUAGES))
        raise ValueError(f"Unsupported IEC source language {language!r}; expected one of: {choices}")
    return normalized


def prepare_textual_source(source: str, language: str = "auto") -> tuple[str, bool]:
    """Replace newlines in IL bodies with the grammar's explicit EOL token.

    Declarations use ordinary whitespace while IL instructions are line based.
    Keeping the replacement one code point wide preserves source-map offsets.
    In ``auto`` mode the first executable line of every POU decides whether its
    body is IL.  Explicit ``il`` is useful for unusual programs whose first
    instruction is a derived function name rather than a standard operator.
    """

    selected = normalize_source_language(language)
    lines = source.splitlines(keepends=True)
    in_pou = False
    in_var = False
    body_language: str | None = None
    saw_il = False
    prepared: list[str] = []

    for line in lines:
        content = line.rstrip("\r\n")
        newline = line[len(content):]
        stripped = re.sub(r"\(\*[\s\S]*?\*\)", "", content).strip()

        if _POU_START.match(content):
            in_pou = True
            in_var = False
            body_language = None
        elif in_pou and _VAR_START.match(content):
            in_var = True

        if in_pou and not in_var and body_language is None and stripped:
            if not _POU_START.match(content) and not _VAR_END.match(content):
                looks_like_assignment = re.match(r"^\s*[A-Za-z_]\w*(?:\s*\.\s*[A-Za-z_]\w*)*\s*:=", content) is not None
                body_language = selected if selected != "auto" else (
                    "il" if _IL_START.match(content) and not looks_like_assignment else "st"
                )

        is_il_line = in_pou and not in_var and body_language == "il" and not _POU_END.match(content)
        if is_il_line and newline:
            prepared.append(content + "\u2029" * newline.count("\n"))
            saw_il = True
        else:
            prepared.append(line)

        if re.search(r"\bEND_VAR\b", content, re.I):
            in_var = False
        if _POU_END.match(content):
            in_pou = False
            in_var = False
            body_language = None

    return "".join(prepared), saw_il
