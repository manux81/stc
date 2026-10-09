# Data-driven generator architecture

## 1. Current architecture and responsibility map

The frontend builds an IEC AST. `SemanticAnalyzer` runs typed semantic passes
and records types, resolved calls/arguments, properties, generated overload
names, OOP hierarchies and assignments in `SemanticContext`. The C and Rust
visitors consume the AST plus that context: they lower each node into
target-neutral facts and render every target decision through a
`GeneratorEngine` backed by a validated `.gen` bundle. There is no `@builtin`
escape hatch; every emitted keyword lives in a template.

| Existing responsibility | Classification | Destination |
|---|---|---|
| parsing and IEC grammar | SEMANTIC | frontend/core |
| symbol, overload and property resolution | SEMANTIC | semantic/core |
| type compatibility and Edition checks | SEMANTIC | semantic/core |
| inheritance, override/final/abstract validation | SEMANTIC | semantic/core |
| SFC step/transition semantics and priority | SEMANTIC | semantic/core |
| IL opcode semantics and label resolution | SEMANTIC / LOWERING | IL index resolution in the adapters |
| C/Rust primitive type spelling | TARGET RENDERING | `type` mapping in `types.gen` |
| literal/operator spelling (incl. based prefixes) | TARGET RENDERING | mappings in `expressions.gen` |
| string comparison / numeric coercion selection | LOWERING | typed lowering, then templates |
| resolved conversion selection | LOWERING | Lowered IR `Cast` |
| C cast / Rust `as` syntax | TARGET RENDERING | `cast` rule |
| assignment and control-flow syntax | TARGET RENDERING | `statements.gen` |
| FOR direction and bound/step evaluation | LOWERING | Lowered IR `ForLoop` |
| call target and argument ordering | LOWERING | resolved `Call` + `parameter` joining |
| FUNCTION/FB/PROGRAM state selection | LOWERING | POU rules in `pou.gen` |
| method/property/interface resolution | SEMANTIC | semantic/core (`resolved_methods`, `resolved_properties`, `oop_assignments`) |
| virtual-dispatch variant selection (this/super/interface/variable) | LOWERING | variant rule selection in the adapters |
| C vtables/fat pointers, Rust structs/`From` impls | TARGET RENDERING | `class`, `interface`, `adapter_entry`, `dispatch_entry` rules in `oop.gen` |
| method parameter joining | TARGET RENDERING | `method_parameters` (`", "` lives in `.gen`) |
| deterministic SFC scan construction | LOWERING | adapter composes `sfc_fire`, `sfc_transition`, `sfc_elapsed`, `sfc_assign`/`sfc_set`, `sfc_stored`, `sfc_previous`, `sfc_action` |
| emitted SFC state/layout/control flow | TARGET RENDERING | `sfc.gen` |
| C `goto` vs Rust program-counter dispatcher | TARGET RENDERING | `il_jump` + `il_dispatch` + `il_instruction` + `il_next` in `il.gen` |
| IL linear vs dispatch form selection | LOWERING | semantic presence of jumps (`_il_has_jumps`) |
| file header, reference trap, section layout | TARGET RENDERING | `preamble` in `language.gen` |
| primitive dependency closure | RUNTIME (generic) | `runtime/loader.py` over backend-owned `primitives.<ext>` |
| primitive bodies and emission | RUNTIME (target) | backend `primitives.<ext>` + `runtime_primitive` template |

`codegen/c.py` and `codegen/rust.py` are now bundle-parameterized visitors:
given any valid bundle they render that backend's syntax. `compiler.py`
selects the Rust visitor only for `rust`/`.rs` bundles and otherwise uses the
C visitor shape with the active bundle, so `generators/<name>/` and
`--generator-path` backends need no Python registration.
`codegen/sfc.py` only extracts the backend-neutral SFC model (steps,
transitions, actions); `codegen/visitor.py` only dispatches AST node names.

## 2. Lowered IR contract

Lowering produces immutable typed records in `codegen/generator/ir.py`.
Phase 1 introduced `Literal`, `UnaryExpression`, `BinaryExpression`,
`Assignment`, `IfBranch`, `WhileLoop`, `RepeatLoop`. Phase 2 added `Cast`,
resolved `Call`, `ArrayAccess`, `Reference`, direction-normalized `ForLoop`,
`CaseStatement` and `Function`. Phase 3 added `PropertyGet`, `PropertySet`,
`InterfaceAssignment`, `FieldDecl`, `MethodDecl`, `ClassLayout`,
`InterfaceLayout` and extended `VirtualCall`/`Jump` with `vptr` and
`extra_arguments`. Phase 4 added `SfcChart`, `SfcTransition`, `SfcFire`,
`IlProgram`, `IlInstruction`, `IlJump` and `RuntimePrimitive`.

Conventions (documented in the schema, not in prose):

- `{arguments}` is the bare `", "`-joined list; `{extra_arguments}` carries a
  leading `", "` separator when non-empty (for calls appended to a receiver).
- `{has_base}`/`{no_base}`/`{empty}` are `"1"`/`""` semantic flags for `when`
  gating and complementary rendering.
- `NULL` never appears in lowering: null dispatch entries use the dedicated
  `dispatch_entry_null` / `adapter_entry_null` rules.
- No IR value contains braces, casts, keywords, ABI layout, `goto`, `match`,
  vtable syntax or another target-language decision.

## 3. Minimal `.gen` format

Files use the TOML grammar from Python's standard library. The generator
language adds only:

