"""IPython cell magic for handcalcs-style Typst/MiTeX calculation output.

Load in a notebook with:

    %load_ext typstcalc

Then use:

    %%typstcalc define
    f_c = 50 * ureg.MPa  # symbol=f'_c | Concrete strength

    %%typstcalc
    E_c = 4700 * sqrt(mag(f_c, ureg.MPa)) * ureg.MPa >> ureg.GPa  # Elastic modulus

Comment syntax after "#":

    # Explanation only
    # symbol=f'_c
    # symbol=E_c | Explanation rendered in the aligned comment column

"symbol=" is only for display. It tells the magic what LaTeX/SymPy symbol to
print on the left-hand side, while the Python variable name remains the name
before "=". For example, Python uses f_c, but the equation can display f'_c.

Use ">> unit" at the end of an expression to convert the calculated Pint
quantity before it is displayed and stored, e.g. ">> ureg.GPa".

To print a value that was already defined or calculated in an earlier
%%typstcalc cell, write the variable name without "=":

    A_s_8 | Area of reinforcement # 8
"""

import ast
import math
import re
from dataclasses import dataclass

import sympy as sp
from IPython.display import Markdown, display
from pint import Quantity, UnitRegistry

ureg = UnitRegistry()
Q_ = ureg.Quantity
sqrt = math.sqrt
ceil = math.ceil
floor = math.floor
calc_max = max
calc_vars = {}

# Function names that should render as a mathematical maximum.  The older
# calc_max name is kept for notebooks that already used it, while plain max(...)
# lets new cells read like normal Python.
MAX_FUNCTION_NAMES = {"max", "calc_max"}
MIN_FUNCTION_NAMES = {"min"}
TRIG_FUNCTION_NAMES = {"sin", "cos", "tan", "cot"}
TRIG_LATEX = {"sin": r"\sin", "cos": r"\cos", "tan": r"\tan", "cot": r"\cot"}
# MiTeX aligned environments are indivisible once they reach Typst.  Keeping
# each generated block short gives the page builder frequent, useful break
# points and avoids both bottom-margin overflow and avoidable half-empty pages.
MAX_ALIGNED_ROWS_PER_BLOCK = 9
WRAPPED_FUNCTION_ARGS_PER_ROW = 2


@dataclass
class CalcVar:
    name: str
    symbol: sp.Symbol
    value: object
    description: str = ""
    display_latex: str = ""

    @property
    def latex(self):
        if self.display_latex:
            return self.display_latex
        return sp.latex(self.symbol)


def _calc_var(name, symbol_text, value, description):
    """Create a calculation variable with an optional display-only symbol.

    Plain names such as "f_c" can safely go through SymPy's printer. Composite
    LaTeX snippets such as "E_{s} A_{s}" should be preserved literally so they
    render as products instead of a single odd-looking symbol.
    """
    symbol_text = symbol_text or name
    display_latex = ""
    if any(token in symbol_text for token in ("\\", "{", "}", " ")):
        display_latex = symbol_text
    return CalcVar(name, sp.Symbol(symbol_text), value, description, display_latex)


def mag(value, unit):
    # Pint quantities need conversion before their magnitude is used inside
    # math functions. Plain numbers can appear after guards such as max(x, 0);
    # in that case they are already dimensionless magnitudes.
    if not hasattr(value, "to"):
        return value
    return value.to(unit).magnitude


def _angle_radians(value):
    if hasattr(value, "to"):
        return value.to(ureg.radian).magnitude
    return value


def sin(value):
    return math.sin(_angle_radians(value))


def cos(value):
    return math.cos(_angle_radians(value))


def tan(value):
    return math.tan(_angle_radians(value))


def cot(value):
    return 1 / tan(value)


def q_latex(value, digits=4):
    if isinstance(value, Quantity):
        if value.dimensionless:
            return f"{value.magnitude:.{digits}g}"
        return format(value, f".{digits}g~L")
    if isinstance(value, sp.Basic):
        return sp.latex(value)
    if isinstance(value, (int, float)):
        return f"{value:.{digits}g}"
    return str(value)


def _needs_group(node):
    return isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub))


def _is_mul_div(node):
    return isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div))


def _unit_from_ast(node):
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "ureg":
            return getattr(ureg, node.attr)
    if isinstance(node, ast.BinOp):
        left = _unit_from_ast(node.left)
        right = _unit_from_ast(node.right)
        if isinstance(node.op, ast.Pow) and left is not None and isinstance(node.right, ast.Constant):
            return left ** node.right.value
        if isinstance(node.op, ast.Mult) and left is not None and right is not None:
            return left * right
        if isinstance(node.op, ast.Div) and left is not None and right is not None:
            return left / right
    return None


