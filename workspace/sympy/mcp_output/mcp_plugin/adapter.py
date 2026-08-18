import os
import sys

# Set path
source_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "source")
sys.path.insert(0, source_path)

# Import modules
from sympy.core import symbols, expand, Basic, Expr
from sympy.simplify import simplify
from sympy.solvers import solve, linsolve, Solver
from sympy.calculus import diff, integrate, Derivative, Integral
from sympy.polys import Poly, factor, Polynomial
from sympy.functions import sin, cos, exp, Function

class Adapter:
    """
    MCP plugin Import mode adapter class.
    Provides adaptation and calling of sympy library core functionality.
    """
    
    def __init__(self):
        self.mode = "import"
    
    # -------------------- Symbolic Expression Module --------------------
    
    def create_symbol(self, name):
        """
        Create symbol.
        
        Parameters:
        name (str): Name of the symbol.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            symbol = symbols(name)
            return {"status": "success", "result": symbol}
        except Exception as e:
            return {"status": "error", "message": f"Error creating symbol: {str(e)}"}
    
    def expand_expression(self, expr):
        """
        Expand expression.
        
        Parameters:
        expr (Expr): Expression to expand.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            expanded = expand(expr)
            return {"status": "success", "result": expanded}
        except Exception as e:
            return {"status": "error", "message": f"Error expanding expression: {str(e)}"}
    
    def simplify_expression(self, expr):
        """
        Simplify expression.
        
        Parameters:
        expr (Expr): Expression to simplify.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            simplified = simplify(expr)
            return {"status": "success", "result": simplified}
        except Exception as e:
            return {"status": "error", "message": f"Error simplifying expression: {str(e)}"}
    
    # -------------------- Equation Solving Module --------------------
    
    def solve_equation(self, equation, symbol):
        """
        Solve equation.
        
        Parameters:
        equation (Expr): Equation expression.
        symbol (Symbol): Unknown variable in the equation.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            solution = solve(equation, symbol)
            return {"status": "success", "result": solution}
        except Exception as e:
            return {"status": "error", "message": f"Error solving equation: {str(e)}"}
    
    def linear_solve(self, equations, symbols):
        """
        Solve linear system of equations.
        
        Parameters:
        equations (list): List of equations.
        symbols (list): List of unknown variables.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            solution = linsolve(equations, symbols)
            return {"status": "success", "result": solution}
        except Exception as e:
            return {"status": "error", "message": f"Error solving linear system of equations: {str(e)}"}
    
    # -------------------- Calculus Module --------------------
    
    def differentiate(self, expr, symbol):
        """
        Differentiate.
        
        Parameters:
        expr (Expr): Expression to differentiate.
        symbol (Symbol): Variable to differentiate with respect to.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            derivative = diff(expr, symbol)
            return {"status": "success", "result": derivative}
        except Exception as e:
            return {"status": "error", "message": f"Error differentiating: {str(e)}"}
    
    def integrate_expression(self, expr, symbol):
        """
        Integrate.
        
        Parameters:
        expr (Expr): Expression to integrate.
        symbol (Symbol): Variable of integration.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            integral = integrate(expr, symbol)
            return {"status": "success", "result": integral}
        except Exception as e:
            return {"status": "error", "message": f"Error integrating: {str(e)}"}
    
    # -------------------- Polynomial Module --------------------
    
    def create_polynomial(self, expr):
        """
        Create polynomial.
        
        Parameters:
        expr (Expr): Polynomial expression.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            polynomial = Poly(expr)
            return {"status": "success", "result": polynomial}
        except Exception as e:
            return {"status": "error", "message": f"Error creating polynomial: {str(e)}"}
    
    def factor_polynomial(self, expr):
        """
        Factor polynomial.
        
        Parameters:
        expr (Expr): Polynomial expression.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            factored = factor(expr)
            return {"status": "success", "result": factored}
        except Exception as e:
            return {"status": "error", "message": f"Error factoring polynomial: {str(e)}"}
    
    # -------------------- Mathematical Functions Module --------------------
    
    def calculate_sin(self, value):
        """
        Calculate sine value.
        
        Parameters:
        value (Expr): Input value.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            result = sin(value)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Error calculating sine value: {str(e)}"}
    
    def calculate_cos(self, value):
        """
        Calculate cosine value.
        
        Parameters:
        value (Expr): Input value.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            result = cos(value)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Error calculating cosine value: {str(e)}"}
    
    def calculate_exp(self, value):
        """
        Calculate exponential value.
        
        Parameters:
        value (Expr): Input value.
        
        Returns:
        dict: Dictionary containing status and result.
        """
        try:
            result = exp(value)
            return {"status": "success", "result": result}
        except Exception as e:
            return {"status": "error", "message": f"Error calculating exponential value: {str(e)}"}
    
    # -------------------- Degradation Handling --------------------
    
    def handle_import_failure(self):
        """
        Handle import failure.
        
        Returns:
        dict: Dictionary containing status and degradation information.
        """
        return {"status": "error", "message": "Import of sympy module failed, degraded mode entered."}