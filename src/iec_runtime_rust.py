# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Provide Rust runtime fragments for IEC standard operations."""


BCD_TO_INT_RUNTIME = """\
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
"""

INT_TO_BCD_RUNTIME = """\
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
"""

RUST_RUNTIME_FUNCTIONS = {
    "BCD_TO_INT": BCD_TO_INT_RUNTIME,
    "INT_TO_BCD": INT_TO_BCD_RUNTIME,
}
