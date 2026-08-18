# MCP Service Documentation

## Project Overview
This service is based on the SymPy library and aims to provide symbolic mathematics functionality, including symbolic computation, algebraic operations, calculus, equation solving, polynomial operations, and mathematical functions. The interface is simple and easy to use, suitable for developers to quickly integrate mathematical computation features.

## Installation
1. Please ensure that you have a Python environment installed.
2. Install dependencies:
   ```
   pip install sympy
   pip install mpmath
   # (Optional) pip install numpy
   # (Optional) pip install scipy
   # (Optional) pip install matplotlib
   ```

## Quick Start

```python
from sympy import symbols, solve, diff, integrate

# Create symbolic variables
x, y = symbols('x y')

# Solve an equation
solution = solve(x**2 - 1, x)

# Differentiate
derivative = diff(x**3, x)

# Integrate
integral = integrate(x**2, x)
```

## Main Tools and Endpoints
- `symbols`: Create symbolic variables
- `expand`: Expand expressions
- `simplify`: Simplify expressions
- `solve`: Solve equations
- `linsolve`: Solve linear systems of equations
- `diff`: Differentiate
- `integrate`: Integrate
- `Poly`: Create polynomials
- `factor`: Factor polynomials
- `sin`, `cos`, `exp`: Mathematical functions

## Common Issues and Notes
- Please ensure all dependencies are installed correctly to avoid runtime errors.
- Symbolic computation can be slower than numerical computation; optimization is recommended for large-scale calculations.
- If you encounter issues with dependencies, environment, or performance, please first check the versions of Python and the dependency packages.

## Reference Documentation
- SymPy Official Documentation: https://docs.sympy.org/latest/
- For MCP service-related information, please refer to the platform documentation.