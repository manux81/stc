# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Implement the command-line interface for the Structured Text compiler."""

import argparse
import json
import sys
from time import perf_counter

from .compiler import compile_source
from .diagnostics import DiagnosticRenderer, DiagnosticStyle, should_use_color
from .frontend.parser import ParsingError
from .libraries import LibraryError
from .native import NativePragmaError


VERSION = "0.2.0"

LOG_LEVELS = {
    "trace": 0,
    "debug": 10,
    "information": 20,
    "warning": 30,
    "error": 40,
    "critical": 50,
    "none": 100,
}
DIAGNOSTIC_LEVELS = {"hint": 10, "information": 20, "warning": 30, "error": 40}


def print_tree(node, indent=""):
    if isinstance(node, dict):
        name = node.get("name", "Unnamed")
        value = node.get("value")
        children = node.get("children", [])
        suffix = f" = {value}" if value is not None else ""
        print(f"{indent}{name}{suffix}")
        for child in children:
            print_tree(child, indent + "  ")
    elif isinstance(node, list):
        for item in node:
            print_tree(item, indent)
    else:
        print(f"{indent}{node}")


def read_source(path):
    if path == "-":
        return sys.stdin.read()
    with open(path, "r", encoding="utf-8") as source_file:
        return source_file.read()


def build_arg_parser():
    parser = argparse.ArgumentParser(
        prog="stc",
        description="IEC 61131-3 Structured Text compiler front-end.",
    )
    parser.add_argument(
        "source",
        nargs="?",
        default="-",
        help="Structured Text source file. Use '-' or omit to read stdin.",
    )
    parser.add_argument(
        "-g",
        "--generator",
        choices=("c", "rust", "ast", "tree"),
        default="c",
        help="Output generator.",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write generated output to this file instead of stdout.",
    )
    parser.add_argument(
        "-s",
        "--std",
        default="iec61131-3:ed3",
        metavar="EDITION",
        help="IEC standard profile (iec61131-3:ed3 or iec61131-3:ed4).",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Display compiler version information.",
    )
    parser.add_argument(
        "-l",
        "--log",
        type=str.casefold,
        choices=tuple(LOG_LEVELS),
        default="information",
        metavar="LEVEL",
        help="Minimum diagnostic level: Trace, Debug, Information, Warning, Error, Critical, None.",
    )
    parser.add_argument(
        "-fwarnings-as-errors",
        action="store_true",
        help="Return a compilation failure when warnings are emitted.",
    )
    parser.add_argument(
        "-fskip-code-gen",
        action="store_true",
        help="Run parsing and semantic analysis without generating target code.",
    )
    parser.add_argument(
        "--write-statistics-to",
        metavar="FILE",
        help="Write compilation statistics as JSON. The parent directory must exist.",
    )
    parser.add_argument(
        "-1",
        "--1core",
        dest="one_core",
        action="store_true",
        help="Force one-core operation. STC is currently single-threaded, so this is a compatibility option.",
    )
    parser.add_argument(
        "--diagnostic-color",
        choices=("auto", "always", "never"),
        default="auto",
        help="Colorize diagnostics like Clang.",
    )
    parser.add_argument(
        "--no-semantic-check",
        action="store_true",
        help="Skip semantic checks before code generation.",
    )
    parser.add_argument(
        "-L",
        "--library-path",
        action="append",
        default=[],
        help="Add a directory to the library search path.",
    )
    parser.add_argument(
        "--import",
        dest="imports",
        action="append",
        default=[],
        metavar="LIBRARY[:SYMBOL]",
        help="Import every export from a library or select one export.",
    )
    return parser


