<!--
Copyright (C) 2021-2026 Manuele Conti
SPDX-License-Identifier: GPL-2.0-or-later
Summary: Documents the compiler architecture, usage, libraries, diagnostics, and roadmap.
-->

# stc

Structured Text Compiler.

`stc` is an executable IEC 61131-3 Structured Text compiler front-end written in
Python. The current milestone turns the original grammar prototype into a
usable command-line tool that can parse ST files and emit an AST, C, or Rust for
the supported subset.

## Current capabilities

- IEC 61131-3 POU parsing for functions, function blocks, and programs.
- `VAR_INPUT` and function-local `VAR` declarations.
- Elementary types including `BOOL`, signed/unsigned integers, `REAL`, `LREAL`,
  and bit-string integer families.
- Derived type and declaration parsing for common arrays, structures, and
  strings in AST output.
- Integer, real, boolean, typed numeric literals such as `INT#10`, strings, and
  date/time literals.
- Assignments, `IF` / `ELSIF` / `ELSE`, `CASE`, `FOR`, `WHILE`, and `REPEAT`.
- Standard function call parsing for common IEC functions in AST output.
- C and Rust code generation for functions, programs, function blocks, and
  standalone actions in the supported subset. Function-block instances expose
  a cycle entry point (`_step` in C, `step` in Rust); native C blocks retain
  their existing `_setup` / `_loop` ABI.
- `VAR_OUTPUT` and `VAR_IN_OUT` lowering for functions and function blocks,
  plus standard `EXIT` in generated loop bodies.
- Target declarations for aliases, arrays, structures, strings, subranges,
  and enumerations when represented by the parser AST.
- JSON AST output for downstream tooling and regression tests.
- Minimal semantic checks for undeclared variables before code generation.
- Structural AST output for every parser production currently present in the
  grammar.

## Usage

```sh
python3 -m stc examples/inter.st -g ast
python3 -m stc examples/inter.st -g c
python3 -m stc examples/inter.st -g rust
python3 -m stc examples/inter.st -g c -o build/inter.c
python3 -m stc examples/inter.st -g c --no-semantic-check
```

`stc.cli` is the compiler CLI entry point: `-g c` selects
`CCodeGenerator`, while `-g rust` selects `RustCodeGenerator` through the
shared `compile_source()` pipeline. The generated files contain IEC functions
as reusable C/Rust functions; they intentionally do not synthesize an
application `main()`, because a PLC runtime must decide how and when to invoke
the program cycle.

Use `-` or omit the source path to read from stdin.

## Python compilation API

Library clients can use the same result-based pipeline as the CLI:

```python
from stc import compile_source

result = compile_source(source, "c", source_name="example.st")
if result.success:
    c_source = result.output
else:
    for diagnostic in result.diagnostics:
        print(diagnostic.code, diagnostic.message)
```

`CompilationResult` preserves the parse tree, AST, semantic context, source
map, diagnostics, and generated output when they are available. Syntax and
semantic failures are returned as data; invalid API usage and unexpected
compiler faults still raise exceptions.

The parser output is converted through an injectable `AstBuilder`. The current
AST is still dictionary-based, but it is detached from parser-owned objects so
typed nodes can replace it incrementally without changing the compilation API.

## Libraries and native implementations

Add library search directories with `-L` and import either every export or one
selected symbol:

```sh
python3 -m stc application.st -g c -L ./libraries --import math
python3 -m stc application.st -g c -L ./libraries --import math:NativeAdd
```

Each library is described by `stc-library.json`:

```json
{
  "schema": 1,
  "name": "math",
  "exports": {
    "NativeAdd": {
      "source": "NativeAdd.st"
    }
  }
}
```

Target-native implementations use matiec-style pragmas inside the IEC source.
A function uses a `body` section:

```iecst
{#native c body}
NativeAdd = lhs + rhs;
{#end_native}
```

A function block uses Arduino-style `setup` and `loop` sections:

```iecst
{#native c setup}
self->output_value = false;
{#end_native}

{#native c loop}
if (self->set_value) self->output_value = true;
{#end_native}
```

The C backend emits `Block_setup(Block *self)` and `Block_loop(Block *self)`.
Native function code can access parameters, locals, and the generated return
variable by their IEC names. Function-block code accesses state through
`self->field_name`. A valid ST body remains in the declaration as a portable
fallback for targets without a matching native pragma.

## Adding a primitive function

Primitive functions are target-specific operations that the code generator
embeds only when they are referenced by the input program. Prefer a portable
Structured Text implementation in `src/stc/stdlib/standard-functions.st` when
the operation can be expressed in ST; use a primitive for target intrinsics or
runtime support that ST cannot provide.

To add a primitive:

1. If the function name is not already recognized as an IEC standard function,
   add it to `standard_functions` in `src/stc/frontend/lexer.py`.
