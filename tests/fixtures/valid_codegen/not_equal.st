(* Copyright (C) 2021-2026 Manuele Conti
   SPDX-License-Identifier: GPL-2.0-or-later
   Summary: Verifies code generation for the IEC not-equal operator. *)

FUNCTION differs : BOOL
VAR_INPUT
    left_value, right_value: INT;
END_VAR
    differs := left_value <> right_value;
END_FUNCTION
