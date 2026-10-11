// Copyright (C) 2021-2026 Manuele Conti
// SPDX-License-Identifier: GPL-2.0-or-later
// Portable Rust primitives embedded into generated crates by STC.

// STC_PRIMITIVE_BEGIN CORE
// Target-independent algorithms remain in stdlib/standard-functions.st.
// STC_PRIMITIVE_END CORE

// STC_PRIMITIVE_BEGIN AND
#[allow(non_snake_case)]
fn AND<T>(left: T, right: T) -> T
where
    T: std::ops::BitAnd<Output = T>,
{
    left & right
}
// STC_PRIMITIVE_END AND

// STC_PRIMITIVE_BEGIN BCD_TO_INT
#[allow(non_snake_case)]
fn BCD_TO_INT(mut value: u16) -> i16 {
    let mut result: i16 = 0;
    let mut factor: i16 = 1;
    while value != 0 {
        result += ((value & 0x0f) as i16) * factor;
        factor *= 10;
        value >>= 4;
    }
    result
}
// STC_PRIMITIVE_END BCD_TO_INT

// STC_PRIMITIVE_BEGIN INT_TO_BCD
#[allow(non_snake_case)]
fn INT_TO_BCD(mut value: i16) -> u16 {
    let mut result: u16 = 0;
    let mut shift: u32 = 0;
    while value > 0 {
        result |= ((value % 10) as u16) << shift;
        value /= 10;
        shift += 4;
    }
    result
}
// STC_PRIMITIVE_END INT_TO_BCD

// STC_PRIMITIVE_BEGIN STRING_SUPPORT
// Shared string helpers for allocating IEC string operations.
// Generated Rust keeps the borrowed `&'static str` ABI: composed results
// are leaked to match the C ring-buffer temporary semantics.
#[allow(non_snake_case)]
fn stc_leak(text: String) -> &'static str {
    Box::leak(text.into_boxed_str())
}
// STC_PRIMITIVE_END STRING_SUPPORT

// STC_PRIMITIVE_BEGIN STC_STRING_CHECK
#[allow(non_snake_case, dead_code)]
fn STC_STRING_CHECK(text: &'static str, capacity: usize, wide: bool) -> &'static str {
    let length = if wide { text.encode_utf16().count() } else { text.chars().count() };
    assert!(length <= capacity, "stc: string capacity exceeded");
    text
}
// STC_PRIMITIVE_END STC_STRING_CHECK

// STC_PRIMITIVE_BEGIN LEN
#[allow(non_snake_case)]
fn LEN(text: &'static str) -> i16 {
    text.chars().count() as i16
}
// STC_PRIMITIVE_END LEN

// STC_PRIMITIVE_BEGIN LEN_CODE_UNIT
#[allow(non_snake_case, dead_code)]
fn LEN_CODE_UNIT(text: &'static str) -> i16 {
    text.len() as i16
}
// STC_PRIMITIVE_END LEN_CODE_UNIT

// STC_PRIMITIVE_BEGIN WSTRING_LEN_CODE_UNIT
#[allow(non_snake_case, dead_code)]
fn WSTRING_LEN_CODE_UNIT(text: &'static str) -> i16 {
    text.chars()
        .map(|value| if (value as u32) > 0xFFFF { 2 } else { 1 })
        .sum::<usize>() as i16
}
// STC_PRIMITIVE_END WSTRING_LEN_CODE_UNIT

// STC_PRIMITIVE_BEGIN MID
#[allow(non_snake_case)]
fn MID(text: &'static str, length: i16, position: i16) -> &'static str {
    if length <= 0 || position <= 0 {
        return "";
    }

    let start = match text.char_indices().nth((position - 1) as usize) {
        Some((index, _)) => index,
        None => return "",
    };
    let end = text[start..]
        .char_indices()
        .nth(length as usize)
        .map(|(index, _)| start + index)
        .unwrap_or(text.len());
    &text[start..end]
}
// STC_PRIMITIVE_END MID

// STC_PRIMITIVE_BEGIN LEFT
#[allow(non_snake_case)]
fn LEFT(text: &'static str, length: i16) -> &'static str {
    if length <= 0 {
        return "";
    }
    match text.char_indices().nth(length as usize) {
        Some((index, _)) => &text[..index],
        None => text,
    }
}
// STC_PRIMITIVE_END LEFT

// STC_PRIMITIVE_BEGIN RIGHT
#[allow(non_snake_case)]
fn RIGHT(text: &'static str, length: i16) -> &'static str {
    if length <= 0 {
        return "";
    }
    let count = text.chars().count();
    if length as usize >= count {
        return text;
    }
    match text.char_indices().nth(count - length as usize) {
        Some((index, _)) => &text[index..],
        None => text,
    }
}
// STC_PRIMITIVE_END RIGHT

// STC_PRIMITIVE_BEGIN CONCAT STRING_SUPPORT
#[allow(non_snake_case)]
fn CONCAT(left: &'static str, right: &'static str) -> &'static str {
    stc_leak(format!("{left}{right}"))
}
// STC_PRIMITIVE_END CONCAT

// STC_PRIMITIVE_BEGIN INSERT STRING_SUPPORT
#[allow(non_snake_case)]
fn INSERT(text: &'static str, value: &'static str, position: i16) -> &'static str {
    if position < 0 {
        return "";
    }
    let split = text
        .char_indices()
        .nth(position as usize)
        .map(|(index, _)| index)
        .unwrap_or(text.len());
    stc_leak(format!("{}{}{}", &text[..split], value, &text[split..]))
}
// STC_PRIMITIVE_END INSERT

// STC_PRIMITIVE_BEGIN DELETE STRING_SUPPORT
#[allow(non_snake_case)]
fn DELETE(text: &'static str, length: i16, position: i16) -> &'static str {
    if length < 0 || position <= 0 {
        return "";
    }
    let start = text
        .char_indices()
        .nth((position - 1) as usize)
        .map(|(index, _)| index)
        .unwrap_or(text.len());
    let end = text[start..]
        .char_indices()
        .nth(length as usize)
        .map(|(index, _)| start + index)
        .unwrap_or(text.len());
    stc_leak(format!("{}{}", &text[..start], &text[end..]))
}
// STC_PRIMITIVE_END DELETE

// STC_PRIMITIVE_BEGIN REPLACE STRING_SUPPORT
#[allow(non_snake_case)]
fn REPLACE(text: &'static str, value: &'static str, length: i16, position: i16) -> &'static str {
    if length < 0 || position <= 0 {
        return "";
    }
    let start = text
        .char_indices()
        .nth((position - 1) as usize)
        .map(|(index, _)| index)
        .unwrap_or(text.len());
    let end = text[start..]
        .char_indices()
        .nth(length as usize)
        .map(|(index, _)| start + index)
        .unwrap_or(text.len());
    stc_leak(format!("{}{}{}", &text[..start], value, &text[end..]))
}
// STC_PRIMITIVE_END REPLACE

// STC_PRIMITIVE_BEGIN ASSERT
#[allow(non_snake_case)]
fn ASSERT(condition: bool) {
    if cfg!(debug_assertions) && !condition {
        panic!("ST assertion failed");
    }
}
// STC_PRIMITIVE_END ASSERT
