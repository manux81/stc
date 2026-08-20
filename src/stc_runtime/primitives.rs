// Copyright (C) 2021-2026 Manuele Conti
// SPDX-License-Identifier: GPL-2.0-or-later
// Portable Rust primitives embedded into generated crates by STC.

// STC_PRIMITIVE_BEGIN CORE
// Target-independent algorithms remain in library/standard-functions.st.
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

// STC_PRIMITIVE_BEGIN LEN
#[allow(non_snake_case)]
fn LEN(text: &'static str) -> i16 {
    text.chars().count() as i16
}
// STC_PRIMITIVE_END LEN

// STC_PRIMITIVE_BEGIN LEN_CODE_UNIT
#[allow(non_snake_case)]
fn LEN_CODE_UNIT(text: &'static str) -> i16 {
    text.len() as i16
}
// STC_PRIMITIVE_END LEN_CODE_UNIT

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

// STC_PRIMITIVE_BEGIN ASSERT
#[allow(non_snake_case)]
fn ASSERT(condition: bool) {
    if cfg!(debug_assertions) && !condition {
        panic!("ST assertion failed");
    }
}
// STC_PRIMITIVE_END ASSERT
