"""Symbol table construction for the IEC 61131-3 AST.

The table is deliberately independent from type checking and code generation.  A
single AST traversal records declarations, lexical scopes and identifier uses so
later compiler passes can perform O(1) node lookups and O(depth) name lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Iterator


AstNode = dict[str, Any]


class SymbolKind(str, Enum):
    TYPE = "type"
    FUNCTION = "function"
    FUNCTION_BLOCK = "function_block"
    PROGRAM = "program"
    CONFIGURATION = "configuration"
    VARIABLE = "variable"
    PARAMETER = "parameter"
    RETURN_VALUE = "return_value"
    ACCESS = "access"
    TASK = "task"


class ScopeKind(str, Enum):
    LIBRARY = "library"
    FUNCTION = "function"
    FUNCTION_BLOCK = "function_block"
    PROGRAM = "program"
    CONFIGURATION = "configuration"
    RESOURCE = "resource"


class StorageClass(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    IN_OUT = "in_out"
    LOCAL = "local"
    TEMP = "temp"
    EXTERNAL = "external"
    GLOBAL = "global"
    ACCESS = "access"
    RETURN = "return"
    UNKNOWN = "unknown"


def normalize_identifier(name: str) -> str:
    """Return the canonical IEC identifier key.

    IEC 61131-3 identifiers are case-insensitive. ``casefold`` is used rather
    than ``lower`` to make the invariant explicit and robust.
    """

    return name.casefold()


@dataclass(frozen=True, slots=True)
class TypeRef:
    """A lightweight type reference retained from the declaration AST."""

    name: str | None
    node: AstNode | None = field(default=None, compare=False, repr=False)


@dataclass(slots=True, eq=False)
class Symbol:
    name: str
    kind: SymbolKind
    declaration: AstNode
    scope: "Scope"
    type_ref: TypeRef | None = None
    storage: StorageClass = StorageClass.UNKNOWN
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        return normalize_identifier(self.name)


@dataclass(slots=True, eq=False)
class Scope:
    name: str
    kind: ScopeKind
    node: AstNode
    parent: "Scope | None" = None
    symbols: dict[str, Symbol] = field(default_factory=dict)
    children: list["Scope"] = field(default_factory=list)

    def define(self, symbol: Symbol) -> Symbol | None:
        """Insert *symbol* and return the previous local declaration, if any."""

        key = symbol.key
        previous = self.symbols.get(key)
        if previous is None:
            self.symbols[key] = symbol
        return previous

    def lookup_local(self, name: str) -> Symbol | None:
        return self.symbols.get(normalize_identifier(name))

    def lookup(self, name: str, kinds: Iterable[SymbolKind] | None = None) -> Symbol | None:
        accepted = set(kinds) if kinds is not None else None
        scope: Scope | None = self
        key = normalize_identifier(name)
        while scope is not None:
            symbol = scope.symbols.get(key)
            if symbol is not None and (accepted is None or symbol.kind in accepted):
                return symbol
            scope = scope.parent
        return None


@dataclass(frozen=True, slots=True)
class SymbolDiagnostic:
    code: str
    message: str
    node: AstNode
    previous: AstNode | None = None


@dataclass(slots=True)
class SymbolTable:
    global_scope: Scope
    diagnostics: list[SymbolDiagnostic] = field(default_factory=list)
    _node_scopes: dict[int, Scope] = field(default_factory=dict, repr=False)
    _declarations: dict[int, Symbol] = field(default_factory=dict, repr=False)
    _references: dict[int, Symbol | None] = field(default_factory=dict, repr=False)
    _reference_nodes: dict[int, AstNode] = field(default_factory=dict, repr=False)

    def scope_for(self, node: AstNode) -> Scope | None:
        return self._node_scopes.get(id(node))

    def symbol_for_declaration(self, node: AstNode) -> Symbol | None:
        return self._declarations.get(id(node))

    def symbol_for_reference(self, node: AstNode) -> Symbol | None:
        return self._references.get(id(node))

    def reference_was_indexed(self, node: AstNode) -> bool:
        return id(node) in self._references

    def lookup(self, name: str, scope: Scope | None = None) -> Symbol | None:
        return (scope or self.global_scope).lookup(name)

    def iter_scopes(self) -> Iterator[Scope]:
        stack = [self.global_scope]
        while stack:
            scope = stack.pop()
            yield scope
            stack.extend(reversed(scope.children))

    def iter_symbols(self) -> Iterator[Symbol]:
        for scope in self.iter_scopes():
            yield from scope.symbols.values()


class SymbolTableBuilder:
    """Build a :class:`SymbolTable` with one structural AST traversal."""

    _POU_NODES = {
        "function_declaration": (ScopeKind.FUNCTION, SymbolKind.FUNCTION, "derived_function_name"),
        "function_block_declaration": (
            ScopeKind.FUNCTION_BLOCK,
            SymbolKind.FUNCTION_BLOCK,
            "derived_function_block_name",
        ),
        "program_declaration": (ScopeKind.PROGRAM, SymbolKind.PROGRAM, "program_type_name"),
        "configuration_declaration": (
            ScopeKind.CONFIGURATION,
            SymbolKind.CONFIGURATION,
            "configuration_name",
        ),
    }

    _DECLARATION_NODES = {
        "var1_init_decl",
        "var1_declaration",
        "array_var_init_decl",
        "array_var_declaration",
        "structured_var_init_decl",
        "structured_var_declaration",
        "string_var_declaration",
        "edge_declaration",
    }

    _SECTION_STORAGE = {
        "input_declarations": StorageClass.INPUT,
        "output_declarations": StorageClass.OUTPUT,
        "input_output_declarations": StorageClass.IN_OUT,
        "function_var_decls": StorageClass.LOCAL,
        "var_declarations": StorageClass.LOCAL,
        "temp_var_decls": StorageClass.TEMP,
        "external_var_declarations": StorageClass.EXTERNAL,
        "global_var_declarations": StorageClass.GLOBAL,
        "retentive_var_declarations": StorageClass.LOCAL,
        "non_retentive_var_decls": StorageClass.LOCAL,
    }

    _TYPE_LEAF_NAMES = {
        "signed_integer_type_name",
        "unsigned_integer_type_name",
        "real_type_name",
        "bit_string_type_name",
        "date_type_name",
        "time_type_name",
        "string_type_name",
        "derived_type_name",
        "function_block_type_name",
        "program_type_name",
        "non_generic_type_name",
    }

    def __init__(self) -> None:
        self.table: SymbolTable | None = None

    def build(self, ast: AstNode) -> SymbolTable:
        root = Scope("<library>", ScopeKind.LIBRARY, ast)
        self.table = SymbolTable(root)
        self._walk(ast, root, StorageClass.UNKNOWN, declaration_context=False)
        return self.table

    def _walk(
        self,
        node: Any,
        scope: Scope,
        storage: StorageClass,
        declaration_context: bool,
    ) -> None:
        if not isinstance(node, dict):
            return

        table = self._table
        table._node_scopes[id(node)] = scope
        name = node.get("name")

        if name in self._POU_NODES:
            self._visit_pou(node, scope)
            return

        if name in self._SECTION_STORAGE:
            storage = self._SECTION_STORAGE[name]

        if name in self._DECLARATION_NODES:
            self._declare_variables(node, scope, storage)
            # Walk type/initializer children, but suppress variable names in the
            # declaration's name-list from reference indexing.
            for child in node.get("children", []):
                child_is_names = isinstance(child, dict) and child.get("name") in {
                    "var1_list", "fb_name_list"
                }
                self._walk(child, scope, storage, declaration_context=child_is_names)
            return

        if name == "fb_name_decl":
            self._declare_named_nodes(node, scope, storage, "fb_name", SymbolKind.VARIABLE)
            for child in node.get("children", []):
                self._walk(child, scope, storage, declaration_context=True)
            return

        if name == "variable_name" and not declaration_context:
            symbol_name = node.get("value")
            if isinstance(symbol_name, str):
                table._references[id(node)] = scope.lookup(symbol_name)
                table._reference_nodes[id(node)] = node

        for child in node.get("children", []):
            self._walk(child, scope, storage, declaration_context)

    def _visit_pou(self, node: AstNode, parent: Scope) -> None:
        scope_kind, symbol_kind, name_node_kind = self._POU_NODES[node["name"]]
        name_node = self._first_descendant(node, name_node_kind)
        pou_name = self._node_value(name_node) or f"<{node['name']}>"

        pou_symbol = Symbol(pou_name, symbol_kind, node, parent, self._pou_type(node))
        self._define(pou_symbol)
        if name_node is not None:
            self._table._declarations[id(name_node)] = pou_symbol

        child_scope = Scope(pou_name, scope_kind, node, parent)
        parent.children.append(child_scope)
        self._table._node_scopes[id(node)] = child_scope

        if node["name"] == "function_declaration":
            return_symbol = Symbol(
                pou_name,
                SymbolKind.RETURN_VALUE,
                name_node or node,
                child_scope,
                self._pou_type(node),
                StorageClass.RETURN,
            )
            self._define(return_symbol)

        # Skip the POU name child: it is already indexed as a declaration.
        for child in node.get("children", []):
            if child is name_node:
                self._table._node_scopes[id(child)] = child_scope
                continue
            self._walk(child, child_scope, StorageClass.UNKNOWN, declaration_context=False)

    def _declare_variables(self, node: AstNode, scope: Scope, storage: StorageClass) -> None:
        names_container = self._first_child_named(node, "var1_list")
        if names_container is None:
            return
        type_ref = self._extract_type(node)
        kind = SymbolKind.PARAMETER if storage in {
            StorageClass.INPUT, StorageClass.OUTPUT, StorageClass.IN_OUT
        } else SymbolKind.VARIABLE
        for name_node in self._descendants_named(names_container, "variable_name"):
            value = self._node_value(name_node)
            if value is None:
                continue
            symbol = Symbol(value, kind, name_node, scope, type_ref, storage)
            self._define(symbol)
            self._table._declarations[id(name_node)] = symbol

    def _declare_named_nodes(
        self,
        node: AstNode,
        scope: Scope,
        storage: StorageClass,
        node_name: str,
        kind: SymbolKind,
    ) -> None:
        type_ref = self._extract_type(node)
        for name_node in self._descendants_named(node, node_name):
            value = self._node_value(name_node)
            if value is None:
                continue
            symbol = Symbol(value, kind, name_node, scope, type_ref, storage)
            self._define(symbol)
            self._table._declarations[id(name_node)] = symbol

    def _define(self, symbol: Symbol) -> None:
        previous = symbol.scope.define(symbol)
        if previous is not None:
            self._table.diagnostics.append(SymbolDiagnostic(
                "duplicate-declaration",
                f"Duplicate declaration of '{symbol.name}' in scope '{symbol.scope.name}'.",
                symbol.declaration,
                previous.declaration,
            ))

    def _pou_type(self, node: AstNode) -> TypeRef | None:
        if node.get("name") != "function_declaration":
            return None
        children = node.get("children", [])
        return self._extract_type(children[1]) if len(children) > 1 else None

    def _extract_type(self, node: Any) -> TypeRef | None:
        if not isinstance(node, dict):
            return None
        for candidate in self._iter_nodes(node):
            if candidate.get("name") in self._TYPE_LEAF_NAMES:
                value = candidate.get("value")
                if isinstance(value, str):
                    return TypeRef(value, candidate)
                leaf = self._first_value_descendant(candidate)
                if leaf is not None:
                    return TypeRef(leaf.get("value"), candidate)
        return None

    @staticmethod
    def _node_value(node: AstNode | None) -> str | None:
        value = node.get("value") if node else None
        return value if isinstance(value, str) else None

    @classmethod
    def _first_value_descendant(cls, node: AstNode) -> AstNode | None:
        for candidate in cls._iter_nodes(node):
            if isinstance(candidate.get("value"), str):
                return candidate
        return None

    @staticmethod
    def _first_child_named(node: AstNode, name: str) -> AstNode | None:
        for child in node.get("children", []):
            if isinstance(child, dict) and child.get("name") == name:
                return child
        return None

    @classmethod
    def _first_descendant(cls, node: AstNode, name: str) -> AstNode | None:
        return next(cls._descendants_named(node, name), None)

    @classmethod
    def _descendants_named(cls, node: AstNode, name: str) -> Iterator[AstNode]:
        for candidate in cls._iter_nodes(node):
            if candidate.get("name") == name:
                yield candidate

    @staticmethod
    def _iter_nodes(node: Any) -> Iterator[AstNode]:
        if not isinstance(node, dict):
            return
        yield node
        for child in node.get("children", []):
            yield from SymbolTableBuilder._iter_nodes(child)

    @property
    def _table(self) -> SymbolTable:
        if self.table is None:
            raise RuntimeError("SymbolTableBuilder.build() has not been called")
        return self.table
