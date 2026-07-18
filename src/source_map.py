"""Source locations for AST nodes without polluting the serialized AST."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

AstNode = dict[str, Any]


@dataclass(frozen=True, slots=True)
class SourceSpan:
    start_line: int
    start_column: int
    end_line: int
    end_column: int
    start_index: int
    end_index: int


@dataclass(slots=True)
class SourceMap:
    filename: str
    source: str
    spans: dict[int, SourceSpan]

    def span_for(self, node: AstNode | None) -> SourceSpan | None:
        return self.spans.get(id(node)) if isinstance(node, dict) else None

    def line_text(self, line: int) -> str:
        lines = self.source.splitlines()
        return lines[line - 1] if 1 <= line <= len(lines) else ""


def _nodes_postorder(node: AstNode) -> Iterable[AstNode]:
    for child in node.get("children", []):
        if isinstance(child, dict):
            yield from _nodes_postorder(child)
    yield node


def _leaf_nodes(node: AstNode) -> Iterable[AstNode]:
    children = [child for child in node.get("children", []) if isinstance(child, dict)]
    if "value" in node and node.get("value") is not None:
        yield node
    for child in children:
        yield from _leaf_nodes(child)


def build_source_map(ast: AstNode, source: str, filename: str, lexer_factory) -> SourceMap:
    """Match value-bearing AST nodes to lexer tokens, then span parent nodes.

    The grammar currently creates plain dictionaries and discards production
    positions. Token matching preserves that public AST format and still gives
    semantic diagnostics precise locations.
    """
    tokens = list(lexer_factory().tokenize(source))
    spans: dict[int, SourceSpan] = {}
    cursor = 0

    def comparable(value: object) -> str:
        return str(value).casefold()

    for node in _leaf_nodes(ast):
        wanted = comparable(node.get("value"))
        matched_index = None
        for index in range(cursor, len(tokens)):
            token = tokens[index]
            if comparable(token.value) == wanted:
                matched_index = index
                break
        if matched_index is None:
            # Operators may be normalized by grammar nodes; search globally as a
            # fallback, preferring an unused token.
            for index, token in enumerate(tokens):
                if comparable(token.value) == wanted and all(
                    span.start_index != token.index for span in spans.values()
                ):
                    matched_index = index
                    break
        if matched_index is None:
            continue

        token = tokens[matched_index]
        raw = str(token.value)
        start = token.index
        end = start + max(len(raw), 1)
        end_line = token.lineno + raw.count("\n")
        if "\n" in raw:
            end_column = len(raw.rsplit("\n", 1)[-1]) + 1
        else:
            end_column = token.column + max(len(raw), 1)
        spans[id(node)] = SourceSpan(
            token.lineno,
            token.column,
            end_line,
            end_column,
            start,
            end,
        )
        cursor = matched_index + 1

    for node in _nodes_postorder(ast):
        if id(node) in spans:
            continue
        child_spans = [
            spans[id(child)]
            for child in node.get("children", [])
            if isinstance(child, dict) and id(child) in spans
        ]
        if not child_spans:
            continue
        first = min(child_spans, key=lambda item: item.start_index)
        last = max(child_spans, key=lambda item: item.end_index)
        spans[id(node)] = SourceSpan(
            first.start_line,
            first.start_column,
            last.end_line,
            last.end_column,
            first.start_index,
            last.end_index,
        )

    return SourceMap(filename=filename, source=source, spans=spans)
