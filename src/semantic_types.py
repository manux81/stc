# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Define type-system primitives shared by semantic analysis passes."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

class TypeCategory(str, Enum):
    BOOL='bool'; SIGNED_INT='signed_int'; UNSIGNED_INT='unsigned_int'; REAL='real'
    BIT_STRING='bit_string'; STRING='string'; TIME='time'; DATE='date'; ENUM='enum'
    ARRAY='array'; STRUCT='struct'; FUNCTION_BLOCK='function_block'; UNKNOWN='unknown'; ERROR='error'

@dataclass(frozen=True, slots=True)
class DataType:
    name: str
    category: TypeCategory
    bits: int | None = None

@dataclass(frozen=True, slots=True)
class ArrayDimension:
    lower: int
    upper: int

@dataclass(frozen=True, slots=True)
class ArrayType(DataType):
    dimensions: tuple[ArrayDimension, ...] = ()
    element_type: DataType | None = None

@dataclass(frozen=True, slots=True)
class EnumType(DataType):
    elements: tuple[str, ...] = ()

@dataclass(frozen=True, slots=True)
class ConstantValue:
    datatype: DataType
    value: Any

BOOL=DataType('BOOL',TypeCategory.BOOL,1)
SINT=DataType('SINT',TypeCategory.SIGNED_INT,8); INT=DataType('INT',TypeCategory.SIGNED_INT,16)
DINT=DataType('DINT',TypeCategory.SIGNED_INT,32); LINT=DataType('LINT',TypeCategory.SIGNED_INT,64)
USINT=DataType('USINT',TypeCategory.UNSIGNED_INT,8); UINT=DataType('UINT',TypeCategory.UNSIGNED_INT,16)
UDINT=DataType('UDINT',TypeCategory.UNSIGNED_INT,32); ULINT=DataType('ULINT',TypeCategory.UNSIGNED_INT,64)
REAL=DataType('REAL',TypeCategory.REAL,32); LREAL=DataType('LREAL',TypeCategory.REAL,64)
BYTE=DataType('BYTE',TypeCategory.BIT_STRING,8); WORD=DataType('WORD',TypeCategory.BIT_STRING,16)
DWORD=DataType('DWORD',TypeCategory.BIT_STRING,32); LWORD=DataType('LWORD',TypeCategory.BIT_STRING,64)
UNKNOWN_TYPE=DataType('<unknown>',TypeCategory.UNKNOWN); ERROR_TYPE=DataType('<error>',TypeCategory.ERROR)

BUILTIN_TYPES={t.name.casefold():t for t in (BOOL,SINT,INT,DINT,LINT,USINT,UINT,UDINT,ULINT,REAL,LREAL,BYTE,WORD,DWORD,LWORD)}
INTEGER_TYPES=(SINT,INT,DINT,LINT,USINT,UINT,UDINT,ULINT)

def is_integer(t: DataType)->bool: return t.category in {TypeCategory.SIGNED_INT,TypeCategory.UNSIGNED_INT}
def is_numeric(t: DataType)->bool: return is_integer(t) or t.category==TypeCategory.REAL

def value_fits(value:int,t:DataType)->bool:
    if not is_integer(t) or t.bits is None: return False
    if t.category==TypeCategory.UNSIGNED_INT: return 0 <= value <= (1<<t.bits)-1
    return -(1<<(t.bits-1)) <= value <= (1<<(t.bits-1))-1

def is_assignable(source:DataType,destination:DataType)->bool:
    if ERROR_TYPE in (source,destination) or UNKNOWN_TYPE in (source,destination): return True
    if source==destination: return True
    if is_integer(source) and is_integer(destination):
        if source.bits is None or destination.bits is None: return False
        if source.category==destination.category: return source.bits<=destination.bits
        return source.category==TypeCategory.UNSIGNED_INT and destination.category==TypeCategory.SIGNED_INT and source.bits<=destination.bits
    return is_integer(source) and destination.category==TypeCategory.REAL

def conversion_cost(source:DataType,destination:DataType)->int:
    if source==destination:return 0
    if is_assignable(source,destination):return 1+(destination.bits or 0)-(source.bits or 0)
    return 10000
