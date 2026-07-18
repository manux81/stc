"""Shared state for all semantic passes."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any
from semantic_types import ConstantValue, DataType
from symbol_table import SymbolTable
from source_map import SourceMap
AstNode=dict[str,Any]

@dataclass(frozen=True,slots=True)
class Diagnostic:
    code:str; message:str; node:AstNode; severity:str='error'

@dataclass(slots=True)
class SemanticContext:
    symbols:SymbolTable
    declared_types:dict[str,DataType]=field(default_factory=dict)
    node_types:dict[int,DataType]=field(default_factory=dict)
    candidate_types:dict[int,set[DataType]]=field(default_factory=dict)
    constants:dict[int,ConstantValue]=field(default_factory=dict)
    lvalues:dict[int,bool]=field(default_factory=dict)
    dependencies:dict[str,set[str]]=field(default_factory=dict)
    declaration_order:list[str]=field(default_factory=list)
    reachable_nodes:set[int]=field(default_factory=set)
    diagnostics:list[Diagnostic]=field(default_factory=list)
    source_map:SourceMap|None=None
    def error(self,code,message,node): self.diagnostics.append(Diagnostic(code,message,node))
    def warning(self,code,message,node): self.diagnostics.append(Diagnostic(code,message,node,'warning'))
    def type_of(self,node): return self.node_types.get(id(node))
    def set_type(self,node,t): self.node_types[id(node)]=t
    def candidates(self,node): return self.candidate_types.get(id(node),set())
    def constant_of(self,node): return self.constants.get(id(node))
