import unittest

import typstcalc


class NativeTypstGridTests(unittest.TestCase):
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
