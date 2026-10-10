// Copyright (C) 2021-2026 Manuele Conti
// SPDX-License-Identifier: GPL-2.0-or-later
// STC_PRIMITIVE_BEGIN BYTE_ARRAY_SUPPORT
#[allow(dead_code)]
fn stc_bytes_encode<const N: usize>(text: &str, encoding: u8) -> [u8; N] {
    let payload: Vec<u8> = match encoding {
        1 => text
            .chars()
            .map(|value| { assert!((value as u32) <= 255, "STRING character exceeds one byte"); value as u8 })
            .collect(),
        2 => text.encode_utf16().flat_map(u16::to_le_bytes).collect(),
        _ => text.as_bytes().to_vec(),
    };
    assert!(
        payload.len() <= N,
        "Byte-array conversion destination is too small"
    );
    let mut out = [0; N];
    out[..payload.len()].copy_from_slice(&payload);
    out
}
#[allow(dead_code)]
fn stc_bytes_decode(bytes: &[u8], encoding: u8) -> &'static str {
    let text = match encoding {
        1 => bytes
            .iter()
            .take_while(|&&b| b != 0)
            .map(|&b| char::from(b))
            .collect::<String>(),
        2 => {
            let mut units = Vec::new();
            let mut i = 0;
            while i < bytes.len() {
                if i + 1 == bytes.len() {
                    assert_eq!(bytes[i], 0, "Incomplete UTF-16 code unit");
                    break;
                }
                let unit = u16::from_le_bytes([bytes[i], bytes[i + 1]]);
                if unit == 0 {
                    break;
                }
                units.push(unit);
                i += 2;
            }
            String::from_utf16(&units).expect("Invalid UTF-16 byte array")
        }
        _ => {
            let end = bytes.iter().position(|&b| b == 0).unwrap_or(bytes.len());
            std::str::from_utf8(&bytes[..end])
                .expect("Invalid UTF-8 byte array")
                .to_owned()
        }
    };
    Box::leak(text.into_boxed_str())
}

// STC_PRIMITIVE_END BYTE_ARRAY_SUPPORT

// STC_PRIMITIVE_BEGIN STRING_TO_ARRAY_OF_BYTE BYTE_ARRAY_SUPPORT
#[allow(non_snake_case)]
fn STRING_TO_ARRAY_OF_BYTE<const N: usize>(text: &str) -> [u8; N] { stc_bytes_encode(text, 1) }
// STC_PRIMITIVE_END STRING_TO_ARRAY_OF_BYTE

// STC_PRIMITIVE_BEGIN ARRAY_OF_BYTE_TO_STRING BYTE_ARRAY_SUPPORT
#[allow(non_snake_case)]
fn ARRAY_OF_BYTE_TO_STRING(bytes: &[u8]) -> &'static str { stc_bytes_decode(bytes, 1) }
// STC_PRIMITIVE_END ARRAY_OF_BYTE_TO_STRING

// STC_PRIMITIVE_BEGIN WSTRING_TO_ARRAY_OF_BYTE BYTE_ARRAY_SUPPORT
#[allow(non_snake_case)]
fn WSTRING_TO_ARRAY_OF_BYTE<const N: usize>(text: &str) -> [u8; N] { stc_bytes_encode(text, 2) }
// STC_PRIMITIVE_END WSTRING_TO_ARRAY_OF_BYTE

// STC_PRIMITIVE_BEGIN ARRAY_OF_BYTE_TO_WSTRING BYTE_ARRAY_SUPPORT
#[allow(non_snake_case)]
fn ARRAY_OF_BYTE_TO_WSTRING(bytes: &[u8]) -> &'static str { stc_bytes_decode(bytes, 2) }
// STC_PRIMITIVE_END ARRAY_OF_BYTE_TO_WSTRING

// STC_PRIMITIVE_BEGIN USTRING_TO_ARRAY_OF_BYTE BYTE_ARRAY_SUPPORT
#[allow(non_snake_case)]
fn USTRING_TO_ARRAY_OF_BYTE<const N: usize>(text: &str) -> [u8; N] { stc_bytes_encode(text, 3) }
// STC_PRIMITIVE_END USTRING_TO_ARRAY_OF_BYTE

// STC_PRIMITIVE_BEGIN ARRAY_OF_BYTE_TO_USTRING BYTE_ARRAY_SUPPORT
#[allow(non_snake_case)]
fn ARRAY_OF_BYTE_TO_USTRING(bytes: &[u8]) -> &'static str { stc_bytes_decode(bytes, 3) }
// STC_PRIMITIVE_END ARRAY_OF_BYTE_TO_USTRING
