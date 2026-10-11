# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Decode IEC character literals without interpreting escaped dollars twice."""
import re


def decode_character_literal(raw):
    raw = raw.strip()
    prefix, _, quoted = raw.partition("#") if raw[0] not in {'"', "'"} else ("", "", raw)
    quoted = quoted.strip()
    quote = quoted[0]
    content = quoted[1:-1]
    width = 4 if prefix.strip().upper() in {"WSTRING", "WCHAR"} or quote == '"' else 2
    pattern = re.compile(
        rf"\$\{{([0-9A-Fa-f]{{1,6}})\}}|\$([0-9A-Fa-f]{{{width}}})|"
        rf"\$([$'\"LlNnPpRrTt])|{re.escape(quote * 2)}"
    )
    controls = {"L": "\n", "N": "\n", "P": "\f", "R": "\r", "T": "\t"}

    def replace(match):
        encoded = match.group(1) or match.group(2)
        if encoded is not None:
            code = int(encoded, 16)
            # Match the existing recovery behavior for invalid braced Unicode scalars.
            if match.group(1) is not None and (code > 0x10FFFF or 0xD800 <= code <= 0xDFFF):
                return "\ufffd"
            return chr(code)
        escaped = match.group(3)
        return controls.get(escaped.upper(), escaped) if escaped else quote

    return pattern.sub(replace, content)
