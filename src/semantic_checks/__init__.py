# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Export semantic-check APIs and register built-in checks."""
from .base import (
    SemanticCheck,
    SemanticPhase,
    children,
    descendants,
    direct_children,
    register_check,
    registered_checks,
    walk,
)
from .declarations import DeclarationCheck, EnumDeclarationCheck, TypeDeclarationCollector
from .constants import ConstantFolder
from .types import (
    FillCandidateDatatypes,
    ForcedNarrowCandidateDatatypes,
    NarrowCandidateDatatypes,
    PrintDatatypesError,
)
from .validation import ArrayRangeCheck, CaseElementsCheck, FlowControlAnalysis, LValueCheck
from .dependencies import DependencyAnalysis, topological_declaration_order
from .pipeline import SemanticPipeline

__all__ = [
    "SemanticCheck",
    "SemanticPhase",
    "SemanticPipeline",
    "register_check",
    "registered_checks",
    "walk",
    "children",
    "direct_children",
    "descendants",
    "EnumDeclarationCheck",
    "TypeDeclarationCollector",
    "FlowControlAnalysis",
    "ConstantFolder",
    "DeclarationCheck",
    "FillCandidateDatatypes",
    "NarrowCandidateDatatypes",
    "PrintDatatypesError",
    "ForcedNarrowCandidateDatatypes",
    "LValueCheck",
    "ArrayRangeCheck",
    "CaseElementsCheck",
    "DependencyAnalysis",
    "topological_declaration_order",
]
