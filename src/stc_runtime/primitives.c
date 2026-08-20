/* Copyright (C) 2021-2026 Manuele Conti
 * SPDX-License-Identifier: GPL-2.0-or-later
 *
 * Portable C primitives embedded into generated translation units by STC.
 * Blocks are selected by primitive_runtime.py; keep marker names stable.
 */

// STC_PRIMITIVE_BEGIN CORE
/* Common state layout used by standard function-block placeholders. */
typedef struct TON {
    bool Q;
    bool Q1;
    int64_t ET;
    int16_t CV;
} TON;

typedef TON TOF;
typedef TON TP;
typedef TON CTU;
typedef TON CTD;
typedef TON CTUD;
typedef TON R_TRIG;
typedef TON F_TRIG;
typedef TON SR;
typedef TON RS;

#if defined(__GNUC__) || defined(__clang__)
#define STC_MAYBE_UNUSED __attribute__((unused))
#else
#define STC_MAYBE_UNUSED
#endif
// STC_PRIMITIVE_END CORE

// STC_PRIMITIVE_BEGIN ABS
#define ABS(x) fabs(x)
// STC_PRIMITIVE_END ABS
// STC_PRIMITIVE_BEGIN SQRT
#define SQRT(x) sqrt(x)
// STC_PRIMITIVE_END SQRT
// STC_PRIMITIVE_BEGIN LN
#define LN(x) log(x)
// STC_PRIMITIVE_END LN
// STC_PRIMITIVE_BEGIN LOG
#define LOG(x) log10(x)
// STC_PRIMITIVE_END LOG
// STC_PRIMITIVE_BEGIN EXP
#define EXP(x) exp(x)
// STC_PRIMITIVE_END EXP
// STC_PRIMITIVE_BEGIN SIN
#define SIN(x) sin(x)
// STC_PRIMITIVE_END SIN
// STC_PRIMITIVE_BEGIN COS
#define COS(x) cos(x)
// STC_PRIMITIVE_END COS
// STC_PRIMITIVE_BEGIN TAN
#define TAN(x) tan(x)
// STC_PRIMITIVE_END TAN
// STC_PRIMITIVE_BEGIN ASIN
#define ASIN(x) asin(x)
// STC_PRIMITIVE_END ASIN
// STC_PRIMITIVE_BEGIN ACOS
#define ACOS(x) acos(x)
// STC_PRIMITIVE_END ACOS
// STC_PRIMITIVE_BEGIN ATAN
#define ATAN(x) atan(x)
// STC_PRIMITIVE_END ATAN
// STC_PRIMITIVE_BEGIN TRUNC
#define TRUNC(x) trunc(x)
// STC_PRIMITIVE_END TRUNC

// STC_PRIMITIVE_BEGIN MIN
#define MIN(a, b) ((a) < (b) ? (a) : (b))
// STC_PRIMITIVE_END MIN
// STC_PRIMITIVE_BEGIN MAX
#define MAX(a, b) ((a) > (b) ? (a) : (b))
// STC_PRIMITIVE_END MAX
// STC_PRIMITIVE_BEGIN LIMIT MIN MAX
#define LIMIT(lo, x, hi) (MAX((lo), MIN((x), (hi))))
// STC_PRIMITIVE_END LIMIT
// STC_PRIMITIVE_BEGIN SEL
#define SEL(g, a, b) ((g) ? (b) : (a))
// STC_PRIMITIVE_END SEL
// STC_PRIMITIVE_BEGIN MUX
#define MUX(k, a, b, c, d) ((k) == 0 ? (a) : (k) == 1 ? (b) : (k) == 2 ? (c) : (d))
// STC_PRIMITIVE_END MUX
// STC_PRIMITIVE_BEGIN AND
#define AND(a, b) ((a) & (b))
// STC_PRIMITIVE_END AND

// STC_PRIMITIVE_BEGIN INT_TO_DINT
#define INT_TO_DINT(x) ((int32_t)(x))
// STC_PRIMITIVE_END INT_TO_DINT
// STC_PRIMITIVE_BEGIN INT_TO_REAL
#define INT_TO_REAL(x) ((float)(x))
// STC_PRIMITIVE_END INT_TO_REAL
// STC_PRIMITIVE_BEGIN REAL_TO_INT
#define REAL_TO_INT(x) ((int16_t)(x))
// STC_PRIMITIVE_END REAL_TO_INT
// STC_PRIMITIVE_BEGIN INT_TO_BOOL
#define INT_TO_BOOL(x) ((bool)(x))
// STC_PRIMITIVE_END INT_TO_BOOL
// STC_PRIMITIVE_BEGIN BOOL_TO_INT
#define BOOL_TO_INT(x) ((int16_t)(x))
// STC_PRIMITIVE_END BOOL_TO_INT
// STC_PRIMITIVE_BEGIN DINT_TO_TIME
#define DINT_TO_TIME(x) ((int64_t)(x))
// STC_PRIMITIVE_END DINT_TO_TIME
// STC_PRIMITIVE_BEGIN TIME_TO_DINT
#define TIME_TO_DINT(x) ((int32_t)(x))
// STC_PRIMITIVE_END TIME_TO_DINT

