#!/usr/bin/env python3
# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Compare implemented parser productions with extracted IEC documentation."""

import ast
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "src" / "iec_parser.py"
ANNEX_B = ROOT / "tmp" / "pdfs" / "annex_b.txt"


GRAPHICAL_NONTERMINALS = {
    "ladder_diagram",
    "function_block_diagram",
    "fbd_network",
    "rung",
}

LEXER_NONTERMINALS = {
    "bit",
    "digit",
    "exponent",
    "hex_digit",
    "identifier",
    "letter",
    "octal_digit",
}


def parser_productions(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "IECParser":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and is_production(item):
                    names.add(item.name)
    return names


def is_production(method):
    for decorator in method.decorator_list:
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
            if decorator.func.id == "_":
                return True
    return False


def doc_productions(annex_path):
    text = annex_path.read_text(encoding="utf-8")
    text = text.replace(":: =", "::=").replace(": =", ":=")
    pattern = re.compile(r"(?m)^([a-z][a-z0-9_]*)\s*(?:::?=|:=)")
    return {match.group(1) for match in pattern.finditer(text)}


def main():
    parser_names = parser_productions(PARSER)
    doc_names = doc_productions(ANNEX_B)
    delegated = GRAPHICAL_NONTERMINALS | LEXER_NONTERMINALS
    missing = sorted(doc_names - parser_names - delegated)
    extra = sorted(parser_names - doc_names)

    print(f"doc_productions={len(doc_names)}")
    print(f"parser_productions={len(parser_names)}")
    print(f"delegated_to_lexer={len(sorted(doc_names & LEXER_NONTERMINALS))}")
    print(f"graphical_not_in_text_frontend={len(sorted(doc_names & GRAPHICAL_NONTERMINALS))}")
    print(f"missing_from_parser={len(missing)}")
    for name in missing:
        print(f"missing {name}")
    print(f"extra_in_parser={len(extra)}")
    for name in extra:
        print(f"extra {name}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
