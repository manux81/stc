"""Semantic-analysis pipeline."""
from semantic_context import SemanticContext
from semantic_passes import (
    ArrayRangeCheck, CaseElementsCheck, ConstantFolder, DeclarationCheck,
    DependencyAnalysis, EnumDeclarationCheck, FillCandidateDatatypes,
    FlowControlAnalysis, ForcedNarrowCandidateDatatypes, LValueCheck,
    NarrowCandidateDatatypes, PrintDatatypesError, TypeDeclarationCollector,
)
from symbol_table import SymbolTableBuilder

class SemanticError(Exception):
    def __init__(self,diagnostics):
        self.diagnostics=diagnostics
        super().__init__('\n'.join(str(d) for d in diagnostics))

class SemanticAnalyzer:
    """Run ordered semantic passes and return their shared context.

    ``strict_types`` may be disabled while extending the language type model;
    declaration, name, lvalue, CASE and range errors remain active.
    """
    PASS_TYPES=(EnumDeclarationCheck,TypeDeclarationCollector,FlowControlAnalysis,
                ConstantFolder,DeclarationCheck,FillCandidateDatatypes,
                NarrowCandidateDatatypes,PrintDatatypesError,
                ForcedNarrowCandidateDatatypes,LValueCheck,ArrayRangeCheck,
                CaseElementsCheck,DependencyAnalysis)
    def __init__(self,strict_types=True): self.strict_types=strict_types
    def analyze(self,ast)->SemanticContext:
        context=SemanticContext(SymbolTableBuilder().build(ast))
        for pass_type in self.PASS_TYPES: pass_type(context).run(ast)
        errors=[d.message for d in context.diagnostics if d.severity=='error']
        if errors: raise SemanticError(errors)
        return context
