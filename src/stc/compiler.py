# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Expose the result-based Structured Text compilation pipeline."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .frontend.ast_builder import AstBuilder, ParseNode
from .semantic.enum_conversions import inject_enum_conversion_functions
from .codegen.c import CCodeGenerator
from .codegen.rust import RustCodeGenerator
from .codegen.generator.loader import bundled_generator, load_generator
from .frontend.lexer import IECLexer
from .frontend.languages import normalize_source_language, prepare_textual_source
from .frontend.parser import IECParser, ParsingError
from .libraries import LibraryError, LibraryResolver, ResolvedLibraries
from .native import extract_native_pragmas
from .semantic.analyzer import SemanticAnalyzer, SemanticError
from .semantic.context import Diagnostic, SemanticContext
from .source_map import SourceMap, build_source_map


AstNode = dict[str, Any]
CompilationTarget = str
BUNDLED_LIBRARY_DIRECTORY = Path(__file__).resolve().parent / "stdlib"


def normalize_standard_edition(standard: str | int) -> int:
    """Return the IEC 61131-3 edition selected by a public CLI/API spelling."""
    normalized = str(standard).strip().casefold().replace(" ", "")
    aliases = {
        "2": 2,
        "2.0": 2,
        "2003": 2,
        "ed2": 2,
        "iec61131-3:ed2": 2,
        "3": 3,
        "3.0": 3,
        "2013": 3,
        "ed3": 3,
        "iec61131-3:ed3": 3,
        "4": 4,
        "4.0": 4,
        "2025": 4,
        "ed4": 4,
        "iec61131-3:ed4": 4,
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        choices = "iec61131-3:ed2, iec61131-3:ed3 or iec61131-3:ed4"
        raise ValueError(f"Unsupported IEC standard {standard!r}; expected {choices}") from exc


def _walk_ast(node):
    if not isinstance(node, dict):
        return
    yield node
    for child in node.get("children", []):
        yield from _walk_ast(child)


def _mark_library_ast(node):
    """Tag imported nodes so source-profile diagnostics remain caller-local."""
    if not isinstance(node, dict):
        return
    node["library_import"] = True
    for child in node.get("children", []):
        _mark_library_ast(child)


def _selected_library_nodes(ast, symbol):
    """Return the top-level declaration exported under ``symbol``."""
    selected = []
    expected = symbol.casefold()
    declaration_names = {
        "derived_function_name",
        "derived_function_block_name",
        "program_type_name",
        "configuration_name",
    }
    for child in ast.get("children", []):
        names = {
            str(node.get("value", "")).casefold()
            for node in _walk_ast(child)
            if node.get("name") in declaration_names
        }
        if expected in names:
            selected.append(child)
    if not selected:
        raise LibraryError(f"Imported source does not declare exported symbol {symbol!r}")
    return selected


def _implicit_standard_imports(ast, libraries):
    """Load bundled ST implementations for referenced standard functions."""
    declared = {
        str(node.get("value", "")).casefold()
        for node in _walk_ast(ast)
        if node.get("name") == "derived_function_name"
    }
    referenced = {
        str(node.get("value", "")).upper()
        for node in _walk_ast(ast)
        if node.get("name") == "standard_function_name"
    }
    imported = {item.symbol.casefold() for item in libraries.imports}
    available = {
        "FIND",
        "BYTE_TO_BOOL", "WORD_TO_BOOL", "DWORD_TO_BOOL", "LWORD_TO_BOOL",
        "USINT_TO_CHAR", "UINT_TO_WCHAR", "UDINT_TO_UCHAR", "WCHAR_TO_UINT",
    }
    required = sorted(
        name for name in referenced & available
        if name.casefold() not in declared and name.casefold() not in imported
    )
    if not required or not BUNDLED_LIBRARY_DIRECTORY.is_dir():
        return
    resolved = LibraryResolver([BUNDLED_LIBRARY_DIRECTORY]).resolve(
        [f"standard:{name}" for name in required]
    )
    libraries.imports.extend(resolved.imports)


@dataclass(frozen=True, slots=True)
class CompilationResult:
    """All observable products of one compilation.

    Syntax and semantic failures are represented in the result rather than
    being raised. Invalid API arguments and unexpected internal failures still
    raise normally.
    """

    target: CompilationTarget
    source_name: str
    standard_edition: int = 3
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


def parse_tree(source: str, language: str = "auto") -> ParseNode | None:
    parser_source, has_il = prepare_textual_source(source, language)
    lexer = IECLexer()
    if has_il:
        lexer.set_language("IL")
    parser = IECParser().set_source(parser_source)
    return parser.parse(lexer.tokenize(parser_source))


def parse_source(source: str, ast_builder: AstBuilder | None = None, language: str = "auto") -> AstNode | None:
    tree = parse_tree(source, language=language)
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
    generate_code: bool = True,
    standard: str | int = "iec61131-3:ed3",
    language: str = "auto",
    generator_path: str | Path | None = None,
) -> CompilationResult:
    """Compile source and return its products and diagnostics."""
    generator_bundle = None
    if generator_path is not None:
        generator_bundle = load_generator(generator_path)
    elif target not in {"c", "rust", "ast", "tree"}:
        candidates = (Path.cwd() / "generators" / target, bundled_generator(target))
        generator_directory = next((candidate for candidate in candidates if candidate.is_dir()), None)
        if generator_directory is None:
            raise ValueError(
                f"Unknown target {target!r}; create generators/{target}/ or use --generator-path"
            )
        generator_bundle = load_generator(generator_directory)
    standard_edition = normalize_standard_edition(standard)
    source_language = normalize_source_language(language)

    libraries = LibraryResolver(library_paths).resolve(imports) if imports else ResolvedLibraries()
    parser_source, native_sections = extract_native_pragmas(source)
    parser_source, has_il = prepare_textual_source(parser_source, source_language)
    builder = ast_builder or AstBuilder()
    try:
        lexer = IECLexer()
        if has_il:
            lexer.set_language("IL")
        tree = IECParser().set_source(parser_source).parse(lexer.tokenize(parser_source))
    except ParsingError as exc:
        return CompilationResult(
            target=target,
            source_name=source_name,
            standard_edition=standard_edition,
            syntax_error=exc,
        )

    if tree is None:
        return CompilationResult(
            target=target,
            source_name=source_name,
            standard_edition=standard_edition,
            syntax_error=SyntaxError("Unable to parse source."),
        )

    ast = builder.build(tree)
    _implicit_standard_imports(ast, libraries)
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
            imported_tree = parse_tree(imported_source, language="auto")
        except ParsingError as exc:
            raise LibraryError(
                f"Cannot parse imported source {imported.source_name}: {exc}"
            ) from exc
        if imported_tree is None:
            raise LibraryError(f"Cannot parse imported source {imported.source_name}")
        imported_ast = builder.build(imported_tree)
        selected_nodes = _selected_library_nodes(imported_ast, imported.symbol)
        for selected_node in selected_nodes:
            _mark_library_ast(selected_node)
        imported_nodes.extend(selected_nodes)
    if imported_nodes:
        ast["children"] = imported_nodes + ast.get("children", [])

    if target == "ast":
        return CompilationResult(
            target=target,
            source_name=source_name,
            standard_edition=standard_edition,
            parse_tree=tree,
            ast=ast,
            output=json.dumps(ast, indent=2),
            libraries=libraries,
        )
    if target == "tree":
        return CompilationResult(
            target=target,
            source_name=source_name,
            standard_edition=standard_edition,
            parse_tree=tree,
            ast=ast,
            output=ast,
            libraries=libraries,
        )

    diagnostic_name = "<stdin>" if source_name == "-" else source_name
    source_map = build_source_map(ast, parser_source, diagnostic_name, IECLexer)
    inject_enum_conversion_functions(ast)
    context = None
    if check_semantics:
        try:
            context = (semantic_analyzer or SemanticAnalyzer()).analyze(
                ast,
                source_map=source_map,
                standard_edition=standard_edition,
            )
        except SemanticError as exc:
            return CompilationResult(
                target=target,
                source_name=source_name,
                standard_edition=standard_edition,
                parse_tree=tree,
                ast=ast,
                context=exc.context,
                diagnostics=tuple(exc.diagnostics),
                source_map=exc.source_map or source_map,
                libraries=libraries,
            )

    if not generate_code:
        return CompilationResult(
            target=target,
            source_name=source_name,
            standard_edition=standard_edition,
            parse_tree=tree,
            ast=ast,
            context=context,
            diagnostics=tuple(context.diagnostics) if context is not None else (),
            source_map=source_map,
            libraries=libraries,
        )

    # The two visitors are transitional AST-to-IR adapters.  The bundle's
    # declared output extension selects the matching reference adapter while
    # Phase 3/4 are still being migrated; rendering itself remains in .gen.
    rust_adapter = target == "rust" or (
        generator_bundle is not None and generator_bundle.extension == "rs"
    )
    generator = (
        RustCodeGenerator(
            context=context,
            source_name=source_name,
            native_implementations={
                name: implementation
                for (implementation_target, name), implementation in native_sections.items()
                if implementation_target == "rust"
            },
            generator_bundle=generator_bundle,
        )
        if rust_adapter
        else CCodeGenerator(
            context=context,
            source_name=source_name,
            native_implementations={
                name: implementation
                for (implementation_target, name), implementation in native_sections.items()
                if implementation_target == "c"
            },
            generator_bundle=generator_bundle,
        )
    )
    generator.visit(ast)
    return CompilationResult(
        target=target,
        source_name=source_name,
        standard_edition=standard_edition,
        parse_tree=tree,
        ast=ast,
        context=context,
        output=(
            generator.formatted_text()
            if isinstance(generator, RustCodeGenerator)
            else generator.text.rstrip() + "\n"
        ),
        diagnostics=tuple(context.diagnostics) if context is not None else (),
        source_map=source_map,
        libraries=libraries,
    )


# Short public spelling for library clients. Keeping the implementation under
# compile_source avoids ambiguity at internal call sites.
compile = compile_source
