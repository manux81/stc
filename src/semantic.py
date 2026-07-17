from symbol_table import SymbolTable, SymbolTableBuilder


class SemanticError(Exception):
    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__("\n".join(diagnostics))


class SemanticAnalyzer:
    """Run declaration and name-resolution checks over an indexed symbol table."""

    def analyze(self, ast) -> SymbolTable:
        table = SymbolTableBuilder().build(ast)
        diagnostics = [diagnostic.message for diagnostic in table.diagnostics]

        for node_id, symbol in table._references.items():
            if symbol is not None:
                continue
            node = table._reference_nodes.get(node_id)
            if node is None:
                continue
            scope = table.scope_for(node)
            owner = scope.name if scope is not None else "<library>"
            diagnostics.append(
                f"Undeclared variable '{node.get('value')}' in scope '{owner}'."
            )

        if diagnostics:
            raise SemanticError(diagnostics)
        return table

