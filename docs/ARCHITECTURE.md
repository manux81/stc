# Compiler structure and extension guide

Start with `src/stc/compiler.py`: `compile_source()` coordinates the three
compiler stages and returns a `CompilationResult`. The public Python entry
point is `from stc import compile_source`; the command-line entry point is
`python3 -m stc`.

## The three stages

```text
IEC source → parsing → AST → analysis → AST + SemanticContext → codegen → C / Rust
                                                                   ↑
                                                               templates
```

| Stage | Directory | Responsibility | Entry point |
|---|---|---|---|
| 1. Read the source | `src/stc/parsing/` | Recognize tokens, grammar and ST/IL bodies; construct the AST | `IECLexer`, `IECParser`, `AstBuilder` |
| 2. Check the program | `src/stc/analysis/` | Resolve names, types and calls; enforce IEC rules; report errors | `SemanticAnalyzer.analyze()` |
| 3. Generate source | `src/stc/codegen/` | Lower checked operations and emit the selected target | `CCodeGenerator`, `RustCodeGenerator` |

`parsing` replaces the old `frontend` name; `analysis` replaces `semantic`.
Semantic analysis means checking the meaning of a program: a syntactically
valid expression may still refer to an undeclared variable or use incompatible
types. The class names `SemanticAnalyzer` and `SemanticContext` retain that
precise meaning.

## First-level map

```text
src/stc/
├── compiler.py          # coordinates the compilation pipeline; public API
├── cli.py               # command-line arguments, input and output
├── parsing/             # stage 1: source → AST
│   └── third_party/sly/ # bundled lexer/parser engine, formerly vendor/
├── analysis/            # stage 2: AST → checked program
│   └── checks/          # registered IEC validation passes
├── codegen/             # stage 3: checked program → target source
│   ├── c/
│   ├── rust/
│   └── common/          # shared lowering, IR and template engine
├── templates/           # editable target syntax
│   ├── c/
│   └── rust/
└── library/             # functions included in compiled programs
    ├── common/          # portable ST implementations and export manifest
    ├── c/               # native C runtime support
    └── rust/            # native Rust runtime support
```

The root support modules have specific boundaries: `libraries.py` resolves
imported ST libraries; `native.py` handles embedded native-code pragmas;
`source_map.py` tracks original source positions; `diagnostics.py` formats
compiler diagnostics. They are used by the pipeline, rather than additional
compiler stages.

At repository level, `src/` is the installable implementation, `tests/` verifies
it, `examples/` provides IEC input programs, `tools/` contains development
utilities, and `docs/` explains the architecture and supported features.
`build/`, `tmp/` and `parser.out` are output/work files, not extension points.

## Where to integrate a change

| I want to… | Start here | Also check |
|---|---|---|
| Embed the compiler in a Python application | `stc.compile_source()` | README Python compilation API |
| Run generated PLC code | Generated function/block cycle entry points | README usage and native implementation sections; the host supplies scheduling and `main()` |
| Add a token or grammar construct | `parsing/lexer.py`, `parsing/parser.py` | `parsing/ast_builder.py`, AST tests, analysis and generation for the new construct |
| Change ST/IL body detection | `parsing/languages.py` | Language/profile tests |
| Reject an invalid program | `analysis/checks/` | Register the module in `analysis/checks/__init__.py`; see [adding checks](ADDING_SEMANTIC_CHECKS.md) |
| Add a datatype or resolve a name | `analysis/types.py`, `analysis/symbol_table.py` | Type checks and target type templates |
| Change emitted C/Rust syntax | `templates/c/` or `templates/rust/` | Validate the bundle with `--check-generator` |
| Change an operation shared by C and Rust | `codegen/common/lowering.py` | Both generated-code test targets |
| Add portable IEC functions | `library/common/*.st` and `stc-library.json` | Library import and generated-code tests |
| Add native runtime support | `library/c/`, `library/rust/` | Dependency markers and `library/loader.py`; README adding primitives |
| Create an external backend based on C or Rust | `--new-generator NAME --generator-base c` (or `rust`) | [template contract](data-driven-generators.md) |
| Add a target requiring a different lowering model | `codegen/` and adapter selection in `compiler.py` | Template schema and runtime support; copying syntax templates alone does not supply a new lowering model |

A new language feature often crosses all three stages: parsing recognizes it,
analysis checks it, and codegen translates it. A formatting change normally
belongs only in templates. A portable library algorithm normally belongs only
in ST library sources and the export manifest.

## Bundled parser dependency

`parsing/third_party/sly/lex.py` and `yacc.py` are the SLY engine by David M.
Beazley. Their original license headers are preserved. STC's IEC grammar is in
`parsing/parser.py`, and its tokens are in `parsing/lexer.py`. Add IEC language
features there; changes to SLY itself are dependency maintenance.
