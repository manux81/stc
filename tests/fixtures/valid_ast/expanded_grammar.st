TYPE
    SampleArray : ARRAY [0..3] OF INT;
    SampleStruct : STRUCT
        count_value : INT;
        label_text : STRING[16];
    END_STRUCT;
END_TYPE

FUNCTION normalize_sample : INT
VAR_INPUT
    raw_value: INT;
END_VAR
VAR
    values: ARRAY [0..3] OF INT := [1, 2, 3, 4];
    status_text: STRING[16] := 'running';
    created_on: DATE := D#2026-07-17;
    started_at: TIME_OF_DAY := TOD#12:34:56.7;
    sample_stamp: DATE_AND_TIME := DT#2026-07-17-12:34:56.7;
    timeout_value: TIME := T#1H;
END_VAR
    CASE raw_value OF
        0: normalize_sample := MIN(IN1 := raw_value, IN2 := 10);
        1, 2: normalize_sample := LIMIT(MN := 0, IN := raw_value, MX := 10);
    ELSE
        normalize_sample := MAX(IN1 := raw_value, IN2 := 0);
    END_CASE;

    FOR raw_value := 0 TO 3 BY 1 DO
        normalize_sample := normalize_sample + values[raw_value];
    END_FOR;
END_FUNCTION

PROGRAM SampleProgram
VAR
    current_value: INT;
END_VAR
    current_value := normalize_sample(raw_value := current_value);
END_PROGRAM
