FUNCTION inter : INT
VAR_INPUT
    a_1: SINT;
    b_1: INT;
    test: BOOL;
END_VAR
VAR
    ff: INT;
END_VAR
    test := TRUE;
    IF a_1 = b_1 THEN
        a_1 := 70;
    ELSIF b_1 = 1 THEN
        b_1 := USINT#10;
    END_IF;
    inter := a_1 + b_1;
    FOR ff := 1 TO 10 DO
	a_1 := a_1 + ff;
    END_FOR;
END_FUNCTION
