import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from main import parse_source
from symbol_table import ScopeKind, StorageClass, SymbolKind, SymbolTableBuilder


class SymbolTableTests(unittest.TestCase):
    def build(self, source):
        return SymbolTableBuilder().build(parse_source(source))

    def test_builds_function_scope_and_resolves_references(self):
        ast = parse_source("""\
FUNCTION AddOne : INT
VAR_INPUT
    ValueIn : INT;
END_VAR
VAR
    temp : INT;
END_VAR
    temp := valuein + 1;
    AddOne := temp;
END_FUNCTION
""")
        table = SymbolTableBuilder().build(ast)
        function_scope = next(s for s in table.iter_scopes() if s.kind == ScopeKind.FUNCTION)

        self.assertEqual(function_scope.lookup_local("VALUEIN").storage, StorageClass.INPUT)
        self.assertEqual(function_scope.lookup_local("temp").kind, SymbolKind.VARIABLE)
        self.assertEqual(function_scope.lookup_local("addone").kind, SymbolKind.RETURN_VALUE)

        references = [
            node for node in self.nodes(ast)
            if node.get("name") == "variable_name" and table.reference_was_indexed(node)
        ]
        self.assertTrue(references)
        self.assertTrue(all(table.symbol_for_reference(node) is not None for node in references))

    def test_reports_duplicate_declarations_case_insensitively(self):
        table = self.build("""\
FUNCTION duplicate : INT
VAR_INPUT
    value : INT;
END_VAR
VAR
    VALUE : INT;
END_VAR
    duplicate := value;
END_FUNCTION
""")
        self.assertEqual(len(table.diagnostics), 1)
        self.assertEqual(table.diagnostics[0].code, "duplicate-declaration")

    def test_indexes_unresolved_reference(self):
        ast = parse_source("""\
FUNCTION bad : INT
VAR_INPUT
    value : INT;
END_VAR
    bad := missing;
END_FUNCTION
""")
        table = SymbolTableBuilder().build(ast)
        missing = next(
            node for node in self.nodes(ast)
            if node.get("name") == "variable_name" and node.get("value") == "missing"
        )
        self.assertTrue(table.reference_was_indexed(missing))
        self.assertIsNone(table.symbol_for_reference(missing))

    @classmethod
    def nodes(cls, node):
        if not isinstance(node, dict):
            return
        yield node
        for child in node.get("children", []):
            yield from cls.nodes(child)


if __name__ == "__main__":
    unittest.main()
