(* Copyright (C) 2021-2026 Manuele Conti
   SPDX-License-Identifier: GPL-2.0-or-later
   Summary: Verifies diagnostics for references to undeclared variables. *)

FUNCTION bad : INT
VAR_INPUT
    input_value: INT;
END_VAR
    bad := input_value + missing_value;
END_FUNCTION
