#!/usr/bin/env python3
import ast
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARSER = ROOT / "src" / "iec_parser.py"


def parser_methods(source_path):
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "IECParser":
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and is_production(item):
                    yield item


def is_production(method):
    for decorator in method.decorator_list:
        if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name):
            if decorator.func.id == "_":
                return True
    return False


def is_placeholder(method):
    return any(isinstance(node, ast.Pass) for node in ast.walk(method))


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Report implemented vs placeholder IEC parser productions.",
    )
    parser.add_argument(
        "--parser",
        type=Path,
        default=PARSER,
        help="Path to iec_parser.py.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List placeholder production method names.",
    )
    args = parser.parse_args(argv)

    methods = list(parser_methods(args.parser))
    placeholders = [method.name for method in methods if is_placeholder(method)]
    implemented = len(methods) - len(placeholders)

    print(f"parser_methods={len(methods)}")
    print(f"implemented={implemented}")
    print(f"placeholders={len(placeholders)}")
    if methods:
        print(f"implemented_percent={implemented / len(methods) * 100:.1f}")

    if args.list:
        for name in placeholders:
            print(name)

    return 1 if placeholders else 0


if __name__ == "__main__":
    raise SystemExit(main())