- `[section]` rules named by the Generator API;
- `template`, formatted with declared `{placeholders}`;
- `mapping`, a string-to-string lookup for types/operators/literals/prefixes;
- `each` plus optional `separator`, for a supplied list of records;
- `when = "{flag}"`, a simple truth test that renders `""` when empty;
- `uses = ["other_rule"]`, acyclic template composition;
- `description`, used for introspection. Lines beginning with `#` are internal
  backend comments; target comments belong in `template`.

Only braces containing an identifier, such as `{body}`, are placeholders.
Ordinary target-language braces are literal and need no escaping.

There are no assignments, mutable variables, user functions, arbitrary loops,
AST access, Python evaluation or builtin escape hatches. STC prepares the data;
the `.gen` files only render it.

Validation rejects malformed TOML, duplicate or unknown sections, unknown
fields/placeholders, missing required placeholders/current-phase rules,
unreachable rules, missing composition targets and composition cycles.

## 4. Complete Generator API section inventory

The executable schema in `schema.py` is authoritative and drives
`--gen-help`, validation and scaffolding:

- types/literals: `type`, `integer_literal`, `real_literal`,
  `boolean_literal`, `based_literal`, `based_prefix`;
- expressions: `operator`, `binary_expression`, `unary_expression`,
  `power_expression`;
- statements/control flow: `assignment`, `if`, `elseif`, `else`, `while`,
  `repeat`, `exit`, `continue`, `return`, `for`, `case`, `case_element_first`,
  `case_element`, `case_value`, `case_range`, `case_labels`, `case_else`,
  `case_else_first`;
- calls/data: `cast`, `call`, `parameter`, `array_type`, `array_dimension`,
  `array_access`, `array_index`, `reference_type`, `reference`, `dereference`,
  `null_reference`;
- POUs: `function`, `function_block`, `program`;
- properties: `property_get`, `property_get_class`, `property_get_interface`,
  `property_set`, `property_set_class`, `property_set_interface`,
  `property_method`, `method_return`;
- OOP: `interface_assignment`, `class`, `class_field`, `class_fields`,
  `class_predecl`, `class_base_field`, `class_vptr_field`, `class_empty_field`,
  `class_prototype`, `class_method`, `method_parameter`,
  `method_parameter_out`, `method_parameters`, `method_receiver`,
  `vtable_entry`, `dispatch_entry`, `dispatch_entry_null`, `empty_dispatch`,
  `interface`, `interface_method`, `interface_default`, `interface_impl`,
  `interface_adapter`, `adapter_entry`, `adapter_entry_null`, `class_init`,
  `class_init_statement`, `class_base_init`, `class_default`, `virtual_call`,
  `virtual_call_this`, `virtual_call_super`, `virtual_call_interface`;
- SFC: `sfc_chart`, `sfc_transition`, `sfc_fire`, `sfc_step_assign`,
  `sfc_elapsed`, `sfc_action`, `sfc_action_decl`, `sfc_assign`, `sfc_set`,
  `sfc_stored`, `sfc_previous`, `sfc_state`, `sfc_flag`;
- IL: `il_dispatch`, `il_instruction`, `il_label`, `il_assign`, `il_jump`,
  `il_return`, `il_call`, `il_guarded`, `il_next`;
- runtime/module: `runtime_primitive`, `preamble`, `global_variable`,
  `global_constant`, `configuration`.

Use `stc --gen-help` for the placeholders and `stc --gen-help SECTION` for a
single contract. This keeps the public API and its documentation synchronized.

## 5. Migration plan and present boundary

Phases 1–4 are implemented for both bundled backends: primitive types,
literals (including based literals via `based_prefix`), expressions,
statements, calls, conversions, arrays, references, `FOR`, `CASE`, POU layout,
properties, OOP dispatch/layout, SFC scans, IL lowering (linear and
dispatcher forms), runtime primitives and file headers all render through
the reference `.gen` files. Both bundles report 100% Generator API coverage
and `COMPLETE` status.

Deliberately remaining Python-side work (all documented, none structural):

- per-declarator layout (`_format_declarator`, array-bracket splitting,
  `*` vs `*mut` reference prefixes, `&mut` parameter prefixes in a few slot
  shapes) and per-type zero literals (`zero_value`): these stay inside each
  adapter next to the code that consumes them, pending dedicated layout rules
  and a shared lowering module;
- configuration scheduler signatures and section headers: `configuration`,
  `global_variable` and `global_constant` templates exist and are
  unit-tested, but the C/Rust visitors still assemble schedulers with legacy
  helpers; they are the next migration slice together with named-type
  (`typedef`/`enum`/`struct`) layout;
- extracting the now-parallel C/Rust lowering logic (SFC scan composition,
  IL threading, OOP model queries) into one shared `lowering.py` so future
  backends reuse a single generic visitor. The current visitors are already
  bundle-parameterized, so this is a mechanical extraction with no template
  changes.

There is no `@builtin` rule and it is not part of the final backend contract.
External paths and discovered `generators/NAME` directories require no Python
installation or target-name registration.

## 6. External backend example

Copy `src/stc/generators/c` outside the repository, change templates such as:

```toml
[assignment]
description = "Generate a lowered assignment as a C statement."
template = "{indent}{target} = ({value}); /* external-assign */\n"
```

Then run `stc source.st --generator-path /absolute/path/to/my-language`.
`stc --new-generator zig` creates all nine documented files without requiring
source inspection, and `stc --check-generator <dir>` reports per-category and
per-phase coverage.
