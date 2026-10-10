# Edition 4 string and byte-array conversions

STC implements the six string/byte-array conversion names for its C and Rust backends with `-s ed4`. Edition 2 and 3 reject these calls. This document defines the current STC contract; it does not assert that the signatures or byte order have been verified against the normative Edition 4 text.

```iecst
PROGRAM Example
VAR
    Bytes : ARRAY[1..8] OF BYTE;
    Text : USTRING;
END_VAR
Bytes := USTRING_TO_ARRAY_OF_BYTE(USTRING#'A🙂');
Text := ARRAY_OF_BYTE_TO_USTRING(Bytes);
END_PROGRAM
```

| String family | Encode | Decode | External byte encoding |
| --- | --- | --- | --- |
| STRING | STRING_TO_ARRAY_OF_BYTE | ARRAY_OF_BYTE_TO_STRING | Single-byte values U+0001–U+00FF (Latin-1) |
| WSTRING | WSTRING_TO_ARRAY_OF_BYTE | ARRAY_OF_BYTE_TO_WSTRING | UTF-16 little endian, including surrogate pairs |
| USTRING | USTRING_TO_ARRAY_OF_BYTE | ARRAY_OF_BYTE_TO_USTRING | UTF-8 |

Each call takes one positional input. Encoding must be assigned directly to a fixed, one-dimensional `ARRAY OF BYTE`; its declared capacity supplies the result size. Inline and named array types and arbitrary lower bounds are supported. `USINT` arrays, multidimensional arrays and indexed array elements are rejected.

Encoding fills unused bytes with zero. A payload that exactly fills the destination is accepted without a terminator. Decoding stops at the first zero byte for STRING/USTRING, or the first zero UTF-16 code unit for WSTRING; otherwise it consumes the whole array. Bytes after the terminator are ignored. An odd final WSTRING byte is accepted only when zero. Embedded NUL characters cannot round-trip through these null-terminated conversions.

Invalid UTF-8, invalid UTF-16 surrogate pairs, a STRING character exceeding 255, and insufficient destination capacity terminate execution (`abort` in C, panic in Rust), including release builds. No silent truncation or replacement characters are used.

## Current ABI limitation

The existing backends represent strings as borrowed UTF-8 text (`const char *` in C, `&str` in Rust), including WSTRING. Decoding allocates a stable result and retains that allocation for the lifetime of the process. Repeated decoding in a cyclic PLC program therefore grows memory usage. These functions need integration with the ongoing owned/bounded string ABI work before they are suitable for sustained cyclic workloads. Buffer encoding itself writes into the declared array.

## Verification and references

`tests/test_byte_array_conversions.py` compiles and executes generated C and Rust with warnings treated as errors. It checks all six names, exact bytes, round trips, named/negative-bound arrays, independent results, terminators, zero padding, invalid encodings, insufficient capacity, and semantic/profile diagnostics.

The [Edition 3/4 comparison article](https://stefanhenneken.net/2025/06/11/iec-61131-3-comparison-of-edition-3-and-edition-4/) identifies the new conversion names but does not define their complete calling or byte-encoding contract. The [Siemens compliance manual](https://cache.industry.siemens.com/dl/files/748/109476748/att_845621/v1/IEC_61131_compliance_en_US.pdf) is dated April 2015 and covers Edition 3; it does not document these Edition 4 conversions. Normative verification remains pending.