def _unit_latex_from_ast(node):
    unit = _unit_from_ast(node)
    if unit is None:
        return None
    return format(unit, "~L")


def _wrap_latex(text):
    return rf"\left({text}\right)"


def _needs_power_wrap_latex(text):
    return "/" in text or text.startswith(r"\frac")


def mitex_block(latex):
    # The notebook preamble defines calc-block(...) as the Typst formatting
    # wrapper for generated equations. Keeping spacing in that Typst helper
    # avoids hardcoding vertical #v(...) gaps in every generated output.
    return "```{=typst}\n#calc-block[#mitex(`" + latex + "`)]\n```"


def aligned_block(rows):
    blocks = []
    for chunk in _chunk_aligned_rows(rows):
        blocks.append(mitex_block("\\begin{aligned}\n" + (r"\\" + "\n").join(chunk) + "\n\\end{aligned}"))
    return "\n\n".join(blocks)


def _chunk_aligned_rows(rows):
    """Split aligned output into page-friendly, approximately balanced blocks.

    A normal variable calculation stays together.  Exceptionally long
    calculations are divided into balanced continuation blocks because a
    single MiTeX ``aligned`` environment cannot break across Typst pages.
    """
    groups = []
    group = []
    for row in rows:
        starts_new_variable = not row.lstrip().startswith("&=")
        if starts_new_variable and group:
            groups.append(group)
            group = []
        group.append(row)
    if group:
        groups.append(group)

    page_groups = []
    for group in groups:
        if len(group) <= MAX_ALIGNED_ROWS_PER_BLOCK:
            page_groups.append(group)
            continue

        part_count = math.ceil(len(group) / MAX_ALIGNED_ROWS_PER_BLOCK)
        base_size, extra = divmod(len(group), part_count)
        start = 0
        for part_index in range(part_count):
            part_size = base_size + (1 if part_index < extra else 0)
            page_groups.append(group[start : start + part_size])
            start += part_size

    chunks = []
    chunk = []
    for group in page_groups:
        if chunk and len(chunk) + len(group) > MAX_ALIGNED_ROWS_PER_BLOCK:
            chunks.append(chunk)
            chunk = []
        chunk.extend(group)
    if chunk:
        chunks.append(chunk)
    return chunks


def register(ipython):
    """Register the %%typstcalc magic in an IPython shell."""
    namespace = ipython.user_ns
    namespace.setdefault("ureg", ureg)
    namespace.setdefault("Q_", Q_)
    namespace.setdefault("sqrt", sqrt)
    namespace.setdefault("ceil", ceil)
    namespace.setdefault("floor", floor)
    namespace.setdefault("max", max)
    namespace.setdefault("calc_max", calc_max)
    namespace.setdefault("mag", mag)
    namespace.setdefault("sin", sin)
    namespace.setdefault("cos", cos)
    namespace.setdefault("tan", tan)
    namespace.setdefault("cot", cot)
    namespace.setdefault("calc_vars", calc_vars)

    def typstcalc(line, cell):
        options = set(line.strip().lower().split())
        define_mode = bool(options & {"define", "definitions", "defs", "vars"})
        wrap_functions = bool(options & {"wrap", "breaks", "linebreaks", "autobreaks", "auto-breaks", "cortes"})
        rows = []
        calc_rows = []

        for raw_line in cell.splitlines():
            if not raw_line.strip():
                continue
            reference = _parse_reference_line(raw_line)
            if reference is not None:
                name, description = reference
                calc_var = _lookup_calc_var(name, namespace, description)
                if define_mode:
                    rows.append(_definition_row(calc_var))
                else:
                    calc_rows.append(_definition_row(calc_var))
                continue

            code, comment = _split_code_comment(raw_line)
            if not code:
                continue
            name, expression = _split_assignment(code)
            expression, unit_expression = _split_conversion(expression)
            # Inline comments control presentation:
            #   # plain text
            #       Adds the plain text as an aligned explanation.
            #   # symbol=E_c
            #       Uses E_c as the rendered left-hand symbol instead of the
            #       Python variable name. This is handy when the Python-safe
            #       name differs from the math notation, e.g. f_c -> f'_c.
            #   # symbol=E_c | Elastic modulus
            #       Uses the symbol before the pipe and the explanation after it.
            symbol_text, description = _parse_comment(comment)

            result = eval(expression, namespace)
            if unit_expression:
                # ">> unit" means: evaluate first, then convert the Pint result
                # to the requested display unit before saving and rendering.
                result = result.to(eval(unit_expression, namespace))

            namespace[name] = result
            calc_vars[name] = _calc_var(name, symbol_text, result, description)

            if define_mode:
                rows.append(_definition_row(calc_vars[name]))
            else:
                calc_rows.extend(_calculation_rows(calc_vars[name], expression, result, namespace, wrap_functions=wrap_functions))

        if define_mode and rows:
            display(Markdown(aligned_block(rows)))
        elif calc_rows:
            display(Markdown(aligned_block(calc_rows)))

    ipython.register_magic_function(typstcalc, "cell", "typstcalc")


