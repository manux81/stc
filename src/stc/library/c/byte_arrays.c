// Copyright (C) 2021-2026 Manuele Conti
// SPDX-License-Identifier: GPL-2.0-or-later
// STC_PRIMITIVE_BEGIN BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline void stc_bytes_fail(void) { abort(); }
static STC_MAYBE_UNUSED inline uint32_t stc_bytes_scalar(const unsigned char **p, const unsigned char *end)
{
    if (*p >= end) { stc_bytes_fail(); return 0; }
    uint32_t a = *(*p)++, value; unsigned count; uint32_t minimum;
    if (a < 0x80) return a;
    if (a >= 0xc2 && a <= 0xdf) { value = a & 31; count = 1; minimum = 0x80; }
    else if (a >= 0xe0 && a <= 0xef) { value = a & 15; count = 2; minimum = 0x800; }
    else if (a >= 0xf0 && a <= 0xf4) { value = a & 7; count = 3; minimum = 0x10000; }
    else { stc_bytes_fail(); return 0; }
    while (count--) {
        if (*p >= end || (**p & 0xc0) != 0x80) { stc_bytes_fail(); return 0; }
        value = (value << 6) | (*(*p)++ & 63);
    }
    if (value < minimum || value > 0x10ffff || (value >= 0xd800 && value <= 0xdfff)) stc_bytes_fail();
    return value;
}
static STC_MAYBE_UNUSED inline size_t stc_bytes_utf8(char *out, uint32_t value)
{
    if (value < 0x80) { out[0] = (char)value; return 1; }
    if (value < 0x800) { out[0] = (char)(0xc0 | (value >> 6)); out[1] = (char)(0x80 | (value & 63)); return 2; }
    if (value < 0x10000) { out[0] = (char)(0xe0 | (value >> 12)); out[1] = (char)(0x80 | ((value >> 6) & 63)); out[2] = (char)(0x80 | (value & 63)); return 3; }
    out[0] = (char)(0xf0 | (value >> 18)); out[1] = (char)(0x80 | ((value >> 12) & 63)); out[2] = (char)(0x80 | ((value >> 6) & 63)); out[3] = (char)(0x80 | (value & 63)); return 4;
}
static STC_MAYBE_UNUSED inline void stc_bytes_encode(const char *text, uint8_t *out, size_t capacity, unsigned encoding)
{
    if (!text) text = "";
    const unsigned char *p = (const unsigned char *)text, *end = p + strlen(text);
    size_t used = 0;
    memset(out, 0, capacity);
    while (p < end) {
        const unsigned char *start = p;
        uint32_t value = stc_bytes_scalar(&p, end);
        if (encoding == 1) {
            if (value > 255 || used >= capacity) stc_bytes_fail();
            out[used++] = (uint8_t)value;
        } else if (encoding == 2) {
            size_t needed = value < 0x10000 ? 2 : 4;
            if (capacity - used < needed) stc_bytes_fail();
            if (needed == 4) {
                value -= 0x10000;
                uint32_t high = 0xd800 | (value >> 10);
                out[used++] = (uint8_t)high; out[used++] = (uint8_t)(high >> 8);
                value = 0xdc00 | (value & 1023);
            }
            out[used++] = (uint8_t)value; out[used++] = (uint8_t)(value >> 8);
        } else {
            size_t needed = (size_t)(p - start);
            if (capacity - used < needed) stc_bytes_fail();
            memcpy(out + used, start, needed); used += needed;
        }
    }
}
static STC_MAYBE_UNUSED inline const char *stc_bytes_decode(const uint8_t *bytes, size_t size, unsigned encoding)
{
    if (size > (SIZE_MAX - 1) / 4) stc_bytes_fail();
    char *out = (char *)malloc(size * 4 + 1);
    if (!out) stc_bytes_fail();
    size_t used = 0, i = 0;
    while (i < size) {
        uint32_t value;
        if (encoding == 1) { value = bytes[i++]; if (!value) break; }
        else if (encoding == 2) {
            if (size - i < 2) { if (bytes[i]) stc_bytes_fail(); break; }
            value = (uint32_t)bytes[i] | ((uint32_t)bytes[i + 1] << 8); i += 2;
            if (!value) break;
            if (value >= 0xd800 && value <= 0xdbff) {
                if (size - i < 2) stc_bytes_fail();
                uint32_t low = (uint32_t)bytes[i] | ((uint32_t)bytes[i + 1] << 8); i += 2;
                if (low < 0xdc00 || low > 0xdfff) stc_bytes_fail();
                value = 0x10000 + ((value - 0xd800) << 10) + low - 0xdc00;
            } else if (value >= 0xdc00 && value <= 0xdfff) stc_bytes_fail();
        } else {
            if (!bytes[i]) break;
            const unsigned char *p = bytes + i;
            value = stc_bytes_scalar(&p, bytes + size); i = (size_t)(p - bytes);
        }
        used += stc_bytes_utf8(out + used, value);
    }
    out[used] = 0;
    return out;
}

// STC_PRIMITIVE_END BYTE_ARRAY_SUPPORT

// STC_PRIMITIVE_BEGIN STRING_TO_ARRAY_OF_BYTE BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline void STRING_TO_ARRAY_OF_BYTE(const char *text, uint8_t *out, size_t size) { stc_bytes_encode(text, out, size, 1); }
// STC_PRIMITIVE_END STRING_TO_ARRAY_OF_BYTE

// STC_PRIMITIVE_BEGIN ARRAY_OF_BYTE_TO_STRING BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline const char *ARRAY_OF_BYTE_TO_STRING(const uint8_t *bytes, size_t size) { return stc_bytes_decode(bytes, size, 1); }
// STC_PRIMITIVE_END ARRAY_OF_BYTE_TO_STRING

// STC_PRIMITIVE_BEGIN WSTRING_TO_ARRAY_OF_BYTE BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline void WSTRING_TO_ARRAY_OF_BYTE(const char *text, uint8_t *out, size_t size) { stc_bytes_encode(text, out, size, 2); }
// STC_PRIMITIVE_END WSTRING_TO_ARRAY_OF_BYTE

// STC_PRIMITIVE_BEGIN ARRAY_OF_BYTE_TO_WSTRING BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline const char *ARRAY_OF_BYTE_TO_WSTRING(const uint8_t *bytes, size_t size) { return stc_bytes_decode(bytes, size, 2); }
// STC_PRIMITIVE_END ARRAY_OF_BYTE_TO_WSTRING

// STC_PRIMITIVE_BEGIN USTRING_TO_ARRAY_OF_BYTE BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline void USTRING_TO_ARRAY_OF_BYTE(const char *text, uint8_t *out, size_t size) { stc_bytes_encode(text, out, size, 3); }
// STC_PRIMITIVE_END USTRING_TO_ARRAY_OF_BYTE

// STC_PRIMITIVE_BEGIN ARRAY_OF_BYTE_TO_USTRING BYTE_ARRAY_SUPPORT
static STC_MAYBE_UNUSED inline const char *ARRAY_OF_BYTE_TO_USTRING(const uint8_t *bytes, size_t size) { return stc_bytes_decode(bytes, size, 3); }
// STC_PRIMITIVE_END ARRAY_OF_BYTE_TO_USTRING
