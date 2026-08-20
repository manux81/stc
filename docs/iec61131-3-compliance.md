# IEC 61131-3 compliance statement

STC implements a documented subset of IEC 61131-3. The default language
profile is Edition 3 (2013); Edition 4 features are enabled explicitly with
`-s ed4`.

Status values used below:

- **Supported**: parsed, checked, generated, and covered by target tests.
- **Partial**: the listed subset is implemented; unlisted forms are not yet
  claimed as conforming.
- **Diagnostic only**: recognized to provide an edition or deprecation
  diagnostic, but not generated as an executable operation.

## Edition 3 feature tables

| IEC feature | Status | STC implementation notes |
| --- | --- | --- |
| Table 5 - Numeric literals | Supported | Binary, octal, decimal, hexadecimal, real, Boolean, and typed numeric literals. Octal literals produce the Edition 3 deprecation warning. |
| Table 6 - Character string literals | Supported | Untyped and typed `STRING`, `WSTRING`, `CHAR`, and `WCHAR` forms, including hexadecimal character escapes. |
| Table 10 - Elementary data types | Partial | Integer, real, bit-string, character, string, time, long-time, and date families are accepted. Long date/time literal coverage remains incomplete. |
| Table 22 - Data type conversion functions | Partial | Typed `_TO_` conversions and typed truncation spellings are recognized. Executable target support is currently limited to the conversions emitted by the primitive runtime or the ST standard library. Old `TRUNC` produces the Edition 3 deprecation warning. |
| Tables 23-27 - Conversion matrices | Partial | Core numeric conversions, BCD helpers, bit-string-to-Boolean conversions, and selected character conversions are implemented. The complete matrix is not yet claimed. |
| Tables 28-33 - Numerical, arithmetic, bit, selection, comparison | Partial | Common arithmetic, comparison, selection, and mathematical operations are generated. Extensible arity and every generic overload are not yet claimed. |
| Table 34 - Character string functions | Partial | C primitives implement `LEN`, `LEFT`, `RIGHT`, `MID`, two-input `CONCAT`, `INSERT`, `DELETE`, and `REPLACE`; `FIND` is implemented in portable ST. Rust currently provides `LEN` and `MID`; the allocating string operations await the owned-string ABI. |

## Edition 4 extensions

The Edition 4 profile currently adds `USTRING`, `UCHAR`, Unicode `${HEX}`
literals, `LEN_CODE_UNIT`, `ASSERT`, and selected new
numeric/character conversions. Octal literals and old untyped `TRUNC` are
rejected in this profile; BCD operations produce a deprecation warning.

Properties, `LEN_MAX`, string/byte-array conversion, mutexes, and semaphores
are not yet claimed as implemented.

## Target primitive boundary

Portable algorithms are defined in `src/stc/stdlib/standard-functions.st`. Operations
that depend on target string or machine representation are declared as compiler
intrinsics and implemented in:

- `src/stc/runtime/primitives.c`
- `src/stc/runtime/primitives.rs`

Generated files embed only referenced primitives and their declared
dependencies. The Python generators contain lowering logic, not runtime
function bodies.
