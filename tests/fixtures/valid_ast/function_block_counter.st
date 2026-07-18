(* Copyright (C) 2021-2026 Manuele Conti
   SPDX-License-Identifier: GPL-2.0-or-later
   Summary: Exercises a stateful counter function-block declaration. *)

FUNCTION_BLOCK Counter
VAR_INPUT
    reset_value : BOOL;
END_VAR
VAR_OUTPUT
    count_value : INT;
END_VAR
    IF reset_value THEN
        count_value := 0;
    ELSE
        count_value := count_value + 1;
    END_IF;
END_FUNCTION_BLOCK
