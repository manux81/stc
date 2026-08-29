"""Sequential Function Chart parsing, validation, and target lowering."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from stc.compiler import compile_source


SFC_PROGRAM = """\
PROGRAM Conveyor
VAR_INPUT start : BOOL; END_VAR
VAR_OUTPUT idle, running : BOOL; END_VAR
INITIAL_STEP Idle: idle(N); END_STEP
TRANSITION StartTransition (PRIORITY := 0) FROM Idle TO Run := start; END_TRANSITION
STEP Run: running(N); END_STEP
TRANSITION FROM Run TO Idle := NOT start; END_TRANSITION
END_PROGRAM
"""


class SequentialFunctionChartTests(unittest.TestCase):
    def test_sfc_is_supported_by_all_profiles_and_targets(self):
        for edition in ("ed2", "ed3", "ed4"):
            for target in ("c", "rust"):
                with self.subTest(edition=edition, target=target):
                    result = compile_source(SFC_PROGRAM, target, standard=edition)
                    self.assertTrue(result.success, result.diagnostics or result.syntax_error)
                    self.assertIn("__sfc_idle_active", result.output)
                    self.assertIn("__sfc_run_elapsed_ms", result.output)

    def test_parallel_divergence_and_convergence_parse(self):
        source = """\
PROGRAM Parallel
VAR_INPUT proceed : BOOL; END_VAR
INITIAL_STEP S0: END_STEP
TRANSITION FROM S0 TO (S1, S2) := proceed; END_TRANSITION
STEP S1: END_STEP
STEP S2: END_STEP
TRANSITION FROM (S1, S2) TO S0 := NOT proceed; END_TRANSITION
END_PROGRAM
"""
        result = compile_source(source, "c", standard="ed4")
        self.assertTrue(result.success, result.diagnostics or result.syntax_error)
        self.assertIn("self->__sfc_s1_active = true", result.output)
        self.assertIn("self->__sfc_s2_active = true", result.output)

    def test_action_qualifiers_and_inline_action_lowering(self):
        source = """\
PROGRAM Actions
VAR_OUTPUT output, indicator : BOOL; END_VAR
INITIAL_STEP S0: Work(P1, indicator); output(L, T#10ms); END_STEP
TRANSITION FROM S0 TO S1 := TRUE; END_TRANSITION
STEP S1: Work(S); END_STEP
ACTION Work: output := TRUE; END_ACTION
END_PROGRAM
"""
        for target in ("c", "rust"):
            with self.subTest(target=target):
                result = compile_source(source, target, standard="ed3")
                self.assertTrue(result.success, result.diagnostics or result.syntax_error)
                self.assertIn("__sfc_action_work_stored", result.output)

    def test_all_standard_action_qualifiers_parse(self):
        associations = " ".join(
            ["out();"]
            + [f"out({qualifier});" for qualifier in ("N", "R", "S", "P", "P0", "P1")]
            + [f"out({qualifier}, T#1ms);" for qualifier in ("L", "D", "SD", "DS", "SL")]
        )
        source = f"""\
PROGRAM Qualifiers
VAR_OUTPUT out : BOOL; END_VAR
INITIAL_STEP Start: {associations} END_STEP
END_PROGRAM
"""
        result = compile_source(source, "c", standard="ed2")
        self.assertTrue(result.success, result.diagnostics or result.syntax_error)

    def test_structural_errors_are_diagnostics(self):
        cases = {
            "unknown-sfc-step": SFC_PROGRAM.replace("TO Run", "TO Missing", 1),
            "invalid-sfc-action-qualifier": SFC_PROGRAM.replace("idle(N)", "idle(Q)"),
            "missing-sfc-action-time": SFC_PROGRAM.replace("idle(N)", "idle(D)"),
            "unknown-sfc-action": SFC_PROGRAM.replace("idle(N)", "missing(N)"),
        }
        for expected, source in cases.items():
            with self.subTest(expected=expected):
                result = compile_source(source, "c", standard="ed3")
                self.assertFalse(result.success)
                self.assertIn(expected, {item.code for item in result.diagnostics})

    def test_generated_program_executes_step_transitions(self):
        compiler = shutil.which("cc") or shutil.which("clang") or shutil.which("gcc")
        if compiler is None:
            self.skipTest("No C compiler is available")
        result = compile_source(SFC_PROGRAM, "c", standard="ed2")
        self.assertTrue(result.success, result.diagnostics or result.syntax_error)
        harness = """
int main(void) {
    Conveyor state;
    Conveyor_cold_init(&state);
    Conveyor_run(&state);
    if (!state.idle || state.running) return 1;
    state.start = true;
    Conveyor_run(&state);
    if (state.idle || !state.running) return 2;
    state.start = false;
    Conveyor_run(&state);
    return (!state.idle || state.running) ? 3 : 0;
}
"""
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "sfc.c")
            executable = Path(directory, "sfc")
            source.write_text(result.output + harness)
            subprocess.run([compiler, "-std=c11", str(source), "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True)


if __name__ == "__main__":
    unittest.main()