def load_ipython_extension(ipython):
    register(ipython)


def _latex_text(text):
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    return "".join(replacements.get(char, char) for char in text)


def _comment_latex(text):
    pieces = []
    math_token = re.compile(
        r"[A-Za-z]+_\s*[A-Za-z0-9]+(?:\s*/\s*[A-Za-z]+)?|#\d+|#"
    )
    cursor = 0
    for match in math_token.finditer(text):
        if match.start() > cursor:
            pieces.append(f"\\text{{{_latex_text(text[cursor:match.start()])}}}")
        token = match.group(0)
        if token.startswith("#"):
            pieces.append(r"\#" + token[1:])
        else:
            pieces.append(_comment_math_latex(token))
        cursor = match.end()
    if cursor < len(text):
        pieces.append(f"\\text{{{_latex_text(text[cursor:])}}}")
    return r"\ ".join(piece for piece in pieces if piece)


def _comment_math_latex(token):
    token = re.sub(r"\s+", "", token)
    if "/" in token:
        variable, denominator = token.split("/", 1)
    else:
        variable, denominator = token, ""
    if "_" in variable:
        base, subscript = variable.split("_", 1)
        variable_latex = f"{base}_{{{subscript}}}" if len(subscript) > 1 else f"{base}_{subscript}"
    else:
        variable_latex = variable
    if denominator:
        denominator_latex = rf"\mathrm{{{denominator}}}" if denominator.isalpha() else denominator
        return rf"{variable_latex}/{denominator_latex}"
    return variable_latex