// STC_PRIMITIVE_BEGIN STRING_SUPPORT
enum {
    STC_STRING_BUFFER_COUNT = 16,
    STC_STRING_BUFFER_SIZE = 1024
};

static STC_MAYBE_UNUSED _Thread_local char stc_string_buffers[STC_STRING_BUFFER_COUNT][STC_STRING_BUFFER_SIZE];
static STC_MAYBE_UNUSED _Thread_local unsigned int stc_string_buffer_index;

static STC_MAYBE_UNUSED inline char *stc_string_buffer(void)
{
    char *buffer = stc_string_buffers[stc_string_buffer_index];
    stc_string_buffer_index = (stc_string_buffer_index + 1u) % STC_STRING_BUFFER_COUNT;
    buffer[0] = '\0';
    return buffer;
}

static STC_MAYBE_UNUSED inline const char *stc_utf8_advance(const char *text, size_t characters)
{
    const unsigned char *cursor = (const unsigned char *)(text == NULL ? "" : text);
    while (*cursor != '\0' && characters > 0u) {
        ++cursor;
        while ((*cursor & 0xc0u) == 0x80u) {
            ++cursor;
        }
        --characters;
    }
    return (const char *)cursor;
}

static STC_MAYBE_UNUSED inline size_t stc_utf8_length(const char *text)
{
    size_t length = 0u;
    const unsigned char *cursor = (const unsigned char *)(text == NULL ? "" : text);
    while (*cursor != '\0') {
        if ((*cursor & 0xc0u) != 0x80u) {
            ++length;
        }
        ++cursor;
    }
    return length;
}

static STC_MAYBE_UNUSED inline const char *stc_string_compose(
    const char *prefix,
    size_t prefix_size,
    const char *middle,
    size_t middle_size,
    const char *suffix,
    size_t suffix_size)
{
    char *buffer = stc_string_buffer();
    size_t used = 0u;
    const char *parts[] = {prefix, middle, suffix};
    const size_t sizes[] = {prefix_size, middle_size, suffix_size};
    for (size_t index = 0u; index < 3u; ++index) {
        size_t available = STC_STRING_BUFFER_SIZE - 1u - used;
        size_t count = sizes[index] < available ? sizes[index] : available;
        if (count > 0u && parts[index] != NULL) {
            memcpy(buffer + used, parts[index], count);
            used += count;
        }
    }
    buffer[used] = '\0';
    return buffer;
}
// STC_PRIMITIVE_END STRING_SUPPORT

// STC_PRIMITIVE_BEGIN INT_TO_STRING STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *INT_TO_STRING(int16_t value)
{
    char *buffer = stc_string_buffer();
    snprintf(buffer, STC_STRING_BUFFER_SIZE, "%d", value);
    return buffer;
}
// STC_PRIMITIVE_END INT_TO_STRING

// STC_PRIMITIVE_BEGIN STRING_TO_INT
static STC_MAYBE_UNUSED inline int16_t STRING_TO_INT(const char *value)
{
    return value == NULL ? 0 : (int16_t)strtol(value, NULL, 10);
}
// STC_PRIMITIVE_END STRING_TO_INT

// STC_PRIMITIVE_BEGIN LEN STRING_SUPPORT
static STC_MAYBE_UNUSED inline int16_t LEN(const char *text)
{
    return (int16_t)stc_utf8_length(text);
}
// STC_PRIMITIVE_END LEN

// STC_PRIMITIVE_BEGIN LEN_CODE_UNIT
static STC_MAYBE_UNUSED inline int16_t LEN_CODE_UNIT(const char *text)
{
    return text == NULL ? 0 : (int16_t)strlen(text);
}
// STC_PRIMITIVE_END LEN_CODE_UNIT