2. Add an implementation to each supported target file,
   `src/stc/runtime/primitives.c` and `src/stc/runtime/primitives.rs`. Enclose
   each implementation in matching marker comments (primitive names are
   normalized to uppercase):

   ```c
   // STC_PRIMITIVE_BEGIN CLAMP MIN MAX
   #define CLAMP(lo, value, hi) (MAX((lo), MIN((value), (hi))))
   // STC_PRIMITIVE_END CLAMP
   ```

   The names after `CLAMP` on the begin marker are dependencies. The loader
   includes them recursively, while the `CORE` block is always included. Keep
   the begin and end names identical and keep the marker name equal to the
   Structured Text function name.
3. Add coverage to `tests/test_primitives.py`. Verify that requesting the new
   primitive includes its implementation and dependencies, omits unrelated
   blocks, and that generated C or Rust containing a call compiles when a
   compiler is available.
4. Run the primitive tests, followed by the complete suite:

   ```sh
   python3 -m unittest tests.test_primitives
   python3 -m unittest discover -s tests
   ```

The C generator already emits the common standard headers. If a primitive
needs additional target imports or a new shared helper, add them to the
backend preamble or to a dependency block rather than duplicating them in
every primitive.

Syntax errors include the unexpected token, line/column, source line, and a
caret:

```text
stc: syntax error: unexpected token at line 6, column 9 near IDENTIFIER('broken')
        broken := value_in;
        ^
```

## Tests

```sh
python3 -m unittest discover -s tests
```

Interesting Structured Text examples live under `tests/fixtures/`:

- `valid_ast/`: syntax that must parse to JSON AST.
- `valid_codegen/`: syntax that must also emit C and Rust.
- `invalid_semantic/`: syntax that parses but must fail semantic code generation.

For example:

```sh
python3 -m stc tests/fixtures/valid_ast/case_and_for.st -g ast
python3 -m stc tests/fixtures/valid_codegen/typed_literals.st -g c
python3 -m stc tests/fixtures/invalid_semantic/undeclared_variable.st -g c
```

## AST status

The current AST is structurally complete for every production currently present
in `IECParser`: no parser production is left as a placeholder. It is still a
dictionary-based parse tree, not yet a typed compiler IR. The next maturity step
is typed nodes with source spans, semantic symbols, and deterministic
diagnostics.

Use the parser coverage audit to track that work:

```sh
python3 tools/ast_coverage.py
python3 tools/ast_coverage.py --list
```

When an Annex B text extraction is available at `tmp/pdfs/annex_b.txt`, the
parser can also be checked against the IEC 61131-3:2003 production names:

```sh
python3 tools/parser_doc_audit.py
```

## Roadmap

1. Replace dict-based AST nodes with typed nodes carrying source spans.
2. Add deterministic diagnostics with line/column ranges and recovery tests.
3. Split parsing, semantic analysis, and backend generation into separate
   compiler phases.
4. Implement a symbol table and type checker for functions, function blocks,
   programs, arrays, structs, direct variables, and configurations.
5. Continue expanding grammar coverage for located declarations, array repeat
   initializers, positional calls, and broader standard function signatures.
6. Add a compatibility corpus with accepted and rejected IEC 61131-3 programs.
7. Add generated-code compile tests for C and Rust on CI.
8. Add a runtime/library layer for standard IEC functions and function blocks.
9. Add C++17 generation once the typed IR is stable.
10. Add ST-level tests and an interactive execution/debugging loop.

## References

- IEC 61131-3:2013, Programmable controllers, Part 3.
- [Autonomy-Logic/STruCpp](https://github.com/Autonomy-Logic/STruCpp)
- [beremiz/matiec](https://github.com/beremiz/matiec)

### Grammar diagnostics

During normal operation, the compiler hides known SLY/PLY warnings about unused
tokens and productions, unreachable symbols, and grammar conflicts. Actual
grammar construction errors remain enabled.

To enable the complete grammar audit and generate `parser.out`:

```bash
STC_PARSER_DIAGNOSTICS=1 python3 -m stc input.st -g c
```

## Clang-style diagnostics

Semantic and syntax diagnostics include the file, line, column, source code,
and a caret range:

```text
example.st:13:9: error: Cannot assign ['REAL'] to ['INT']. [incompatible-assignment]
   13 |         b_1 := 10.5;
      |         ^~~~~~~~~~~
stc: 1 error generated.
```

Color is enabled automatically on interactive terminals and can be controlled
explicitly:

```bash
python3 -m stc input.st -g c --diagnostic-color=always
python3 -m stc input.st -g c --diagnostic-color=never
```

The C generator receives the semantic context and emits `FOR` loops and `#line`
directives so C compiler diagnostics can refer back to the Structured Text
source.

## Extending semantic analysis

Semantic checks are organized under `src/stc/semantic/checks/`. Each check is a
small registered class with explicit phase and dependencies. See
[`docs/ADDING_SEMANTIC_CHECKS.md`](docs/ADDING_SEMANTIC_CHECKS.md) for a complete
example.
