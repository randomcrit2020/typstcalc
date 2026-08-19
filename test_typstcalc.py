import unittest
from unittest.mock import patch

import typstcalc


class NativeTypstGridTests(unittest.TestCase):
    def test_automatic_preamble_reserves_height_for_tall_mitex_rows(self):
        self.assertIn("#let calc-block", typstcalc.TYPST_PREAMBLE)
        self.assertIn("inset: (top: 4pt, bottom: 4pt)", typstcalc.TYPST_PREAMBLE)

    def test_magic_emits_automatic_preamble_only_once(self):
        class FakeIPython:
            def __init__(self):
                self.user_ns = {}
                self.magic = None

            def register_magic_function(self, function, *_args):
                self.magic = function

        shell = FakeIPython()
        with patch.object(typstcalc, "display") as mocked_display:
            typstcalc.register(shell)
            shell.magic("define", "auto_preamble_a = 2")
            shell.magic("", "auto_preamble_b = auto_preamble_a + 1")

        first_output = mocked_display.call_args_list[0].args[0].data
        second_output = mocked_display.call_args_list[1].args[0].data
        self.assertIn("#let calc-block", first_output)
        self.assertNotIn("#let calc-block", second_output)
        self.assertIn("#calc-block", first_output)
        self.assertIn("#calc-block", second_output)

    def test_manual_preamble_option_suppresses_automatic_template(self):
        class FakeIPython:
            def __init__(self):
                self.user_ns = {}
                self.magic = None

            def register_magic_function(self, function, *_args):
                self.magic = function

        shell = FakeIPython()
        with patch.object(typstcalc, "display") as mocked_display:
            typstcalc.register(shell)
            shell.magic("define no-preamble", "manual_preamble_a = 2")

        output = mocked_display.call_args.args[0].data
        self.assertNotIn("#let calc-block", output)
        self.assertIn("#calc-block", output)

    def test_comment_parses_symbol_label_and_description(self):
        symbol, description, label = typstcalc._parse_comment(
            r"symbol=\frac{q_2}{q_1}; label=eq-capacity-ratio | Capacity ratio"
        )

        self.assertEqual(symbol, r"\frac{q_2}{q_1}")
        self.assertEqual(description, "Capacity ratio")
        self.assertEqual(label, "eq-capacity-ratio")

    def test_comment_rejects_invalid_typst_label(self):
        with self.assertRaisesRegex(ValueError, "Typst equation labels"):
            typstcalc._parse_comment("label=eq capacity")

    def test_reprinting_variable_does_not_duplicate_equation_label(self):
        name = "numbered_value_for_reprint_test"
        previous = typstcalc._calc_var(
            name, "x", 3, "Original equation", "eq-original-equation"
        )
        typstcalc.calc_vars[name] = previous
        try:
            reprinted = typstcalc._lookup_calc_var(name, {name: 3})
        finally:
            typstcalc.calc_vars.pop(name, None)

        self.assertEqual(reprinted.equation_label, "")

    def test_explicit_fraction_display_symbol_preserves_latex(self):
        variable = typstcalc._calc_var(
            name="ratio_q_explicit",
            symbol_text=r"\frac{q_2}{q_1}",
            value=0.5,
            description="Capacity ratio",
        )

        self.assertEqual(variable.latex, r"\frac{q_2}{q_1}")

    def test_definition_rows_keep_math_and_comment_separate(self):
        variable = typstcalc.CalcVar(
            name="force",
            symbol=typstcalc.sp.Symbol("F"),
            value=12 * typstcalc.ureg.kN,
            description="Applied force",
        )

        row = typstcalc._definition_row(variable)

        self.assertEqual(row.lhs, "F")
        self.assertEqual(row.rhs, r"12\ \mathrm{kN}")
        self.assertEqual(row.description, "Applied force")

    def test_calculation_rows_mark_only_the_first_row_as_a_new_variable(self):
        lhs = typstcalc.CalcVar(
            name="area",
            symbol=typstcalc.sp.Symbol("A"),
            value=6,
            description="Calculated area",
        )
        namespace = {"b": 2, "h": 3}

        rows = typstcalc._calculation_rows(lhs, "b * h", 6, namespace)

        self.assertTrue(rows[0].starts_new_variable)
        self.assertEqual(rows[0].description, "Calculated area")
        self.assertTrue(all(not row.starts_new_variable for row in rows[1:]))

    def test_typst_block_groups_equation_trails_and_uses_safe_strings(self):
        rows = [
            typstcalc.CalcRow("a", "x + y", 'Quoted "note" #1'),
            typstcalc.CalcRow("", "3"),
            typstcalc.CalcRow("b", r"\frac{1}{2}", ""),
        ]

        output = typstcalc.typst_calc_block(rows)

        self.assertIn(
            '(mitex("\\\\begin{aligned}\\na &= x + y\\\\\\\\\\n&= 3\\n\\\\end{aligned}"), "Quoted \\"note\\" #1")',
            output,
        )
        self.assertIn(
            '(mitex("\\\\begin{aligned}\\nb &= \\\\frac{1}{2}\\n\\\\end{aligned}"), none)',
            output,
        )
        self.assertNotIn(r"\text{Quoted", output)

    def test_typst_block_emits_label_only_for_numbered_equation(self):
        rows = [
            typstcalc.CalcRow(
                "a", "x + y", "Numbered note", "eq-numbered-result"
            ),
            typstcalc.CalcRow("", "3"),
            typstcalc.CalcRow("b", "4", "Unnumbered note"),
        ]

        output = typstcalc.typst_calc_block(rows)

        self.assertIn(', "Numbered note", "eq-numbered-result"),', output)
        self.assertIn(', "Unnumbered note"),', output)
        self.assertNotIn('"Unnumbered note", "', output)

    def test_balancing_preserves_complete_three_row_calculations(self):
        rows = []
        for index in range(4):
            rows.extend(
                (
                    typstcalc.CalcRow(f"x_{index}", "formula", f"Note {index}"),
                    typstcalc.CalcRow("", "substitution"),
                    typstcalc.CalcRow("", "result"),
                )
            )

        chunks = typstcalc._chunk_aligned_rows(rows, max_rows=9)

        self.assertEqual([len(chunk) for chunk in chunks], [6, 6])
        self.assertTrue(all(chunk[0].starts_new_variable for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
