"""Small, target-neutral Lowered IR used by the first generator migration.

The classes deliberately contain semantic facts, never target syntax.  Later
phases can add nodes without changing the template language.
"""

from __future__ import annotations

from dataclasses import dataclass
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
