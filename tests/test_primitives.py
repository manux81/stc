# Copyright (C) 2021-2026 Manuele Conti
# SPDX-License-Identifier: GPL-2.0-or-later
"""Verify external target primitives and selective runtime emission."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.compiler import compile_source
from stc.runtime.loader import render_primitives


class PrimitiveRuntimeTests(unittest.TestCase):
    def test_loader_resolves_dependencies_and_omits_unused_blocks(self):
        runtime = render_primitives("c", {"MID"})

        self.assertIn("stc_utf8_advance", runtime)
        self.assertIn("const char *MID", runtime)
        self.assertNotIn("INT_TO_BCD", runtime)
        self.assertNotIn("ST assertion failed", runtime)

    def test_generated_output_embeds_only_referenced_primitives(self):
        source = """\
FUNCTION Slice : STRING
VAR_INPUT Text : STRING; END_VAR
Slice := MID(Text, 2, 1);
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed3")

        self.assertTrue(result.success, result.diagnostics)
        self.assertIn("const char *MID", result.output)
        self.assertNotIn("static inline uint16_t INT_TO_BCD", result.output)
        self.assertNotIn("ST assertion failed", result.output)

    def test_c_string_primitives_follow_table_34_examples(self):
        compiler = shutil.which("cc")
        if compiler is None:
            self.skipTest("A C compiler is not installed")
        source = """\
FUNCTION VerifyStrings : BOOL
VAR Text : STRING; END_VAR
Text := 'ABC';
VerifyStrings := LEFT(Text, 2) = 'AB'
    AND RIGHT(Text, 2) = 'BC'
    AND MID(Text, 1, 2) = 'B'
    AND INSERT(Text, 'XY', 2) = 'ABXYC'
    AND DELETE('ABXYC', 2, 3) = 'ABC'
    AND REPLACE('ABCDE', 'X', 2, 3) = 'ABXE';
END_FUNCTION
"""
        result = compile_source(source, "c", standard="ed3")
        self.assertTrue(result.success, result.diagnostics)

        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            generated = root / "generated.c"
            generated.write_text(result.output, encoding="utf-8")
            harness = root / "harness.c"
            harness.write_text(
                '#include "generated.c"\nint main(void) { return VerifyStrings() ? 0 : 1; }\n',
                encoding="utf-8",
            )
            executable = root / "primitive-test"
            subprocess.run(
                [compiler, "-std=c11", str(harness), "-o", str(executable)],
                check=True,
                capture_output=True,
                text=True,
            )
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
