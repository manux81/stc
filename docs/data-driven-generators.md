# Data-driven generator architecture

## Current architecture and responsibility map

The frontend builds an IEC AST. `SemanticAnalyzer` runs typed semantic passes
and records types, resolved calls/arguments, properties, generated overload
names, OOP hierarchies and assignments in `SemanticContext`. The two visitors
then consume both the AST and that context, but they also perform additional
lowering while directly appending target text.

| Existing responsibility | Classification | Destination |
|---|---|---|
| parsing and IEC grammar | SEMANTIC | frontend/core |
| symbol, overload and property resolution | SEMANTIC | semantic/core |
| type compatibility and Edition checks | SEMANTIC | semantic/core |
| C/Rust primitive type spelling | TARGET RENDERING | `types.gen` |
| literal/operator spelling | TARGET RENDERING | `expressions.gen` |
| selecting string comparison or numeric coercion | MIXED / NEEDS REFACTORING | typed lowering, then templates |
| resolved conversion selection | LOWERING | Lowered IR `Cast` |
| C cast / Rust `as` syntax | TARGET RENDERING | conversion rules |
| C/Rust assignment and control-flow syntax | TARGET RENDERING | `statements.gen` |
| FOR direction and bound/step evaluation | LOWERING | Lowered IR `ForLoop` |
| call target and argument ordering | LOWERING | resolved call IR |
| FUNCTION/FB/PROGRAM state selection | LOWERING | POU IR |
| C structs/functions and Rust structs/impls | TARGET RENDERING | `pou.gen` |
| inheritance, override/final/abstract validation | SEMANTIC | semantic/core |
| virtual dispatch selection | LOWERING | `VirtualCall` |
| C vtables/fat pointers and Rust dispatch representation | TARGET RENDERING | `oop.gen` |
| SFC step/transition semantics and priority | SEMANTIC | semantic/core |
| deterministic SFC scan construction | LOWERING | SFC IR |
| emitted SFC state/layout/control flow | TARGET RENDERING | `sfc.gen` |
| IL opcode semantics and label resolution | SEMANTIC / LOWERING | IL CFG IR |
| C `goto` and Rust program-counter dispatch | TARGET RENDERING | `il.gen` |
| primitive dependency closure | RUNTIME (generic) | core resolver |
| primitive ABI, declaration and implementation | RUNTIME (target) | `runtime.gen` and backend sources |

In particular, `c.py` contains the C prologue, type/declarator layout, C OOP
emission, runtime selection, expression coercion, every POU representation,
SFC scans, IL lowering and configuration scheduling. `rust.py` has the same
categories plus Rust-specific ownership/casts, formatting and its IL
program-counter strategy. `sfc.py` currently extracts a partially lowered SFC
model, while `visitor.py` only dispatches raw AST node names.

## Lowered IR contract

Lowering produces immutable typed records. Phase 1 introduced concrete
`Literal`, `UnaryExpression`, `BinaryExpression`, `Assignment`, `IfBranch`,
`WhileLoop` and `RepeatLoop` records. Phase 2 added `Cast`, resolved `Call`,
`ArrayAccess`, `Reference`, direction-normalized `ForLoop`, `CaseStatement`
and `Function`. Contracts for later passes include resolved `VirtualCall` and
label/index-resolved `Jump`.

The completed IR will have these families:

- module and declarations: module, type, global, FUNCTION, FUNCTION_BLOCK,
  PROGRAM and configuration;
- typed values: literal, variable/lvalue, field, array access, unary, binary,
  cast, direct call, virtual call, reference and dereference;
- statements: assignment, call, branch, loop, case, return, exit and continue;
- target-neutral data layout facts: fields, inheritance and interface method
  slots, never a C struct or Rust impl;
- SFC: persistent state fields, ordered transitions and normalized action
  activation operations;
- IL: basic blocks, resolved labels/indexes, accumulator operations and
  conditional/unconditional terminators;
- runtime requests: primitive name, dependencies and semantic signature.

No IR value may contain braces, casts, keywords, ABI layout, `goto`, `match`,
vtable syntax or another target-language decision.

## Minimal `.gen` format

Files use the TOML grammar already available in Python's standard library.
The generator language adds only:

- `[section]` rules named by the Generator API;
- `template`, formatted with declared `{placeholders}`;
- `mapping`, a string-to-string lookup for types/operators/literals;
- `each` plus optional `separator`, for a supplied list of records;
- `when = "{flag}"`, a simple truth test;
- `uses = ["other_rule"]`, acyclic template composition;
- `description`, used for introspection. Lines beginning with `#` are internal
  backend comments; target comments belong in `template`.

Only braces containing an identifier, such as `{body}`, are placeholders.
Ordinary target-language braces are literal and need no escaping.

There are no assignments, mutable variables, user functions, arbitrary loops,
AST access, Python evaluation or builtin escape hatches. STC prepares the data;
the `.gen` files only render it.

Validation rejects malformed TOML, duplicate or unknown sections, unknown
fields/placeholders, missing required placeholders/current-phase rules, unreachable
rules, missing composition targets and composition cycles.

## Complete Generator API section inventory

The executable schema in `schema.py` is authoritative and drives
`--gen-help`, validation and scaffolding. Its current full inventory is:

- types/literals/expressions: `type`, `integer_literal`, `real_literal`,
  `boolean_literal`, `based_literal`, `operator`, `binary_expression`,
  `unary_expression`;
- statements/control flow: `assignment`, `if`, `elseif`, `else`, `while`,
  `repeat`, `exit`, `continue`, `return`, `for`, `case`, `case_element`;
- calls/data: `cast`, `call`, `parameter`, `array_type`, `array_access`,
  `reference_type`, `reference`, `dereference`;
- POUs: `function`, `function_block`, `program`;
- properties/OOP: `property_get`, `property_set`, `class`, `interface`,
  `virtual_call`;
- SFC/IL/runtime: `sfc_chart`, `sfc_transition`, `il_dispatch`, `il_jump`,
  `runtime_primitive`.

Use `stc --gen-help` for the placeholders and `stc --gen-help SECTION` for a
single contract. This keeps the public API and its documentation synchronized.

## Migration plan and present boundary

Phases 1 and 2 are implemented for both bundled backends. The C and Rust
visitors adapt analyzed AST nodes into lowered records and render primitive
types, literals, expressions, statements, resolved calls and conversions,
arrays, references, FOR, CASE, and POU layout through their reference `.gen`
files. The existing visitors remain explicitly transitional adapters for
everything in Phases 3 and 4; there is no `@builtin` rule and it is not part of
the final backend contract. External paths and discovered `generators/NAME`
directories require no Python installation or target-name registration.

Phase 3 will move property and
OOP dispatch/layout. Phase 4 will replace `sfc.py`, visitor IL lowering and
`runtime/loader.py` target branches with lowered SFC/IL records and generic
runtime dependency resolution over backend-provided sources. At that point the
legacy C/Rust visitors can be removed and a wholly new target will be external.

## External backend example

Copy `src/stc/generators/c` outside the repository, change templates such as:

```toml
[assignment]
template = "{indent}SET {target} TO {value};\n"
```

Then run `stc source.st --generator-path /absolute/path/to/my-language`.
During the current migration, Phase 3/4 constructs still use the legacy C
adapter, so such a backend is a demonstrator rather than a complete new
language. `stc --new-generator zig` creates all nine documented files without
requiring source inspection.
