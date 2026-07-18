(* Copyright (C) 2021-2026 Manuele Conti
   SPDX-License-Identifier: GPL-2.0-or-later
   Summary: Verifies code generation for typed and based numeric literals. *)

FUNCTION add_literals : INT
VAR_INPUT
    base_value: INT;
END_VAR
    add_literals := base_value + INT#10 + 2#1010 + 16#0A;
END_FUNCTION
