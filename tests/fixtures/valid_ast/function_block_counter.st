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