// STC_PRIMITIVE_BEGIN MID STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *MID(const char *text, int length, int position)
{
    const char *start;
    const char *end;
    if (text == NULL || length <= 0 || position <= 0) {
        return "";
    }
    start = stc_utf8_advance(text, (size_t)(position - 1));
    if (*start == '\0') {
        return "";
    }
    end = stc_utf8_advance(start, (size_t)length);
    return stc_string_compose(start, (size_t)(end - start), NULL, 0u, NULL, 0u);
}
// STC_PRIMITIVE_END MID

// STC_PRIMITIVE_BEGIN LEFT STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *LEFT(const char *text, int length)
{
    const char *end;
    if (text == NULL || length <= 0) {
        return "";
    }
    end = stc_utf8_advance(text, (size_t)length);
    return stc_string_compose(text, (size_t)(end - text), NULL, 0u, NULL, 0u);
}
// STC_PRIMITIVE_END LEFT

// STC_PRIMITIVE_BEGIN RIGHT STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *RIGHT(const char *text, int length)
{
    size_t text_length;
    const char *start;
    if (text == NULL || length <= 0) {
        return "";
    }
    text_length = stc_utf8_length(text);
    start = stc_utf8_advance(text, text_length > (size_t)length ? text_length - (size_t)length : 0u);
    return stc_string_compose(start, strlen(start), NULL, 0u, NULL, 0u);
}
// STC_PRIMITIVE_END RIGHT

// STC_PRIMITIVE_BEGIN CONCAT STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *CONCAT(const char *left, const char *right)
{
    left = left == NULL ? "" : left;
    right = right == NULL ? "" : right;
    return stc_string_compose(left, strlen(left), right, strlen(right), NULL, 0u);
}
// STC_PRIMITIVE_END CONCAT

// STC_PRIMITIVE_BEGIN INSERT STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *INSERT(const char *text, const char *value, int position)
{
    const char *split;
    text = text == NULL ? "" : text;
    value = value == NULL ? "" : value;
    if (position < 0) {
        return "";
    }
    split = stc_utf8_advance(text, (size_t)position);
    return stc_string_compose(text, (size_t)(split - text), value, strlen(value), split, strlen(split));
}
// STC_PRIMITIVE_END INSERT

// STC_PRIMITIVE_BEGIN DELETE STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *DELETE(const char *text, int length, int position)
{
    const char *start;
    const char *end;
    text = text == NULL ? "" : text;
    if (length < 0 || position <= 0) {
        return "";
    }
    start = stc_utf8_advance(text, (size_t)(position - 1));
    end = stc_utf8_advance(start, (size_t)length);
    return stc_string_compose(text, (size_t)(start - text), end, strlen(end), NULL, 0u);
}
// STC_PRIMITIVE_END DELETE

// STC_PRIMITIVE_BEGIN REPLACE STRING_SUPPORT
static STC_MAYBE_UNUSED inline const char *REPLACE(const char *text, const char *value, int length, int position)
{
    const char *start;
    const char *end;
    text = text == NULL ? "" : text;
    value = value == NULL ? "" : value;
    if (length < 0 || position <= 0) {
        return "";
    }
    start = stc_utf8_advance(text, (size_t)(position - 1));
    end = stc_utf8_advance(start, (size_t)length);
    return stc_string_compose(text, (size_t)(start - text), value, strlen(value), end, strlen(end));
}
// STC_PRIMITIVE_END REPLACE

// STC_PRIMITIVE_BEGIN BCD_TO_INT
static STC_MAYBE_UNUSED inline int16_t BCD_TO_INT(uint16_t value)
{
    int16_t result = 0;
    int16_t factor = 1;
    while (value != 0u) {
        result += (int16_t)(value & 0x0fu) * factor;
        factor *= 10;
        value >>= 4;
    }
    return result;
}
// STC_PRIMITIVE_END BCD_TO_INT

// STC_PRIMITIVE_BEGIN INT_TO_BCD
static STC_MAYBE_UNUSED inline uint16_t INT_TO_BCD(int16_t value)
{
    uint16_t result = 0u;
    unsigned int shift = 0u;
    while (value > 0) {
        result |= (uint16_t)(value % 10) << shift;
        value /= 10;
        shift += 4u;
    }
    return result;
}
// STC_PRIMITIVE_END INT_TO_BCD

// STC_PRIMITIVE_BEGIN ASSERT
static STC_MAYBE_UNUSED inline void ASSERT(bool condition)
{
#ifndef NDEBUG
    if (!condition) {
        fputs("ST assertion failed\n", stderr);
        abort();
    }
#else
    (void)condition;
#endif
}
// STC_PRIMITIVE_END ASSERT