def _short_description(text):
    """Return a compact label that fits beside hand-calculation equations.

    Known calculation notes are abbreviated explicitly. Unknown notes are kept
    whole so the document never silently renders clipped labels.
    """
    text = " ".join(text.split())
    replacements = [
        ("Factor de resistencia del acero de refuerzo", "Factor resistencia acero"),
        ("Fluencia del acero Grade 60", "Fluencia acero G60"),
        ("Área nominal de barra #6", "Área barra #6"),
        ("Diámetro nominal de barra #6", "Diámetro barra #6"),
        ("Separación longitudinal de barras embebidas del proveedor", "Separación barras"),
        ("Longitud longitudinal de caja de apoyo", "Longitud caja apoyo"),
        ("Coeficiente de fricción para superficie rugosa", "Coef. fricción"),
        ("Separación máxima en zonas de frenado/sesgo", "Sep. máx. frenado/sesgo"),
        ("Longitud recta mínima de embebido", "Long. mín. embebido"),
        ("Factor de distribución de carga adoptado", "Factor distribución"),
        ("Multiplicador dinámico total para cargas de rueda", "Factor dinámico"),
        ("Longitud efectiva conservadora de distribución longitudinal", "Longitud efectiva"),
        ("Ancho local AASHTO para carga de rueda sobre MBJS", "Ancho rueda AASHTO"),
        ("Separación transversal entre ruedas de un eje", "Sep. ruedas eje"),
        ("Separación real entre barras embebidas usada como longitud tributaria", "Separación tributaria"),
        ("Carga vertical de rueda para caso local de resistencia", "Rueda vertical resistencia"),
        ("Relación entre carga horizontal y carga vertical de rueda", "Relación H/V"),
        ("Carga vertical de rueda para Fatiga I", "Rueda vertical fatiga"),
        ("Carga vertical de eje para Fatiga I", "Eje vertical fatiga"),
        ("Factor de carga para Fatiga I", "Factor fatiga I"),
        ("Profundidad total de caja de apoyo del proveedor", "Altura caja"),
        ("Brazo vertical entre capas de barras embebidas", "Brazo z"),
        ("Separación real entre barras expresada en pies", "Separación en ft"),
        ("Cuantía de anclajes por metro lineal", "Anclajes por m"),
        ("Multiplicador dinámico total para carga de rueda", "Factor dinámico"),
        ("Carga vertical factorizada, caso distribuido por eje", "Vertical eje"),
        ("Carga horizontal factorizada, caso distribuido por eje", "Horizontal eje"),
        ("Carga vertical factorizada, caso local por rueda", "Vertical rueda"),
        ("Carga horizontal factorizada, caso local por rueda", "Horizontal rueda"),
        ("Envolvente vertical factorizada de resistencia por metro lineal", "Envolvente vertical/m"),
        ("Envolvente horizontal factorizada de resistencia por metro lineal", "Envolvente horizontal/m"),
        ("Carga vertical factorizada de resistencia por metro lineal", "Vertical resistencia/m"),
        ("Carga horizontal factorizada de resistencia por metro lineal", "Horizontal resistencia/m"),
        ("Carga vertical factorizada por metro lineal", "Carga vertical/m"),
        ("Carga horizontal factorizada por metro lineal", "Carga horizontal/m"),
        ("Carga vertical total para Fatiga I", "Carga fatiga total"),
        ("Carga vertical total de eje para Fatiga I", "Fatiga total eje"),
        ("Carga vertical total de rueda para Fatiga I", "Fatiga total rueda"),
        ("Carga vertical de fatiga por metro lineal", "Carga fatiga/m"),
        ("Carga vertical de fatiga, caso distribuido por eje", "Fatiga eje"),
        ("Carga vertical de fatiga, caso local por rueda", "Fatiga rueda"),
        ("Envolvente vertical de fatiga por metro lineal", "Envolvente fatiga/m"),
        ("Carga vertical factorizada equivalente por anclaje", "Vertical por anclaje"),
        ("Carga horizontal factorizada equivalente por anclaje", "Horizontal por anclaje"),
        ("Carga vertical factorizada equivalente por anclaje con cuantía continua", "Vertical/barra continua"),
        ("Carga horizontal factorizada equivalente por anclaje con cuantía continua", "Horizontal/barra continua"),
        ("Barras completas bajo el ancho local de rueda", "Barras bajo rueda"),
        ("Reacción vertical total bajo el ancho local de rueda", "Reacción V local"),
        ("Reacción horizontal total bajo el ancho local de rueda", "Reacción H local"),
        ("Carga vertical por barra en chequeo local discreto", "V/barra local"),
        ("Carga horizontal por barra en chequeo local discreto", "H/barra local"),
        ("Envolvente vertical de diseño por barra", "V diseño/barra"),
        ("Envolvente horizontal de diseño por barra", "H diseño/barra"),
        ("Carga vertical de fatiga equivalente por anclaje", "Fatiga por anclaje"),
        ("Carga vertical de fatiga equivalente por anclaje con cuantía continua", "Fatiga/barra continua"),
        ("Cortante de diseño por metro lineal para la revisión de anclajes", "Cortante diseño/m"),
        ("Cortante de diseño por metro lineal para revisión de anclajes", "Cortante diseño/m"),
        ("Tensión de diseño por metro lineal para la revisión de anclajes", "Tensión diseño/m"),
        ("Tensión directa horizontal por metro lineal", "Tensión directa/m"),
        ("Tensión directa horizontal, caso distribuido por eje", "Tensión directa eje"),
        ("Tensión directa horizontal, caso local por rueda", "Tensión directa rueda"),
        ("Carga horizontal por caja de apoyo", "Horizontal por caja"),
        ("Momento de volcamiento por caja de apoyo", "Volcamiento caja"),
        ("Tensión por volcamiento en la caja de apoyo", "Tensión por brazo z"),
        ("Tensión por volcamiento equivalente por metro lineal", "Tensión por z/m"),
        ("Tensión por volcamiento, caso distribuido por eje", "Tensión z eje"),
        ("Tensión por volcamiento, caso local por rueda", "Tensión z rueda"),
        ("Tensión máxima de diseño por metro lineal", "Tensión máxima/m"),
        ("Tensión máxima equivalente por anclaje", "Tensión máx./anclaje"),
        ("Tensión máxima equivalente por anclaje con cuantía continua", "Tensión/barra continua"),
        ("Tensión total por volcamiento bajo ancho local de rueda", "Tensión z local"),
        ("Tensión por barra en chequeo local discreto", "Tensión/barra local"),
        ("Envolvente de tensión de diseño por barra", "Tensión diseño/barra"),
        ("Demanda vertical por posición transversal del detalle de dos barras", "Vertical por posición (2 barras)"),
        ("Demanda vertical total transferida al grupo completo de la caja", "Vertical total del grupo"),
        ("Carga vertical redistribuida sobre ancho conservador de caja", "Vertical sobre ancho de caja"),
        ("Carga vertical factorizada final por metro lineal", "Vertical final/m"),
        ("Carga horizontal factorizada final por metro lineal", "Horizontal final/m"),
        ("Carga vertical final de fatiga por metro lineal", "Fatiga final/m"),
        ("Carga vertical equivalente por anclaje", "Vertical/anclaje"),
        ("Carga horizontal equivalente por anclaje", "Horizontal/anclaje"),
        ("Área requerida de acero por metro lineal", "A_s/m requerido"),
        ("Área provista por metro lineal con barras #6 a 150 mm", "A_s/m provisto"),
        ("Demanda/capacidad por cuantía de acero por metro", "D/C A_s/m"),
        ("Resistencia de diseño a tensión de una barra #6", "Resistencia T barra"),
        ("Demanda/capacidad de tensión por barra", "D/C T barra"),
        ("Separación real en pulgadas", "Separación en in"),
        ("Separación real respecto al límite de 9 in", "D/C separación"),
        ("Rango de esfuerzo vertical por fatiga con cuantía por metro", "Esfuerzo fatiga"),
        ("Demanda/capacidad por fatiga vertical", "D/C fatiga"),
        ("Demanda/capacidad por fatiga vertical con cuantía continua", "D/C fatiga continua"),
        ("Reacción vertical de fatiga bajo el ancho local de rueda", "Reacción fatiga local"),
        ("Fatiga vertical por barra en chequeo local discreto", "Fatiga/barra local"),
        ("Rango de esfuerzo vertical por fatiga en barra local", "Esfuerzo fatiga barra"),
        ("Demanda/capacidad de fatiga por barra local", "D/C fatiga barra"),
        ("Envolvente demanda/capacidad por fatiga", "D/C fatiga diseño"),
        ("Resistencia a tensión por metro lineal de barras embebidas", "Resistencia tensión/m"),
        ("Resistencia por fricción cortante por metro lineal", "Resistencia cortante/m"),
        ("Resistencia simplificada por fricción cortante por metro lineal", "Resistencia cortante/m"),
        ("Demanda/capacidad por tensión distribuida", "D/C tensión"),
        ("Demanda/capacidad por cortante distribuido", "D/C cortante"),
        ("Índice de interacción tensión-cortante por metro lineal", "Interacción T/V"),
        ("Cohesión preliminar para AASHTO 5.7.4, pendiente de confirmar", "Cohesión preliminar"),
        ("Fuerza compresiva conservadora para AASHTO 5.7.4", "Compresión conservadora"),
        ("Factor preliminar para fricción cortante AASHTO 5.7.4", "Factor fricción AASHTO"),
        ("Fluencia limitada a 60 ksi para interface shear", "Fy interfaz"),
        ("Margen por cuantía de acero provista por metro", "Margen A_s"),
        ("Margen de fatiga vertical", "Margen fatiga"),
        ("Margen de fatiga vertical de diseño", "Margen fatiga"),
        ("Margen de interacción tensión-cortante", "Margen T/V"),
        ("Margen de separación en zonas de frenado/sesgo", "Margen separación"),
        ("Demanda de soldadura por tensión horizontal en una barra", "Tensión horizontal por barra"),
        ("Demanda por tensión horizontal en una barra", "Tensión horizontal por barra"),
        ("Cortante vertical total de caja distribuido como tensión entre todas las barras verticales", "Vertical de caja distribuida por barra"),
        ("Cortante vertical total de caja distribuido como tensión por barra", "Vertical de caja por barra"),
        ("Demanda envolvente de soldadura por barra", "Demanda gobernante por barra"),
        ("Factor direccional para carga paralela al cordón, theta=0 grados", "Factor direccional, carga paralela"),
        ("Factor direccional para carga transversal al cordón, theta=90 grados", "Factor direccional, carga a 90 grados"),
        ("Resistencia base factorizada por unidad de longitud", "Resistencia base de soldadura"),
        ("Resistencia por unidad de longitud con carga paralela", "Resistencia/longitud, carga paralela"),
        ("Resistencia por unidad de longitud con carga a 90 grados", "Resistencia/longitud, carga a 90 grados"),
        ("Menor resistencia por unidad de longitud adoptada", "Resistencia/longitud gobernante"),
        ("Menor resistencia factorizada con longitud adoptada", "Resistencia mínima con longitud adoptada"),
        ("Longitud por tensión horizontal y carga paralela al cordón", "Longitud horizontal, carga paralela"),
        ("Longitud por tensión horizontal y carga paralela", "Longitud horizontal, carga paralela"),
        ("Longitud por tensión horizontal y carga a 90 grados", "Longitud horizontal, carga a 90 grados"),
        ("Longitud por cortante vertical distribuido y carga paralela al cordón", "Longitud vertical, carga paralela"),
        ("Longitud por cortante vertical distribuido y carga paralela", "Longitud vertical, carga paralela"),
        ("Longitud por cortante vertical distribuido y carga a 90 grados", "Longitud vertical, carga a 90 grados"),
        ("Longitud requerida por la menor capacidad direccional", "Longitud requerida gobernante"),
        ("D/C por tensión horizontal con carga paralela", "D/C horizontal, carga paralela"),
        ("D/C tensión horizontal con carga paralela", "D/C horizontal, carga paralela"),
        ("D/C por tensión horizontal con carga a 90 grados", "D/C horizontal, carga a 90 grados"),
        ("D/C tensión horizontal con carga a 90 grados", "D/C horizontal, carga a 90 grados"),
        ("D/C por cortante vertical distribuido con carga paralela", "D/C vertical, carga paralela"),
        ("D/C cortante vertical distribuido con carga paralela", "D/C vertical, carga paralela"),
        ("D/C por cortante vertical distribuido con carga a 90 grados", "D/C vertical, carga a 90 grados"),
        ("D/C cortante vertical distribuido con carga a 90 grados", "D/C vertical, carga a 90 grados"),
    ]
    for long, short in replacements:
        if text == long:
            return short
    return text


