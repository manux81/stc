FUNCTION climb_until : INT
VAR_INPUT
    start_value: INT;
END_VAR
VAR
    cursor_value: INT;
END_VAR
    cursor_value := start_value;
    REPEAT
        cursor_value := cursor_value + 1;
    UNTIL cursor_value >= 10
    END_REPEAT;
    climb_until := cursor_value;
END_FUNCTION
