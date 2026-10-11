# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Quote decoded IEC text for the reference target languages."""


def quote_string(content, control_escape):
    escapes = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}
    return '"' + ''.join(escapes.get(char, control_escape(ord(char))
                           if ord(char) < 32 or ord(char) == 127 else char)
                         for char in content) + '"'


def c_string_literal(content):
    return quote_string(content, lambda code: f"\\{code:03o}")


def rust_string_literal(content):
    return quote_string(content, lambda code: f"\\u{{{code:x}}}")
