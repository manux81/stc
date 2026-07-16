FUNCTION normalize_mode : INT
VAR_INPUT
    mode_value: INT;
END_VAR
VAR
    index_value: INT;
END_VAR
    CASE mode_value OF
        0: normalize_mode := 10;
        1, 2: normalize_mode := 20;
    ELSE
        normalize_mode := 0;
    END_CASE;
    FOR index_value := 0 TO 3 BY 1 DO
        normalize_mode := normalize_mode + index_value;
    END_FOR;
END_FUNCTION
