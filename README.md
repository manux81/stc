# stc

Structured Text Compiler.

`stc` is an executable IEC 61131-3 Structured Text compiler front-end written in
Python. The current milestone turns the original grammar prototype into a
usable command-line tool that can parse ST files and emit an AST, C, or Rust for
the supported subset.

## Current capabilities

- IEC 61131-3 POU parsing for functions.
- `VAR_INPUT` and function-local `VAR` declarations.
- Elementary types including `BOOL`, signed/unsigned integers, `REAL`, `LREAL`,
  and bit-string integer families.
- Integer, real, boolean, and typed numeric literals such as `INT#10`.
- Assignments, `IF` / `ELSIF` / `ELSE`, `WHILE`, and `REPEAT`.
- C and Rust code generation for the supported function subset.
- JSON AST output for downstream tooling and regression tests.

## Usage

```sh
python3 src/main.py examples/inter.st -g ast
python3 src/main.py examples/inter.st -g c
python3 src/main.py examples/inter.st -g rust
python3 src/main.py examples/inter.st -g c -o build/inter.c
```

Use `-` or omit the source path to read from stdin.

## Tests

```sh
python3 -m unittest discover -s tests
```

## Positioning

The long-term target is to grow toward the practical compiler quality of
STruC++ and matiec:

- STruC++: readable generated C++17, reusable libraries, integrated testing, and
  debugging/REPL workflows.
- matiec: broad IEC 61131-3 compiler coverage and mature PLC-oriented code
  generation.

This repository is not at that level yet. The next steps are deliberately
foundation-first so compatibility can be expanded without repeatedly rewriting
the frontend.

## Roadmap

1. Replace dict-based AST nodes with typed nodes carrying source spans.
2. Add deterministic diagnostics with line/column ranges and recovery tests.
3. Split parsing, semantic analysis, and backend generation into separate
   compiler phases.
4. Implement a symbol table and type checker for functions, function blocks,
   programs, arrays, structs, direct variables, and configurations.
5. Expand grammar coverage for function blocks, programs, `CASE`, `FOR`,
   arrays, structures, strings, time/date literals, and standard functions.
6. Add a compatibility corpus with accepted and rejected IEC 61131-3 programs.
7. Add generated-code compile tests for C and Rust on CI.
8. Add a runtime/library layer for standard IEC functions and function blocks.
9. Add C++17 generation once the typed IR is stable.
10. Add ST-level tests and an interactive execution/debugging loop.

## References

- IEC 61131-3:2013, Programmable controllers, Part 3.
- [Autonomy-Logic/STruCpp](https://github.com/Autonomy-Logic/STruCpp)
- [beremiz/matiec](https://github.com/beremiz/matiec)