def _note_latex(description):
    if not description:
        return ""
    return f" && \\quad {_comment_latex(_short_description(description))}"


def _parse_comment(comment):
    comment = comment.strip()
    if not comment:
        return None, ""
    if comment.startswith("symbol="):
        body = comment.removeprefix("symbol=").strip()
        if "|" in body:
            symbol, description = body.split("|", 1)
            return symbol.strip(), description.strip()
        return body.strip(), ""
    return None, comment


def _parse_reference_line(line):
    line = line.strip()
    if "=" in line:
        return None
    if "|" in line:
        name, description = line.split("|", 1)
        return name.strip(), description.strip()
    return line, ""


def _lookup_calc_var(name, namespace, description=""):
    if name in calc_vars:
        previous = calc_vars[name]
        return CalcVar(
            name=previous.name,
            symbol=previous.symbol,
            value=namespace.get(name, previous.value),
            description=description or previous.description,
            display_latex=previous.display_latex,
        )
    if name in namespace:
        return CalcVar(name, sp.Symbol(name), namespace[name], description)
    raise NameError(f"No previous typstcalc variable named {name!r}")


def _split_code_comment(line):
    if "#" not in line:
        return line.strip(), ""
    code, comment = line.split("#", 1)
    return code.strip(), comment.strip()


