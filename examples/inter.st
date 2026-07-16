FUNCTION inter : INT
VAR_INPUT
    a_1, b_1: INT;
    test: BOOL;
END_VAR
VAR
    ff: INT;
END_VAR
    test := TRUE;
    IF a_1 = b_1 THEN
        a_1 := 70_9;
    ELSIF b_1 = 1 THEN
        b_1 := INT#10;
    END_IF;
    inter := a_1 + b_1;
END_FUNCTION
