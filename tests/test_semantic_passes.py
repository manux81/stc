import sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from compiler import parse_source
from semantic import SemanticAnalyzer,SemanticError
from semantic_context import SemanticContext
from semantic_passes import ConstantFolder,CaseElementsCheck,topological_declaration_order
from symbol_table import SymbolTableBuilder

def test_constant_folding_and_duplicate_case_label():
    ast=parse_source('''FUNCTION f : INT\nVAR_INPUT x : INT; END_VAR\nCASE x OF 1: f:=1; 1: f:=2; END_CASE;\nEND_FUNCTION\n''')
    ctx=SemanticContext(SymbolTableBuilder().build(ast)); ConstantFolder(ctx).run(ast); CaseElementsCheck(ctx).run(ast)
    assert any(d.code=='overlapping-case-elements' for d in ctx.diagnostics)

def test_lvalue_indexes_assignment_target():
    ast=parse_source('''FUNCTION f : INT\nVAR_INPUT x : INT; END_VAR\nf := x;\nEND_FUNCTION\n''')
    context=SemanticAnalyzer().analyze(ast)
    assignments=[n for n in _nodes(ast) if n.get("name")=="assignment_statement"]
    assert context.lvalues[id(assignments[0]["children"][0])]

def _nodes(node):
    if not isinstance(node,dict): return
    yield node
    for child in node.get("children",[]): yield from _nodes(child)

def test_valid_program_returns_context():
    ast=parse_source('''FUNCTION f : INT\nVAR_INPUT x : INT; END_VAR\nf := x + 1;\nEND_FUNCTION\n''')
    context=SemanticAnalyzer().analyze(ast)
    assert context.symbols.lookup('f') is not None

def test_topological_order():
    ast={'name':'library','children':[]}; ctx=SemanticContext(SymbolTableBuilder().build(ast))
    ctx.dependencies={'matrix':{'row'},'row':set()}
    assert topological_declaration_order(ctx)==['row','matrix']


def test_real_literal_cannot_be_assigned_to_int():
    source = '''
FUNCTION inter : INT
VAR
    value : INT;
END_VAR
    value := 10.5;
    inter := value;
END_FUNCTION
'''
    ast = parse_source(source)
    with pytest.raises(SemanticError, match='Cannot assign'):
        SemanticAnalyzer().analyze(ast)


def test_underscored_integer_literal_is_valid():
    source = '''
FUNCTION inter : INT
VAR
    value : INT;
END_VAR
    value := 70_9;
    inter := value;
END_FUNCTION
'''
    ast = parse_source(source)
    SemanticAnalyzer().analyze(ast)
