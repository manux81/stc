# stc
Structured Text Compiler

stc - Executable EBNF grammar for IEC 61131-3 ST POUs
=============================================================

STC is composed of the two terms ST and [yacc]https://github.com/dabeaz/ply and represents an executable grammar for IEC 61131-3 Structured Text modules that is defined using the Extended Backus-Naur Form (EBNF).

Features
----------------
* IEC 61131-3 POU-Types: Program, Functionblock, Function
* Sections (each available only once): VAR_INPUT, VAR, VAR_OUTPUT, VAR_IN_OUT, VAR_EXTERNAL
* Data types: BOOL, INT, DINT, UINT, REAL, TIME, ARRAY
* Operators: *, /, MOD, +, -, NOT, AND, XOR, OR, <=, >=, <, >, =, <>, FALSE, TRUE, external function/functionblocks, variable, constant
* Statements: assignments, if/else, case, macro, for, while, repeat, exit, return

Our goal is to minimize and to ensure uniqueness of the resulting parsing tree for a subset of the ST constructs for further use. 



References
----------------
[1] DIN Deutsches Institut für Normung e. V., “Programmable controllers – Part 3: Programming languages (IEC 61131-3:2013); German version EN 61131-3:2013,” 2014.
