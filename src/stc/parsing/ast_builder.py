# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Convert parser-owned trees into detached compiler AST nodes."""
from __future__ import annotations

from typing import Any


ParseNode = dict[str, Any]
AstNode = dict[str, Any]


class AstBuildError(ValueError):
    """Raised when the parser returns a malformed tree."""


class AstBuilder:
    """Build an AST detached from parser-owned node objects.

    The current AST remains dictionary-based. Keeping the conversion behind
    this class allows typed nodes to be introduced incrementally without
    coupling parser productions to semantic or backend representations.
    """

    def build(self, parse_tree: ParseNode) -> AstNode:
        return self._build_node(parse_tree)

    def _build_node(self, node: ParseNode) -> AstNode:
        if not isinstance(node, dict):
            raise AstBuildError(f"Expected a parse node, got {type(node).__name__}")

        name = node.get("name")
        children = node.get("children")
        if not isinstance(name, str) or not name:
            raise AstBuildError("Parse node is missing a non-empty 'name'")
        if not isinstance(children, list):
            raise AstBuildError(f"Parse node {name!r} is missing a 'children' list")

        built: AstNode = {"name": name}
        if "value" in node:
            built["value"] = node["value"]
        built["children"] = [
            self._build_node(child) if isinstance(child, dict) else child
            for child in children
        ]
        return built