def _split_assignment(code):
    if "=" not in code:
        raise ValueError(f"Expected an assignment in: {code}")
    name, expression = code.split("=", 1)
    return name.strip(), expression.strip()


def _split_conversion(expression):
    if ">>" not in expression:
        return expression.strip(), None
    expression, unit_expression = expression.split(">>", 1)
    return expression.strip(), unit_expression.strip()


def _sympy_from_ast(node, used_names):
    if isinstance(node, ast.Constant):
        return sp.sympify(node.value)
    if isinstance(node, ast.Name):
        if node.id in calc_vars:
            used_names.add(node.id)
            return calc_vars[node.id].symbol
        return sp.Symbol(node.id)
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "ureg":
            return sp.Integer(1)
        return sp.Symbol(node.attr)
    if isinstance(node, ast.UnaryOp):
        value = _sympy_from_ast(node.operand, used_names)
        return -value if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left = _sympy_from_ast(node.left, used_names)
        right = _sympy_from_ast(node.right, used_names)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            return sp.sqrt(_sympy_from_ast(node.args[0], used_names))
        if isinstance(node.func, ast.Name) and node.func.id in TRIG_FUNCTION_NAMES:
            return getattr(sp, node.func.id)(_sympy_from_ast(node.args[0], used_names))
        if isinstance(node.func, ast.Name) and node.func.id == "ceil":
            return sp.ceiling(_sympy_from_ast(node.args[0], used_names))
        if isinstance(node.func, ast.Name) and node.func.id == "floor":
            return sp.floor(_sympy_from_ast(node.args[0], used_names))
        if isinstance(node.func, ast.Name) and node.func.id == "abs":
            return sp.Abs(_sympy_from_ast(node.args[0], used_names))
        if isinstance(node.func, ast.Name) and node.func.id in MAX_FUNCTION_NAMES:
            return sp.Max(*[_sympy_from_ast(arg, used_names) for arg in node.args])
        if isinstance(node.func, ast.Name) and node.func.id in MIN_FUNCTION_NAMES:
            return sp.Min(*[_sympy_from_ast(arg, used_names) for arg in node.args])
        if isinstance(node.func, ast.Name) and node.func.id == "mag":
            return _sympy_from_ast(node.args[0], used_names)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "to":
            return _sympy_from_ast(node.func.value, used_names)
    raise ValueError(f"Unsupported expression syntax: {ast.unparse(node)}")


def _symbolic_expr(expression):
    node = ast.parse(expression, mode="eval").body
    used_names = set()
    return _sympy_from_ast(node, used_names), used_names


def _wrap_function_args(args, args_per_row=WRAPPED_FUNCTION_ARGS_PER_ROW):
    """Render long function argument lists in stacked rows."""
    if len(args) <= args_per_row:
        return ", ".join(args)
    rows = []
    for index in range(0, len(args), args_per_row):
        rows.append(", ".join(args[index : index + args_per_row]))
    return r"\substack{" + r"\\".join(rows) + "}"


