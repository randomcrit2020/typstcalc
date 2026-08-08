# typstcalc

`typstcalc` is an IPython cell magic for engineering calculations in Jupyter
and Quarto notebooks. It evaluates Python expressions and emits
Typst-compatible MiTeX equations showing the symbolic expression, substituted
values, units, and final result.

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

## Symbols and descriptions

Comments control presentation without changing the Python variable name:

```python
%%typstcalc
phi_V_n = 0.75 * 420 * ureg.kN  # symbol=\phi V_n | Design shear resistance
```

- `# Description` adds an explanatory note.
- `# symbol=E_c` changes only the displayed mathematical symbol.
- `# symbol=E_c | Description` sets both the symbol and note.

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
