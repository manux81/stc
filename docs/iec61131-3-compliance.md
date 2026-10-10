# IEC 61131-3 compliance statement

STC implements a documented subset of IEC 61131-3. The default language
profile is Edition 3 (2013); Edition 4 features are enabled explicitly with
`-s ed4`, and the legacy Edition 2 profile with `-s ed2`.

Status values used below:

- **Supported**: parsed, checked, generated, and covered by target tests.
- **Partial**: the listed subset is implemented; unlisted forms are not yet
  claimed as conforming.
- **Diagnostic only**: recognized to provide an edition or deprecation
  diagnostic, but not generated as an executable operation.

## Edition 2 Instruction List

Instruction List bodies are parsed as line-oriented IEC text and lowered by
both single-file backends (`codegen/c.py` and `codegen/rust.py`). The supported
subset covers load/store, Boolean and arithmetic operations, comparisons,
set/reset, functions, returns, labels, and conditional/unconditional jumps.
Rust lowers jumps through a program-counter dispatcher because Rust has no
native `goto`. Parenthesized IL networks and every formal function-block call
form are not yet claimed as conforming.

The Edition 3 profile accepts the same subset with an IL deprecation warning.
The Edition 4 profile rejects IL before code generation.

## Edition 3 feature tables

| IEC feature | Status | STC implementation notes |
| --- | --- | --- |
| Table 5 - Numeric literals | Supported | Binary, octal, decimal, hexadecimal, real, Boolean, and typed numeric literals. Octal literals produce the Edition 3 deprecation warning. |
| Table 6 - Character string literals | Supported | Untyped and typed `STRING`, `WSTRING`, `CHAR`, and `WCHAR` forms, including hexadecimal character escapes. |
| Table 10 - Elementary data types | Partial | Integer, real, bit-string, character, string, time, long-time, and date families are accepted. Long date/time literal coverage remains incomplete. |
| Table 12 - Reference operations | Supported | `REF_TO` declarations and named reference types, `REF(variable)`, `NULL`, reference assignment, and explicit `^` dereferencing are checked and lowered by the C and Rust backends. References are rejected by the Edition 2 profile and accepted by Edition 3 and Edition 4. References to function-local/temporary variables and `VAR_IN_OUT` reference declarations are diagnosed. |
| Table 22 - Data type conversion functions | Partial | Typed `_TO_` conversions and typed truncation spellings are recognized. Executable target support is currently limited to the conversions emitted by the primitive runtime or the ST standard library. Old `TRUNC` produces the Edition 3 deprecation warning. |
| Tables 23-27 - Conversion matrices | Partial | Core numeric conversions, BCD helpers, bit-string-to-Boolean conversions, and selected character conversions are implemented. The complete matrix is not yet claimed. |
| Tables 28-33 - Numerical, arithmetic, bit, selection, comparison | Partial | Common arithmetic, comparison, selection, and mathematical operations are generated. Extensible arity and every generic overload are not yet claimed. |
| Table 34 - Character string functions | Partial | C primitives implement `LEN`, `LEN_CODE_UNIT`, `LEFT`, `RIGHT`, `MID`, two-input `CONCAT`, `INSERT`, `DELETE`, and `REPLACE`; `FIND` is implemented in portable ST. Rust implements the same set on the borrowed `&'static str` ABI (`CONCAT`/`INSERT`/`DELETE`/`REPLACE` via leaked owned buffers); the owned-`String` ABI remains future work. |
| Table 48 - Object-oriented programming | Partial | Edition 3/4 profiles parse, check, and lower `CLASS`, `INTERFACE`, `METHOD`, `EXTENDS`, `IMPLEMENTS`, `ABSTRACT`, `FINAL`, `OVERRIDE`, access modifiers, `THIS`, and `SUPER`. Edition 4 adds typed `PROPERTY_GET` and `PROPERTY_SET` accessors to function blocks, classes, and interfaces, including read-only/write-only diagnostics and interface dispatch. C uses embedded base objects, vtables, and interface fat pointers; Rust uses embedded base objects and generated interface adapters. Inheritance, interface/property dispatch, abstract/interface completeness, accessor type agreement, and invalid final overrides are covered by target-compilation tests. Complete access-control enforcement is not yet implemented. |

## Sequential Function Charts

Textual SFC is supported in the Edition 2, Edition 3, and Edition 4 profiles
for programs and function blocks. The implemented subset includes multiple
networks, simple and simultaneous step branches, named/prioritized
transitions with ST conditions, textual actions, indicators, and the standard
`N`, `R`, `S`, `P`, `P0`, `P1`, `L`, `D`, `SD`, `DS`, and `SL` action
qualifiers. Both backends retain step activation, previous-scan activation,
elapsed time, and stored-action state in the generated POU instance.

Direct calls to a generated POU count one millisecond per invocation for timed
qualifiers. Graphical transition conditions (FBD and LD), macro steps, and
online-change state migration are not currently claimed as supported.

## Edition 4 extensions

The Edition 4 profile currently adds `USTRING`, `UCHAR`, Unicode `${HEX}`
literals, `LEN_MAX`, `LEN_CODE_UNIT`, `ASSERT`, typed `PROPERTY_GET`/`PROPERTY_SET`
accessors, and selected new numeric/character conversions. Octal literals and
old untyped `TRUNC` are rejected in this profile; BCD operations produce a
deprecation warning.

String/byte-array conversions are implemented for the six Edition 4 names
(`STRING`/`WSTRING`/`USTRING` `_TO_ARRAY_OF_BYTE` and `ARRAY_OF_BYTE_TO_`
`STRING`/`WSTRING`/`USTRING`) as checked intrinsics; see
`docs/byte-array-conversions.md` for the encoding contract and ABI limits.
Mutexes and semaphores are not yet claimed as implemented.

## Target primitive boundary

Portable algorithms are defined in `src/stc/stdlib/standard-functions.st`. Operations
that depend on target string or machine representation are declared as compiler
intrinsics and implemented in:

- `src/stc/runtime/primitives.c`
- `src/stc/runtime/primitives.rs`

Generated files embed only referenced primitives and their declared
dependencies. The Python generators contain lowering logic, not runtime
function bodies.