def _symbol_latex_from_ast(node, wrap_functions=False):
    unit_latex = _unit_latex_from_ast(node)
    if unit_latex is not None:
        return unit_latex
    if isinstance(node, ast.Constant):
        return q_latex(node.value)
    if isinstance(node, ast.Name):
        if node.id in calc_vars:
            return calc_vars[node.id].latex
        return sp.latex(sp.Symbol(node.id))
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "ureg":
            return ""
        return sp.latex(sp.Symbol(node.attr))
    if isinstance(node, ast.UnaryOp):
        value = _symbol_latex_from_ast(node.operand, wrap_functions)
        return f"-{value}" if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        left = _symbol_latex_from_ast(node.left, wrap_functions)
        right = _symbol_latex_from_ast(node.right, wrap_functions)
        if isinstance(node.op, ast.Add):
            return rf"{left} + {right}"
        if isinstance(node.op, ast.Sub):
            return rf"{left} - {right}"
        if isinstance(node.op, ast.Mult):
            if _unit_latex_from_ast(node.left) is not None or _unit_latex_from_ast(node.right) is not None:
                return r"\ ".join(part for part in (left, right) if part)
            return " ".join(part for part in (left, right) if part)
        if isinstance(node.op, ast.Div):
            return rf"\frac{{{left}}}{{{right}}}"
        if isinstance(node.op, ast.Pow):
            if isinstance(node.left, ast.BinOp) or _needs_power_wrap_latex(left):
                left = _wrap_latex(left)
            return rf"{left}^{{{right}}}"
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            return rf"\sqrt{{{_symbol_latex_from_ast(node.args[0], wrap_functions)}}}"
        if isinstance(node.func, ast.Name) and node.func.id in TRIG_FUNCTION_NAMES:
            func_latex = TRIG_LATEX[node.func.id]
            return rf"{func_latex}\left({_symbol_latex_from_ast(node.args[0], wrap_functions)}\right)"
        if isinstance(node.func, ast.Name) and node.func.id == "ceil":
            return rf"\left\lceil {_symbol_latex_from_ast(node.args[0], wrap_functions)} \right\rceil"
        if isinstance(node.func, ast.Name) and node.func.id == "floor":
            return rf"\left\lfloor {_symbol_latex_from_ast(node.args[0], wrap_functions)} \right\rfloor"
        if isinstance(node.func, ast.Name) and node.func.id == "abs":
            return rf"\left|{_symbol_latex_from_ast(node.args[0], wrap_functions)}\right|"
        if isinstance(node.func, ast.Name) and node.func.id in MAX_FUNCTION_NAMES:
            args = [_symbol_latex_from_ast(arg, wrap_functions) for arg in node.args]
            args = _wrap_function_args(args) if wrap_functions else ", ".join(args)
            return rf"\max\left({args}\right)"
        if isinstance(node.func, ast.Name) and node.func.id in MIN_FUNCTION_NAMES:
            args = [_symbol_latex_from_ast(arg, wrap_functions) for arg in node.args]
            args = _wrap_function_args(args) if wrap_functions else ", ".join(args)
            return rf"\min\left({args}\right)"
        if isinstance(node.func, ast.Name) and node.func.id == "mag":
            return _symbol_latex_from_ast(node.args[0], wrap_functions)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "to":
            return _symbol_latex_from_ast(node.func.value, wrap_functions)
    raise ValueError(f"Unsupported expression syntax: {ast.unparse(node)}")


def _symbolic_latex(expression, wrap_functions=False):
    node = ast.parse(expression, mode="eval").body
    return _symbol_latex_from_ast(node, wrap_functions)


