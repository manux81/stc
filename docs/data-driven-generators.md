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
| parsing and IEC grammar | SEMANTIC | parsing/ |
| symbol, overload and property resolution | SEMANTIC | analysis/ |
| type compatibility and Edition checks | SEMANTIC | analysis/ |
| inheritance, override/final/abstract validation | SEMANTIC | analysis/ |
| SFC step/transition semantics and priority | SEMANTIC | analysis/ |
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
| method/property/interface resolution | SEMANTIC | analysis/ (`resolved_methods`, `resolved_properties`, `oop_assignments`) |
| virtual-dispatch variant selection (this/super/interface/variable) | LOWERING | variant rule selection in the adapters |
| C vtables/fat pointers, Rust structs/`From` impls | TARGET RENDERING | `class`, `interface`, `adapter_entry`, `dispatch_entry` rules in `oop.gen` |
| method parameter joining | TARGET RENDERING | `method_parameters` (`", "` lives in `.gen`) |
| deterministic SFC scan construction | LOWERING | adapter composes `sfc_fire`, `sfc_transition`, `sfc_elapsed`, `sfc_assign`/`sfc_set`, `sfc_stored`, `sfc_previous`, `sfc_action` |
| emitted SFC state/layout/control flow | TARGET RENDERING | `sfc.gen` |
| C `goto` vs Rust program-counter dispatcher | TARGET RENDERING | `il_jump` + `il_dispatch` + `il_instruction` + `il_next` in `il.gen` |
| IL linear vs dispatch form selection | LOWERING | semantic presence of jumps (`_il_has_jumps`) |
| file header, reference trap, section layout | TARGET RENDERING | `preamble` in `language.gen` |
| primitive dependency closure | RUNTIME (generic) | `library/loader.py` over backend-owned `primitives.<ext>` |
| primitive bodies and emission | RUNTIME (target) | backend `primitives.<ext>` + `runtime_primitive` template |

`codegen/c/generator.py` and `codegen/rust/generator.py` are now bundle-parameterized visitors:
given any valid bundle they render that backend's syntax. `compiler.py`
selects the reference visitor from explicit `adapter = "c"` / `"rust"` metadata
(with extension-based fallback for older bundles), so `templates/<name>/` and
`--generator-path` backends need no Python registration.
`codegen/common/sfc.py` only extracts the backend-neutral SFC model (steps,
transitions, actions); `codegen/common/visitor.py` only dispatches AST node names.

## 2. Lowered IR contract

Lowering produces immutable typed records in `codegen/common/ir.py`.
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

## 5. Extended layout API and shared lowering

Phase 5 adds executable rules for `type_alias`, `enum_type`, `enum_value`,
`enum_default_marker`, `structure_type`, `structure_field`, `string_type`,
`reference_inline`, scalar/pointer/array declarators, local variables, persistent
state fields, zero values, and section headers. The schema and `--gen-help`
remain authoritative for their placeholders.

Configuration generation now uses the shared `SharedLowering` implementation.
Its `scheduler_*` rules render program instances, task state/defaults, cold and
warm initialization, due-time calculations, timer advancement, firing, and the
scheduler loop. Priority ordering and retention decisions remain semantic data.
Both C and Rust render cyclic and SINGLE task handling through the same model.
`global_variable` / `global_constant` render configuration globals.

`codegen/common/lowering.py` also owns the deterministic SFC scan, common IL operand,
opcode and label algorithms, AST/declaration traversal helpers, and `OopModel`
hierarchy queries. OOP interface ancestry is collected recursively.

New generators are runnable copies of a reference bundle, including runtime
primitives. `stc --new-generator NAME` starts from C;
`stc --new-generator NAME --generator-base rust` starts from Rust. The command
preserves existing directories by failing when the destination already exists.
The copied language metadata records the adapter explicitly, so changing the
backend name does not change lowering conventions.

This extension changes the complete Generator API: external bundles must add
the phase-5 sections. Generate a fresh reference copy and port customizations;
`--check-generator` diagnoses missing sections and reports phase-5 coverage.

The renderer deliberately remains a declarative template engine. There are no
Python callbacks, AST access or arbitrary executable rules. The current adapters
still own ABI choices and some expression/initialization glue, while `layout_patterns` in each bundle declares the type shapes used by shared
declarator/default-value selection. Invalid patterns are rejected during loading. An entirely
different runtime or ABI still needs a new lowering adapter. API coverage does
not establish complete IEC language support or prove generated target code valid;
the generated-code compile and execution tests provide that separate check.

## 6. External backend example

Copy `src/stc/templates/c` outside the repository, change templates such as:

```toml
[assignment]
description = "Generate a lowered assignment as a C statement."
template = "{indent}{target} = ({value}); /* external-assign */\n"
```

Then run `stc source.st --generator-path /absolute/path/to/my-language`.
`stc --new-generator zig` creates all nine populated files and a runtime
primitive source, and `stc --check-generator <dir>` reports per-category and
per-phase coverage.
