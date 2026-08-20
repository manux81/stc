(* Copyright (C) 2021-2026 Manuele Conti
   SPDX-License-Identifier: GPL-2.0-or-later
   Summary: Target-independent implementations of IEC standard functions.

   Keep portable algorithms in this file. Operations that directly access the
   target string representation, such as LEN and MID, remain compiler
   intrinsics and are shared by these higher-level functions. *)

(*****************************************************************************
 * Character string functions
 *****************************************************************************)

FUNCTION FIND : INT
VAR_INPUT
    IN1 : STRING;
    IN2 : STRING;
END_VAR
VAR
    Position     : INT;
    InputLength  : INT;
    SearchLength : INT;
END_VAR

FIND := 0;
InputLength := LEN(IN1);
SearchLength := LEN(IN2);

IF SearchLength > 0 THEN
    FOR Position := 1 TO InputLength - SearchLength + 1 DO
        IF MID(IN1, SearchLength, Position) = IN2 THEN
            FIND := Position;
            EXIT;
        END_IF;
    END_FOR;
END_IF;
END_FUNCTION

(*****************************************************************************
 * IEC 61131-3 Edition 3 bit-string conversions
 *****************************************************************************)

FUNCTION BYTE_TO_BOOL : BOOL
VAR_INPUT Value : BYTE; END_VAR
BYTE_TO_BOOL := Value <> 0;
END_FUNCTION

FUNCTION WORD_TO_BOOL : BOOL
VAR_INPUT Value : WORD; END_VAR
WORD_TO_BOOL := Value <> 0;
END_FUNCTION

FUNCTION DWORD_TO_BOOL : BOOL
VAR_INPUT Value : DWORD; END_VAR
DWORD_TO_BOOL := Value <> 0;
END_FUNCTION

FUNCTION LWORD_TO_BOOL : BOOL
VAR_INPUT Value : LWORD; END_VAR
LWORD_TO_BOOL := Value <> 0;
END_FUNCTION

(*****************************************************************************
 * IEC 61131-3 Edition 4 character conversions
 *****************************************************************************)

FUNCTION USINT_TO_CHAR : CHAR
VAR_INPUT Value : USINT; END_VAR
USINT_TO_CHAR := Value;
END_FUNCTION

FUNCTION UINT_TO_WCHAR : WCHAR
VAR_INPUT Value : UINT; END_VAR
UINT_TO_WCHAR := Value;
END_FUNCTION

FUNCTION UDINT_TO_UCHAR : UCHAR
VAR_INPUT Value : UDINT; END_VAR
UDINT_TO_UCHAR := Value;
END_FUNCTION

FUNCTION WCHAR_TO_UINT : UINT
VAR_INPUT Value : WCHAR; END_VAR
WCHAR_TO_UINT := Value;
END_FUNCTION
