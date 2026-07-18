(* Copyright (C) 2021-2026 Manuele Conti
   SPDX-License-Identifier: GPL-2.0-or-later
   Summary: Exercises parsing of directly represented IEC variables. *)

FUNCTION read_input_word : INT
VAR_INPUT
    fallback_value: INT;
END_VAR
    read_input_word := %IW0;
END_FUNCTION
