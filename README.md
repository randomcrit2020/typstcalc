# typstcalc

`typstcalc` is an IPython cell magic for engineering calculations in Jupyter
and Quarto notebooks. It evaluates Python expressions and emits
Typst-compatible MiTeX equations showing the symbolic expression, substituted
values, units, and final result.

## Rendering pipeline

For now, `typstcalc` uses a LaTeX-based intermediate representation rather
than generating native Typst math directly:

1. Python and Pint evaluate the expression and handle quantities and units.
2. The expression renderer uses SymPy's LaTeX printer where needed to produce
   LaTeX mathematical notation for symbols, values, and equations.
3. The magic wraps that notation in a raw Typst `#mitex(...)` block.
4. During Typst compilation, the MiTeX package interprets the LaTeX math and
   converts it into content that Typst can render.

In short: **Python/Pint calculation → SymPy/LaTeX notation → MiTeX → Typst**.
No LaTeX engine or separate LaTeX compilation step is required.

## Requirements

- Python with IPython
- [Pint](https://pint.readthedocs.io/) for quantities and units
- [SymPy](https://www.sympy.org/) for mathematical symbols and LaTeX output
- Typst with the MiTeX package when rendering the generated raw Typst blocks

Install the Python dependencies in a project managed by `uv`:

```powershell
uv add ipython pint sympy
```

Place `typstcalc.py` in the notebook's working directory or elsewhere on the
Python import path. Load it once near the beginning of the notebook:

```python
%load_ext typstcalc
```

The extension adds `ureg`, `Q_`, `sqrt`, trigonometric helpers, `mag`, and
other calculation helpers to the notebook namespace.

## Basic calculation

Use `%%typstcalc define` for input values:

```python
%%typstcalc define
f_c = 50 * ureg.MPa  # symbol=f'_c | Concrete strength
b = 300 * ureg.mm    # Member width
h = 600 * ureg.mm    # Member depth
```

Use `%%typstcalc` for derived calculations. The rendered equation includes
the formula, numerical substitution, and result:

```python
%%typstcalc
A_g = b * h >> ureg.mm**2  # Gross section area
E_c = 4700 * sqrt(mag(f_c, ureg.MPa)) * ureg.MPa >> ureg.GPa  # Elastic modulus
```

The `>> unit` suffix converts the evaluated Pint quantity before it is stored
and displayed.

## Mathematical expressions

Normal Python arithmetic is supported, including `+`, `-`, `*`, `/`,
parentheses, and powers written with `**`:

```python
%%typstcalc define
L = 4 * ureg.m       # Length
b = 300 * ureg.mm    # Width
h = 600 * ureg.mm    # Height
```

In a new cell:

```python
%%typstcalc
A = b * h >> ureg.mm**2       # Area
I = b * h**3 / 12 >> ureg.mm**4  # Second moment of area
```

The extension currently recognizes these mathematical helpers:

- `sqrt(x)`
- `sin(x)`, `cos(x)`, `tan(x)`, and `cot(x)`
- `abs(x)`
- `ceil(x)` and `floor(x)`
- `max(...)` and `min(...)`

Example:

```python
%%typstcalc define
x = 9                         # Dimensionless value
theta = 30 * ureg.degree      # Angle
V_1 = -12 * ureg.kN           # Signed force
V_2 = 18 * ureg.kN            # Second force
n = 3.2                       # Dimensionless count
```

In a new cell:

```python
%%typstcalc
root_x = sqrt(x)               # Square root
s_theta = sin(theta)           # Sine
c_theta = cos(theta)           # Cosine
V_abs = abs(V_1)               # Absolute value
V_max = max(V_1, V_2)          # Maximum
n_up = ceil(n)                 # Round upward
n_down = floor(n)              # Round downward
```

The trigonometric helpers accept plain radians or Pint angle quantities such
as `30 * ureg.degree`. For dimensional quantities, convert to a magnitude
before applying a function that expects a plain number:

```python
%%typstcalc
E_c = 4700 * sqrt(mag(f_c, ureg.MPa)) * ureg.MPa >> ureg.GPa
```

Here, `mag(f_c, ureg.MPa)` converts `f_c` to MPa and returns its numerical
magnitude. The expression then reapplies the correct output unit.

### Adding another function

A new function must be available to Python and understood by both equation
rendering passes. For example, to add natural logarithms as `ln(x)`:

1. Define the evaluator near the other helpers:

   ```python
   def ln(value):
       return math.log(value)
   ```

2. Add it to the notebook namespace inside `register`:

   ```python
   namespace.setdefault("ln", ln)
   ```

3. Add an `ast.Call` branch to both `_symbol_latex_from_ast` and
   `_value_latex_from_ast`, rendering the function as `\ln\left(...\right)`.

After those additions, it can be used normally:

```python
%%typstcalc
y = ln(x)  # Natural logarithm
```

Defining a Python function in the notebook is sufficient for evaluation but
not for equation output; unsupported call syntax is intentionally rejected by
the renderer.

## Symbols and descriptions

Comments control presentation without changing the Python variable name:

```python
%%typstcalc
phi_V_n = 0.75 * 420 * ureg.kN  # symbol=\phi V_n | Design shear resistance
```

- `# Description` adds an explanatory note.
- `# symbol=E_c` changes only the displayed mathematical symbol.
- `# symbol=E_c | Description` sets both the symbol and note.

### Greek letters

Variable names are passed through SymPy's LaTeX printer. The following
lowercase names render automatically as Greek letters:

GitHub Markdown uses MathJax for the previews in the **Rendered symbols**
column. This README rendering is only a visual reference; notebook output
still follows the SymPy/LaTeX → MiTeX → Typst pipeline described above.

| Python names | Rendered symbols |
| --- | --- |
| `alpha`, `beta`, `gamma`, `delta` | $\alpha,\ \beta,\ \gamma,\ \delta$ |
| `epsilon`, `zeta`, `eta`, `theta` | $\epsilon,\ \zeta,\ \eta,\ \theta$ |
| `iota`, `kappa`, `mu`, `nu` | $\iota,\ \kappa,\ \mu,\ \nu$ |
| `xi`, `pi`, `rho`, `sigma`, `tau` | $\xi,\ \pi,\ \rho,\ \sigma,\ \tau$ |
| `upsilon`, `phi`, `chi`, `psi`, `omega` | $\upsilon,\ \phi,\ \chi,\ \psi,\ \omega$ |

`omicron` is accepted but renders as the Latin letter `o`, since the glyphs
are identical. `lambda` renders as `\lambda`, but `lambda` is a reserved Python
keyword and cannot be used as the left side of an assignment. Use a safe
Python name with a display override instead:

```python
%%typstcalc define
lambda_value = 1.15  # symbol=\lambda | Slenderness factor
```

The uppercase names with distinct Greek glyphs are:

| Python name | Rendered | Python name | Rendered |
| --- | --- | --- | --- |
| `Gamma` | $\Gamma$ | `Delta` | $\Delta$ |
| `Theta` | $\Theta$ | `Lambda` | $\Lambda$ |
| `Xi` | $\Xi$ | `Pi` | $\Pi$ |
| `Sigma` | $\Sigma$ | `Upsilon` | $\Upsilon$ |
| `Phi` | $\Phi$ | `Psi` | $\Psi$ |
| `Omega` | $\Omega$ |  |  |

Other uppercase Greek names render as upright Latin letters because their
usual mathematical glyphs are identical to Latin capitals.

Variant forms are also recognized:

| Python name | Rendered | Python name | Rendered |
| --- | --- | --- | --- |
| `varepsilon` | $\varepsilon$ | `vartheta` | $\vartheta$ |
| `varpi` | $\varpi$ | `varrho` | $\varrho$ |
| `varsigma` | $\varsigma$ | `varphi` | $\varphi$ |

Underscores create subscripts automatically:

```python
%%typstcalc define
alpha_1 = 0.85                 # Displays as \alpha_1
theta_max = 45 * ureg.degree   # Displays as \theta_{max}
phi_n = 0.75                   # Displays as \phi_n
```

For any notation that is awkward or invalid as a Python identifier, use
`symbol=` with raw LaTeX/MiTeX notation:

```python
%%typstcalc
rho_prime = 0.012  # symbol=\rho' | Compression reinforcement ratio
```

## Reusing a previous value

Write a previously calculated variable without `=` to display it again. An
optional description can follow `|`:

```python
%%typstcalc define
A_g | Gross section area used in the resistance check
```

## Long expressions

Add `wrap` to split long function argument lists into shorter rendered lines:

```python
%%typstcalc wrap
V_u = max(V_dead, V_live, V_wind, V_seismic)  # Governing shear demand
```

Equivalent option names include `breaks`, `linebreaks`, and `autobreaks`.

## Typst preamble

Generated output uses raw Typst blocks containing `#calc-block[#mitex(...)]`.
The Typst document therefore needs definitions similar to:

```typst
#import "@preview/mitex:0.2.7": *

#let calc-block(body) = block(
  width: 100%,
  above: 12pt,
  below: 12pt,
)[#scale(x: 100%, y: 100%, reflow: true)[#body]]
```

The magic automatically divides large aligned equation groups into
page-friendly blocks.
