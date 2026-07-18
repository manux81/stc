import argparse
import sys

from compiler import compile_source
from diagnostics import DiagnosticRenderer, DiagnosticStyle, should_use_color
from iec_parser import ParsingError
from library import LibraryError


VERSION = "0.2.0"


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
        help="IEC standard dialect marker accepted for compatibility.",
    )
    parser.add_argument(
        "-v",
        "--version",
        action="store_true",
        help="Display compiler version information.",
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


def report_compilation_failure(result, color_mode="auto", stream=None):
    stream = stream or sys.stderr
    color = should_use_color(color_mode, stream)
    if result.syntax_error is not None:
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
    for diagnostic in result.diagnostics:
        print(renderer.render(diagnostic), file=stream)
    error_count = sum(d.severity == "error" for d in result.diagnostics)
    warning_count = sum(d.severity == "warning" for d in result.diagnostics)
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
        compilation = compile_source(
            source,
            args.generator,
            check_semantics=not args.no_semantic_check,
            source_name=args.source,
            library_paths=args.library_path,
            imports=args.imports,
        )
    except (OSError, LibraryError) as exc:
        print(f"stc: {exc}", file=sys.stderr)
        return 2

    if not compilation.success:
        report_compilation_failure(compilation, args.diagnostic_color)
        return 1

    if args.generator == "tree":
        print_tree(compilation.output)
        return 0

    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(compilation.output)
    else:
        print(compilation.output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