def _value_latex_from_ast(node, namespace, digits=4, inline_div=False, wrap_functions=False):
    unit_latex = _unit_latex_from_ast(node)
    if unit_latex is not None:
        return unit_latex
    if isinstance(node, ast.Constant):
        return q_latex(node.value, digits)
    if isinstance(node, ast.Name):
        if node.id in calc_vars:
            return q_latex(calc_vars[node.id].value, digits)
        return sp.latex(sp.Symbol(node.id))
    if isinstance(node, ast.Attribute):
        if isinstance(node.value, ast.Name) and node.value.id == "ureg":
            return ""
        return sp.latex(sp.Symbol(node.attr))
    if isinstance(node, ast.UnaryOp):
        value = _value_latex_from_ast(node.operand, namespace, digits, inline_div, wrap_functions)
        return f"-{value}" if isinstance(node.op, ast.USub) else value
    if isinstance(node, ast.BinOp):
        use_inline_div = inline_div or (isinstance(node.op, ast.Div) and (_is_mul_div(node.left) or _is_mul_div(node.right)))
        left = _value_latex_from_ast(node.left, namespace, digits, use_inline_div, wrap_functions)
        right = _value_latex_from_ast(node.right, namespace, digits, use_inline_div, wrap_functions)
        if isinstance(node.op, ast.Add):
            return rf"{left} + {right}"
        if isinstance(node.op, ast.Sub):
            return rf"{left} - {right}"
        if isinstance(node.op, ast.Mult):
            if _unit_latex_from_ast(node.left) is not None or _unit_latex_from_ast(node.right) is not None:
                return r"\ ".join(part for part in (left, right) if part)
            return r" \cdot ".join(part for part in (left, right) if part)
        if isinstance(node.op, ast.Div):
            if _needs_group(node.left) or _needs_group(node.right):
                return rf"\frac{{{left}}}{{{right}}}"
            if use_inline_div:
                if isinstance(node.left, ast.BinOp) and isinstance(node.left.op, ast.Div):
                    left = _wrap_latex(left)
                if isinstance(node.right, ast.BinOp):
                    right = _wrap_latex(right)
                return rf"{left} / {right}"
            return rf"\frac{{{left}}}{{{right}}}"
        if isinstance(node.op, ast.Pow):
            if (
                isinstance(node.left, ast.BinOp)
                or (isinstance(node.left, ast.Name) and node.left.id in calc_vars)
                or _needs_power_wrap_latex(left)
            ):
                left = _wrap_latex(left)
            return rf"{left}^{{{right}}}"
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id == "sqrt":
            return rf"\sqrt{{{_value_latex_from_ast(node.args[0], namespace, digits, inline_div, wrap_functions)}}}"
        if isinstance(node.func, ast.Name) and node.func.id in TRIG_FUNCTION_NAMES:
            func_latex = TRIG_LATEX[node.func.id]
            arg = _value_latex_from_ast(node.args[0], namespace, digits, inline_div, wrap_functions)
            return rf"{func_latex}\left({arg}\right)"
        if isinstance(node.func, ast.Name) and node.func.id == "ceil":
            return rf"\left\lceil {_value_latex_from_ast(node.args[0], namespace, digits, inline_div, wrap_functions)} \right\rceil"
        if isinstance(node.func, ast.Name) and node.func.id == "floor":
            return rf"\left\lfloor {_value_latex_from_ast(node.args[0], namespace, digits, inline_div, wrap_functions)} \right\rfloor"
        if isinstance(node.func, ast.Name) and node.func.id == "abs":
            return rf"\left|{_value_latex_from_ast(node.args[0], namespace, digits, inline_div, wrap_functions)}\right|"
        if isinstance(node.func, ast.Name) and node.func.id in MAX_FUNCTION_NAMES:
            args = [_value_latex_from_ast(arg, namespace, digits, inline_div, wrap_functions) for arg in node.args]
            args = _wrap_function_args(args) if wrap_functions else ", ".join(args)
            return rf"\max\left({args}\right)"
        if isinstance(node.func, ast.Name) and node.func.id in MIN_FUNCTION_NAMES:
            args = [_value_latex_from_ast(arg, namespace, digits, inline_div, wrap_functions) for arg in node.args]
            args = _wrap_function_args(args) if wrap_functions else ", ".join(args)
            return rf"\min\left({args}\right)"
        if isinstance(node.func, ast.Name) and node.func.id == "mag":
            return q_latex(eval(ast.unparse(node), namespace), digits)
        if isinstance(node.func, ast.Attribute) and node.func.attr == "to":
            return _value_latex_from_ast(node.func.value, namespace, digits, inline_div, wrap_functions)
    raise ValueError(f"Unsupported expression syntax: {ast.unparse(node)}")


def _substituted_latex(expression, namespace, digits=4, wrap_functions=False):
    node = ast.parse(expression, mode="eval").body
    return _value_latex_from_ast(node, namespace, digits, wrap_functions=wrap_functions)


def _definition_row(calc_var, digits=4):
    return rf"{calc_var.latex} &= {q_latex(calc_var.value, digits)}{_note_latex(calc_var.description)}"


def _calculation_rows(lhs, expression, result, namespace, digits=4, wrap_functions=False):
    symbolic = _symbolic_latex(expression, wrap_functions)
    substituted = _substituted_latex(expression, namespace, digits, wrap_functions)
    final = q_latex(result, digits)
    note = _note_latex(lhs.description)
    if symbolic == substituted == final:
        return [rf"{lhs.latex} &= {symbolic}{note}"]
    if substituted == final:
        return [
            rf"{lhs.latex} &= {symbolic}{note}",
            rf"&= {final}",
        ]
    return [
        rf"{lhs.latex} &= {symbolic}{note}",
        rf"&= {substituted}",
        rf"&= {final}",
    ]
