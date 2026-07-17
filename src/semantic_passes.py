"""Composable semantic passes for the IEC 61131-3 AST.

The visitors intentionally use side tables in SemanticContext instead of mutating
AST nodes. Passes can therefore be rerun, inspected and unit-tested independently.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Iterator
from semantic_context import SemanticContext
from semantic_types import *
from symbol_table import StorageClass, SymbolKind, normalize_identifier
AstNode=dict[str,Any]

class SemanticPass:
    def __init__(self,context:SemanticContext): self.context=context
    def run(self,ast:AstNode): self.visit(ast); return self.context
    def visit(self,node):
        if not isinstance(node,dict): return
        getattr(self,'visit_'+node.get('name',''),self.generic_visit)(node)
    def generic_visit(self,node):
        for child in node.get('children',[]): self.visit(child)
    @staticmethod
    def nodes(node)->Iterator[AstNode]:
        if not isinstance(node,dict): return
        yield node
        for child in node.get('children',[]): yield from SemanticPass.nodes(child)
    @staticmethod
    def descendants(node,name): return (n for n in SemanticPass.nodes(node) if n.get('name')==name)

class EnumDeclarationCheck(SemanticPass):
    def run(self,ast):
        for decl in self.nodes(ast):
            if decl.get('name') not in {'enumerated_type_declaration','enumerated_spec_init'}: continue
            values=[n for n in self.nodes(decl) if n.get('name')=='enumerated_value' and isinstance(n.get('value'),str)]
            seen={}
            for value in values:
                key=normalize_identifier(value['value'])
                if key in seen: self.context.error('duplicate-enum-element',f"Duplicate enum element '{value['value']}'.",value)
                seen[key]=value
        return self.context

class TypeDeclarationCollector(SemanticPass):
    def run(self,ast):
        self.context.declared_types.update(BUILTIN_TYPES)
        # The grammar exposes declared type names through simple_type_name and derived_type_name.
        for node in self.nodes(ast):
            if node.get('name') not in {'simple_type_declaration','array_type_declaration','structure_type_declaration','enumerated_type_declaration'}: continue
            name_node=next((n for n in self.nodes(node) if n is not node and n.get('name') in {'simple_type_name','derived_type_name','array_type_name','structure_type_name'} and isinstance(n.get('value'),str)),None)
            if name_node:
                key=normalize_identifier(name_node['value'])
                self.context.declared_types.setdefault(key,DataType(name_node['value'],TypeCategory.UNKNOWN))
                self.context.declaration_order.append(key)
        for symbol in self.context.symbols.iter_symbols():
            if symbol.type_ref:
                symbol.attributes['datatype']=self.context.declared_types.get(normalize_identifier(symbol.type_ref.name or ''),UNKNOWN_TYPE)
        return self.context

class FlowControlAnalysis(SemanticPass):
    def run(self,ast):
        # Conservative reachability: all nodes are reachable except statements after an
        # unconditional RETURN in the same statement list.
        for node in self.nodes(ast): self.context.reachable_nodes.add(id(node))
        for stmt_list in (n for n in self.nodes(ast) if n.get('name')=='statement_list'):
            terminated=False
            for stmt in [c for c in stmt_list.get('children',[]) if isinstance(c,dict)]:
                if terminated:
                    self.context.reachable_nodes.discard(id(stmt)); self.context.warning('unreachable-code','Unreachable statement.',stmt)
                if any(n.get('name')=='return_statement' for n in self.nodes(stmt)): terminated=True
        return self.context

class ConstantFolder(SemanticPass):
    INT_NODES={'integer','signed_integer','binary_integer','octal_integer','hex_integer'}
    def generic_visit(self,node):
        super().generic_visit(node)
        children=[c for c in node.get('children',[]) if isinstance(c,dict)]
        if len(children)==1 and self.context.constant_of(children[0]) is not None:
            self.context.constants[id(node)]=self.context.constant_of(children[0])
        self._fold_expression(node,children)
    def visit_integer(self,node): self._literal(node,10)
    def visit_integer_literal(self,node):
        self._literal(node,10)
        declared=next((n.get('value') for n in self.nodes(node) if n.get('name') in {'signed_integer_type_name','unsigned_integer_type_name'} and isinstance(n.get('value'),str)),None)
        if declared and normalize_identifier(declared) in BUILTIN_TYPES:
            datatype=BUILTIN_TYPES[normalize_identifier(declared)]
            current=self.context.constant_of(node)
            if current is not None:
                self.context.constants[id(node)]=ConstantValue(datatype,current.value)
                self.context.candidate_types[id(node)]={datatype}
    def visit_signed_integer(self,node): self._literal(node,10)
    def visit_binary_integer(self,node): self._literal(node,2)
    def visit_octal_integer(self,node): self._literal(node,8)
    def visit_hex_integer(self,node): self._literal(node,16)
    def visit_real_literal(self,node):
        try:
            raw=str(node.get('value')).replace('_','')
            if '#' in raw: raw=raw.split('#',1)[1]
            value=float(raw)
        except (ValueError,TypeError):
            return
        # Untyped IEC real literals may be REAL or LREAL until context narrows them.
        self.context.constants[id(node)]=ConstantValue(REAL,value)
        self.context.candidate_types[id(node)]={REAL,LREAL}
    def visit_boolean_literal(self,node):
        raw=str(node.get('value')).casefold()
        if raw not in {'true','false','0','1'}:
            return
        value=raw in {'true','1'}
        self.context.constants[id(node)]=ConstantValue(BOOL,value)
        self.context.candidate_types[id(node)]={BOOL}
    def _literal(self,node,base):
        try:
            raw=str(node.get('value')).replace('_','')
            if '#' in raw: raw=raw.split('#',1)[1]
            value=int(raw,base)
        except (ValueError,TypeError): return
        candidates={t for t in INTEGER_TYPES if value_fits(value,t)}
        datatype=min(candidates,key=lambda t:t.bits or 999) if candidates else LINT
        self.context.constants[id(node)]=ConstantValue(datatype,value)
        self.context.candidate_types[id(node)]=candidates or {LINT}
    def _fold_expression(self,node,children):
        ops=[c.get('value') for c in children if c.get('name','').endswith('_operator') or c.get('name') in {'comparison_operator'}]
        values=[self.context.constant_of(c) for c in children if self.context.constant_of(c) is not None]
        if len(values)!=2 or not ops:return
        a,b=values; op=str(ops[0]).upper()
        try:
            result={'+':lambda:a.value+b.value,'-':lambda:a.value-b.value,'*':lambda:a.value*b.value,'/':lambda:a.value/b.value,
                    'MOD':lambda:a.value%b.value,'=':lambda:a.value==b.value,'<>':lambda:a.value!=b.value,
                    '<':lambda:a.value<b.value,'>':lambda:a.value>b.value,'<=':lambda:a.value<=b.value,'>=':lambda:a.value>=b.value}.get(op)
            if result:
                value=result(); self.context.constants[id(node)]=ConstantValue(BOOL if isinstance(value,bool) else a.datatype,value)
        except (ArithmeticError,ValueError): self.context.error('invalid-constant-expression','Invalid constant expression.',node)

class DeclarationCheck(SemanticPass):
    def run(self,ast):
        for diagnostic in self.context.symbols.diagnostics: self.context.error(diagnostic.code,diagnostic.message,diagnostic.node)
        for node_id,symbol in self.context.symbols._references.items():
            if symbol is None:
                node=self.context.symbols._reference_nodes[node_id]
                self.context.error('undeclared-variable',f"Undeclared variable '{node.get('value')}'.",node)
        for symbol in self.context.symbols.iter_symbols():
            if symbol.type_ref and normalize_identifier(symbol.type_ref.name or '') not in self.context.declared_types:
                self.context.error('unknown-type',f"Unknown type '{symbol.type_ref.name}'.",symbol.type_ref.node or symbol.declaration)
        return self.context

class FillCandidateDatatypes(SemanticPass):
    def run(self,ast):
        for node in self.nodes(ast):
            if node.get('name')=='variable_name':
                symbol=self.context.symbols.symbol_for_reference(node) or self.context.symbols.symbol_for_declaration(node)
                if symbol:
                    self.context.candidate_types[id(node)]={symbol.attributes.get('datatype',UNKNOWN_TYPE)}
            if id(node) in self.context.constants:
                self.context.candidate_types.setdefault(id(node),{self.context.constants[id(node)].datatype})
        # propagate through single-child grammar wrappers
        changed=True
        while changed:
            changed=False
            for node in self.nodes(ast):
                children=[c for c in node.get('children',[]) if isinstance(c,dict)]
                if len(children)==1 and self.context.candidates(children[0]) and not self.context.candidates(node):
                    self.context.candidate_types[id(node)]=set(self.context.candidates(children[0])); changed=True
        return self.context

class NarrowCandidateDatatypes(SemanticPass):
    def run(self,ast):
        for node in self.nodes(ast):
            candidates=self.context.candidates(node)
            if len(candidates)==1:self.context.set_type(node,next(iter(candidates)))
        for node in self.nodes(ast):
            if node.get('name')!='assignment_statement':continue
            children=[c for c in node.get('children',[]) if isinstance(c,dict)]
            if len(children)<2:continue
            left,right=children[0],children[-1]
            destinations=self.context.candidates(left); sources=self.context.candidates(right)
            pairs=[(s,d) for s in sources for d in destinations if is_assignable(s,d)]
            if pairs:
                s,d=min(pairs,key=lambda p:conversion_cost(*p)); self.context.set_type(left,d); self.context.set_type(right,s)
        return self.context

class PrintDatatypesError(SemanticPass):
    def run(self,ast):
        for node in self.nodes(ast):
            if node.get('name')!='assignment_statement':continue
            children=[c for c in node.get('children',[]) if isinstance(c,dict)]
            if len(children)<2:continue
            left,right=children[0],children[-1]
            dst=self.context.candidates(left); src=self.context.candidates(right)
            if dst and src and not any(is_assignable(s,d) for s in src for d in dst):
                self.context.error('incompatible-assignment',f"Cannot assign {sorted(t.name for t in src)} to {sorted(t.name for t in dst)}.",node)
        return self.context

class ForcedNarrowCandidateDatatypes(SemanticPass):
    def run(self,ast):
        for node in self.nodes(ast):
            if self.context.type_of(node) is None:
                candidates=self.context.candidates(node)
                self.context.set_type(node,min(candidates,key=lambda t:(t.category==TypeCategory.UNKNOWN,t.bits or 999,t.name)) if candidates else ERROR_TYPE)
        return self.context

class LValueCheck(SemanticPass):
    def is_lvalue(self,node):
        if id(node) in self.context.lvalues:return self.context.lvalues[id(node)]
        variable_nodes=[n for n in self.nodes(node) if n.get('name')=='variable_name']
        result=False
        if variable_nodes:
            symbol=self.context.symbols.symbol_for_reference(variable_nodes[-1])
            result=bool(symbol and symbol.kind in {SymbolKind.VARIABLE,SymbolKind.PARAMETER,SymbolKind.RETURN_VALUE} and not symbol.attributes.get('constant'))
        self.context.lvalues[id(node)]=result; return result
    def run(self,ast):
        for node in self.nodes(ast):
            if node.get('name')=='assignment_statement':
                children=[c for c in node.get('children',[]) if isinstance(c,dict)]
                if children and not self.is_lvalue(children[0]): self.context.error('invalid-lvalue','Assignment target is not writable.',children[0])
            elif node.get('name')=='control_variable':
                token=next((n for n in self.nodes(node) if isinstance(n.get('value'),str)),None)
                if token:
                    scope=self.context.symbols.scope_for(node); symbol=scope.lookup(token['value']) if scope else None
                    if not symbol or symbol.attributes.get('constant'):self.context.error('invalid-for-control','FOR control variable is not writable.',node)
        return self.context

@dataclass(frozen=True,slots=True)
class CaseInterval:
    lower:int; upper:int; node:AstNode

class CaseElementsCheck(SemanticPass):
    def run(self,ast):
        for case in (n for n in self.nodes(ast) if n.get('name')=='case_statement'):
            intervals=[]
            for label in (n for n in self.nodes(case) if n.get('name')=='case_list_element'):
                constants=[self.context.constant_of(n) for n in self.nodes(label) if self.context.constant_of(n)]
                if not constants:self.context.error('non-constant-case-label','CASE label must be constant.',label); continue
                v=int(constants[-1].value); intervals.append(CaseInterval(v,v,label))
            intervals.sort(key=lambda i:(i.lower,i.upper))
            for previous,current in zip(intervals,intervals[1:]):
                if current.lower<=previous.upper:self.context.error('overlapping-case-elements',f"Duplicate or overlapping CASE label {current.lower}.",current.node)
        return self.context

class ArrayRangeCheck(SemanticPass):
    def run(self,ast):
        # Declaration ranges are represented by subrange nodes in the current parser.
        for node in (n for n in self.nodes(ast) if n.get('name') in {'subrange','subrange_specification'}):
            vals=[self.context.constant_of(n) for n in self.nodes(node) if self.context.constant_of(n)]
            if len(vals)>=2 and int(vals[0].value)>int(vals[1].value): self.context.error('invalid-array-range',f"Invalid range {vals[0].value}..{vals[1].value}.",node)
        return self.context

class DependencyAnalysis(SemanticPass):
    def run(self,ast):
        names=set(self.context.declaration_order)
        for owner in names:self.context.dependencies.setdefault(owner,set())
        # Generic collector: each declared type depends on other known type names in its subtree.
        for decl in self.nodes(ast):
            own=next((normalize_identifier(n['value']) for n in self.nodes(decl) if isinstance(n.get('value'),str) and normalize_identifier(n['value']) in names),None)
            if own is None:continue
            refs={normalize_identifier(n['value']) for n in self.nodes(decl) if isinstance(n.get('value'),str) and normalize_identifier(n['value']) in names and normalize_identifier(n['value'])!=own}
            self.context.dependencies[own].update(refs)
        return self.context

def topological_declaration_order(context:SemanticContext)->list[str]:
    deps={k:set(v) for k,v in context.dependencies.items()}; result=[]
    while deps:
        ready=sorted(k for k,v in deps.items() if not v)
        if not ready: raise ValueError('Cyclic declaration dependency: '+', '.join(sorted(deps)))
        result.extend(ready)
        for key in ready: deps.pop(key)
        for values in deps.values(): values.difference_update(ready)
    return result
