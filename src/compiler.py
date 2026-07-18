# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Expose the result-based Structured Text compilation pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from ast_builder import AstBuilder, ParseNode
from iec_generator_c import CCodeGenerator
from iec_generator_rust import RustCodeGenerator
from iec_lexer import IECLexer
from iec_parser import IECParser, ParsingError
from library import LibraryError, LibraryResolver, ResolvedLibraries
from native import extract_native_pragmas
from semantic import SemanticAnalyzer, SemanticError
from semantic_context import Diagnostic, SemanticContext
from source_map import SourceMap, build_source_map


AstNode = dict[str, Any]
CompilationTarget = Literal["c", "rust", "ast", "tree"]
SUPPORTED_TARGETS = frozenset(("c", "rust", "ast", "tree"))


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """All observable products of one compilation.

    Syntax and semantic failures are represented in the result rather than
    being raised. Invalid API arguments and unexpected internal failures still
    raise normally.
    """

    target: CompilationTarget
    source_name: str
    parse_tree: ParseNode | None = None
    ast: AstNode | None = None
    context: SemanticContext | None = None
    output: str | AstNode | None = None
    diagnostics: tuple[Diagnostic, ...] = ()
    syntax_error: ParsingError | SyntaxError | None = None
    source_map: SourceMap | None = None
    libraries: ResolvedLibraries | None = None

    @property
    def success(self) -> bool:
        return self.syntax_error is None and not any(
            diagnostic.severity == "error" for diagnostic in self.diagnostics
        )


def parse_tree(source: str) -> ParseNode | None:
    lexer = IECLexer()
    parser = IECParser().set_source(source)
    return parser.parse(lexer.tokenize(source))


def parse_source(source: str, ast_builder: AstBuilder | None = None) -> AstNode | None:
    tree = parse_tree(source)
    return (ast_builder or AstBuilder()).build(tree) if tree is not None else None


def compile_source(
    source: str,
    target: CompilationTarget = "c",
    *,
    check_semantics: bool = True,
    source_name: str = "<stdin>",
    semantic_analyzer: SemanticAnalyzer | None = None,
    ast_builder: AstBuilder | None = None,
    library_paths: tuple[str, ...] | list[str] = (),
    imports: tuple[str, ...] | list[str] = (),
) -> CompilationResult:
    """Compile source and return its products and diagnostics."""
    if target not in SUPPORTED_TARGETS:
        supported = ", ".join(sorted(SUPPORTED_TARGETS))
        raise ValueError(f"Unsupported compilation target {target!r}; expected one of: {supported}")

    libraries = LibraryResolver(library_paths).resolve(imports) if imports else ResolvedLibraries()
    parser_source, native_sections = extract_native_pragmas(source)
    builder = ast_builder or AstBuilder()
    try:
        tree = parse_tree(parser_source)
    except ParsingError as exc:
        return CompilationResult(target=target, source_name=source_name, syntax_error=exc)

    if tree is None:
        return CompilationResult(
            target=target,
            source_name=source_name,
            syntax_error=SyntaxError("Unable to parse source."),
        )

    ast = builder.build(tree)
    imported_nodes = []
    for imported in libraries.imports:
        imported_source, imported_native = extract_native_pragmas(imported.source)
        for key, implementation in imported_native.items():
            if key in native_sections:
                raise LibraryError(
                    f"Duplicate native implementation for {implementation.target}:{implementation.name}"
                )
            native_sections[key] = implementation
        try:
            imported_tree = parse_tree(imported_source)
        except ParsingError as exc:
            raise LibraryError(
                f"Cannot parse imported source {imported.source_name}: {exc}"
            ) from exc
        if imported_tree is None:
            raise LibraryError(f"Cannot parse imported source {imported.source_name}")
        imported_ast = builder.build(imported_tree)
        imported_nodes.extend(imported_ast.get("children", []))
    if imported_nodes:
        ast["children"] = imported_nodes + ast.get("children", [])

    if target == "ast":
        return CompilationResult(
            target=target,
            source_name=source_name,
            parse_tree=tree,
            ast=ast,
            output=json.dumps(ast, indent=2),
            libraries=libraries,
        )
    if target == "tree":
        return CompilationResult(
            target=target,
            source_name=source_name,
            parse_tree=tree,
            ast=ast,
            output=ast,
            libraries=libraries,
        )

    diagnostic_name = "<stdin>" if source_name == "-" else source_name
    source_map = build_source_map(ast, parser_source, diagnostic_name, IECLexer)
    context = None
    if check_semantics:
        try:
            context = (semantic_analyzer or SemanticAnalyzer()).analyze(ast, source_map=source_map)
        except SemanticError as exc:
            return CompilationResult(
                target=target,
                source_name=source_name,
                parse_tree=tree,
                ast=ast,
                context=exc.context,
                diagnostics=tuple(exc.diagnostics),
                source_map=exc.source_map or source_map,
                libraries=libraries,
            )

    generator = (
        RustCodeGenerator()
        if target == "rust"
        else CCodeGenerator(
            context=context,
            source_name=source_name,
            native_implementations={
                name: implementation
                for (implementation_target, name), implementation in native_sections.items()
                if implementation_target == "c"
            },
        )
    )
    generator.visit(ast)
    return CompilationResult(
        target=target,
        source_name=source_name,
        parse_tree=tree,
        ast=ast,
        context=context,
        output=generator.text.rstrip() + "\n",
        diagnostics=tuple(context.diagnostics) if context is not None else (),
        source_map=source_map,
        libraries=libraries,
    )


# Short public spelling for library clients. Keeping the implementation under
# compile_source avoids ambiguity at internal call sites.
compile = compile_source
