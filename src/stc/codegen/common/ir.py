"""Target-neutral Lowered IR for data-driven backends.

Every record carries resolved semantic facts (names, types, direction,
labels, priorities) and already-lowered target fragments for nested values.
No record contains target keywords, casts, ABI layout or control-flow syntax;
those decisions live exclusively in ``.gen`` templates.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class LoopDirection(str, Enum):
    ASCENDING = "ascending"
    DESCENDING = "descending"
    DYNAMIC = "dynamic"


@dataclass(frozen=True, slots=True)
class Literal:
    value: str
    type_name: str | None = None
    suffix: str = ""


@dataclass(frozen=True, slots=True)
class UnaryExpression:
    operator: str
    operand: str


@dataclass(frozen=True, slots=True)
class BinaryExpression:
    left: str
    operator: str
    right: str


@dataclass(frozen=True, slots=True)
class Assignment:
    target: str
    value: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class IfBranch:
    condition: str
    body: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class WhileLoop:
    condition: str
    body: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class RepeatLoop:
    condition: str
    body: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class ForLoop:
    variable: str
    start: str
    end: str
    step: str
    direction: LoopDirection
    body: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class Cast:
    source_type: str
    target_type: str
    value: str


@dataclass(frozen=True, slots=True)
class VirtualCall:
    receiver: str
    method: str
    static_type: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Jump:
    target_label: str
    target_index: int
    condition: str | None = None


@dataclass(frozen=True, slots=True)
class Call:
    name: str
    arguments: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArrayAccess:
    array: str
    indices: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Reference:
    value: str


@dataclass(frozen=True, slots=True)
class CaseElement:
    labels: tuple[str, ...]
    body: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class CaseStatement:
    selector: str
    elements: str
    else_body: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class Function:
    name: str
    emitted_name: str
    return_type: str
    parameters: str
    locals: str
    body: str
    return_value: str
    comment: str = ""


@dataclass(frozen=True, slots=True)
class PropertyGet:
    receiver: str
    method: str
    arguments: str = ""


@dataclass(frozen=True, slots=True)
class PropertySet:
    receiver: str
    method: str
    value: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class InterfaceAssignment:
    target: str
    source: str
    owner_class: str = ""
    interface: str = ""
    indent: str = ""


@dataclass(frozen=True, slots=True)
class FieldDecl:
    type: str
    name: str


@dataclass(frozen=True, slots=True)
class MethodDecl:
    owner: str = ""
    name: str = ""
    return_type: str = ""
    parameters: str = ""
    locals: str = ""
    body: str = ""
    has_return: str = ""


@dataclass(frozen=True, slots=True)
class ClassLayout:
    name: str
    base: str = ""
    has_base: str = ""
    fields: str = ""
    prototypes: str = ""
    vtable: str = ""
    dispatch: str = ""
    adapters: str = ""
    init: str = ""
    methods: str = ""
    interfaces: str = ""


@dataclass(frozen=True, slots=True)
class InterfaceLayout:
    name: str
    methods: str = ""
    bases: str = ""


@dataclass(frozen=True, slots=True)
class SfcChart:
    body: str
    indent: str = ""
    steps: str = ""
    transitions: str = ""
    actions: str = ""


@dataclass(frozen=True, slots=True)
class SfcTransition:
    fire: str
    condition: str
    sources: str = ""
    targets: str = ""
    priority: int = 0
    indent: str = ""


@dataclass(frozen=True, slots=True)
class SfcFire:
    fire: str
    sources: str
    condition: str
    indent: str = ""


@dataclass(frozen=True, slots=True)
class IlProgram:
    instructions: str
    labels: str = ""
    indent: str = ""


@dataclass(frozen=True, slots=True)
class IlInstruction:
    body: str
    index: int = 0
    label: str = ""
    has_label: str = ""
    indent: str = ""


@dataclass(frozen=True, slots=True)
class IlJump:
    target_label: str
    target_index: int
    condition: str = ""
    has_condition: str = ""
    indent: str = ""


@dataclass(frozen=True, slots=True)
class RuntimePrimitive:
    implementation: str
    name: str = ""
    dependencies: str = ""
    declaration: str = ""
