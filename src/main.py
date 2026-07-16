import argparse
import json
import sys

from iec_generator_c import CCodeGenerator
from iec_generator_rust import RustCodeGenerator
from iec_lexer import IECLexer
from iec_parser import IECParser
from semantic import SemanticAnalyzer, SemanticError


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


def parse_source(source):
    lexer = IECLexer()
    parser = IECParser()
    tokens = lexer.tokenize(source)
    return parser.parse(tokens)


def generate(source, target, check_semantics=True):
    ast = parse_source(source)
    if ast is None:
        raise SyntaxError("Unable to parse source.")

    if target == "ast":
        return json.dumps(ast, indent=2)
    if target == "tree":
        return ast

    if check_semantics:
        SemanticAnalyzer().analyze(ast)

    generator = RustCodeGenerator() if target == "rust" else CCodeGenerator()
    generator.visit(ast)
    return generator.text.rstrip() + "\n"


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
        "--no-semantic-check",
        action="store_true",
        help="Skip semantic checks before code generation.",
    )
    return parser


def main(argv=None):
    arg_parser = build_arg_parser()
    args = arg_parser.parse_args(argv)

    if args.version:
        print(f"stc {VERSION}")
        return 0

    try:
        source = read_source(args.source)
        result = generate(source, args.generator, not args.no_semantic_check)
    except OSError as exc:
        print(f"stc: {exc}", file=sys.stderr)
        return 2
    except SyntaxError as exc:
        print(f"stc: syntax error: {exc}", file=sys.stderr)
        return 1
    except SemanticError as exc:
        for diagnostic in exc.diagnostics:
            print(f"stc: semantic error: {diagnostic}", file=sys.stderr)
        return 1

    if args.generator == "tree":
        print_tree(result)
        return 0

    if args.output:
        with open(args.output, "w", encoding="utf-8") as output_file:
            output_file.write(result)
    else:
        print(result, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