def report_compilation_failure(result, color_mode="auto", log_level="information", stream=None):
    stream = stream or sys.stderr
    threshold = LOG_LEVELS[log_level]
    if threshold >= LOG_LEVELS["none"]:
        return
    color = should_use_color(color_mode, stream)
    if result.syntax_error is not None:
        if threshold > LOG_LEVELS["error"]:
            return
        exc = result.syntax_error
        filename = "<stdin>" if result.source_name == "-" else result.source_name
        if isinstance(exc, ParsingError):
            line = exc.line or 1
            column = exc.column or 1
            label = "\033[1;31merror\033[0m" if color else "error"
            print(f"{filename}:{line}:{column}: {label}: {exc.args[0]} [syntax-error]", file=stream)
            if exc.source_line is not None:
                print(f" {line:>4} | {exc.source_line}", file=stream)
                marker = " " * max(0, column - 1) + "^"
                if color:
                    marker = " " * max(0, column - 1) + "\033[1;32m^\033[0m"
                print(f"      | {marker}", file=stream)
        else:
            print(f"{filename}: error: {exc} [syntax-error]", file=stream)
        print("stc: 1 error generated.", file=stream)
        return

    renderer = DiagnosticRenderer(
        result.source_map,
        DiagnosticStyle(color=color),
    )
    visible_diagnostics = [
        diagnostic
        for diagnostic in result.diagnostics
        if DIAGNOSTIC_LEVELS.get(diagnostic.severity, LOG_LEVELS["information"]) >= threshold
    ]
    for diagnostic in visible_diagnostics:
        print(renderer.render(diagnostic), file=stream)
    error_count = sum(d.severity == "error" for d in visible_diagnostics)
    warning_count = sum(d.severity == "warning" for d in visible_diagnostics)
    suffix = []
    if error_count:
        suffix.append(f"{error_count} error" + ("s" if error_count != 1 else ""))
    if warning_count:
        suffix.append(f"{warning_count} warning" + ("s" if warning_count != 1 else ""))
    if suffix:
        print("stc: " + " and ".join(suffix) + " generated.", file=stream)


def main(argv=None):
    arg_parser = build_arg_parser()
    args = arg_parser.parse_args(argv)

    if args.version:
        print(f"stc {VERSION}")
        return 0

    try:
        source = read_source(args.source)
        started_at = perf_counter()
        compilation = compile_source(
            source,
            args.generator,
            check_semantics=not args.no_semantic_check,
            source_name=args.source,
            library_paths=args.library_path,
            imports=args.imports,
            generate_code=not args.fskip_code_gen,
            standard=args.std,
        )
        elapsed_ms = (perf_counter() - started_at) * 1000.0
    except (OSError, ValueError, LibraryError, NativePragmaError) as exc:
        print(f"stc: {exc}", file=sys.stderr)
        return 2

    error_count = sum(d.severity == "error" for d in compilation.diagnostics)
    warning_count = sum(d.severity == "warning" for d in compilation.diagnostics)
    failed = not compilation.success or (args.fwarnings_as_errors and warning_count > 0)

    if args.write_statistics_to:
        statistics = {
            "compiler": "stc",
            "version": VERSION,
            "source": args.source,
            "target": args.generator,
            "source_bytes": len(source.encode("utf-8")),
            "elapsed_ms": round(elapsed_ms, 3),
            "errors": error_count + (1 if compilation.syntax_error is not None else 0),
            "warnings": warning_count,
            "success": not failed,
            "code_generation_skipped": args.fskip_code_gen,
            "requested_one_core": args.one_core,
            "cores_used": 1,
        }
        statistics_path = args.write_statistics_to
        try:
            with open(statistics_path, "w", encoding="utf-8") as statistics_file:
                json.dump(statistics, statistics_file, indent=2, sort_keys=True)
                statistics_file.write("\n")
        except OSError as exc:
            print(f"stc: cannot write statistics file {statistics_path}: {exc}", file=sys.stderr)
            return 2

    if failed:
        report_compilation_failure(compilation, args.diagnostic_color, args.log)
        return 1

    if warning_count:
        report_compilation_failure(compilation, args.diagnostic_color, args.log)

    if args.fskip_code_gen:
        return 0

    if args.generator == "tree":
        print_tree(compilation.output)
        return 0

    try:
        if args.output:
            with open(args.output, "w", encoding="utf-8") as output_file:
                output_file.write(compilation.output)
        else:
            print(compilation.output, end="")
    except OSError as exc:
        print(f"stc: cannot write output file {args.output}: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
