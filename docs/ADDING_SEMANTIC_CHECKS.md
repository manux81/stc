# Adding a semantic check

Each rule lives in one small class under `src/semantic_checks/`. A check does not
modify the AST: it reads shared information from `SemanticContext` and emits
errors with `self.error(...)`.

## Minimal example

Create `src/semantic_checks/boolean_conditions.py`:

```python
from semantic_types import BOOL
from .base import SemanticCheck, SemanticPhase, direct_children, register_check


@register_check(
    name="boolean-conditions",
    phase=SemanticPhase.VALIDATION,
    after=("narrow-candidate-types",),
)
class BooleanConditionsCheck(SemanticCheck):
    def visit_if_statement(self, node):
        condition = direct_children(node)[0]
        condition_type = self.context.type_of(condition)
        if condition_type != BOOL:
            self.error(
                "non-boolean-condition",
                "IF condition must have type BOOL.",
                condition,
            )
        self.generic_visit(node)
```

Then import the module in `src/semantic_checks/__init__.py` so its decorator runs:

```python
from .boolean_conditions import BooleanConditionsCheck
```

No change to `SemanticAnalyzer` or `main.py` is needed.

## Available context

- `context.symbols`: symbol table and resolved references.
- `context.declared_types`: declared and built-in types.
- `context.candidates(node)`: candidate datatypes.
- `context.type_of(node)`: selected datatype.
- `context.constant_of(node)`: compile-time constant value.
- `context.source_map`: source positions used by Clang-style diagnostics.

## Traversal helpers

- Implement `visit_<node-name>()` for node-specific logic.
- Call `self.generic_visit(node)` to continue into children.
- Use `walk(node)` for a complete subtree traversal.
- Use `direct_children(node)` when grammar wrappers matter.
- Use `descendants(node, "node_name")` for filtered traversal.

## Testing a check independently

```python
context = SemanticContext(SymbolTableBuilder().build(ast))
BooleanConditionsCheck(context).run(ast)
assert context.diagnostics[0].code == "non-boolean-condition"
```
